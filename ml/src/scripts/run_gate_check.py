"""
評価ゲート: バックテスト結果を KPI 機械判定し、ゾーン判定を出力する。

使い方:
  python ml/src/scripts/run_gate_check.py --year 2025 --month 12
  python ml/src/scripts/run_gate_check.py --csv artifacts/backtest_202512.csv
  python ml/src/scripts/run_gate_check.py --year 2025 --month 12 --no-append  # kpi_history に追記しない
  python ml/src/scripts/run_gate_check.py --year 2025 --month 12 --source model-loop  # 由来記録

出力:
  artifacts/gate_result_YYYYMM[_<label>].json  ... ゾーン判定 + KPI（--label 指定時はサフィックス付与）
  artifacts/kpi_history.jsonl                  ... 1 ラン 1 行追記（--no-append で無効）

exit code:
  0  ... normal / caution（ROI >= 300%）
  1  ... warning / danger（ROI < 300% または ROI < 0%）

ゾーン定義（CLAUDE.md 運用ルール準拠）:
  normal  ... ROI >= 500%
  caution ... 300% <= ROI < 500%
  warning ... 0% <= ROI < 300%
  danger  ... ROI < 0%

サニティチェック（2026-04-24 H3 対応）:
  avg_odds が過去 kpi_history の中央値比で大きく乖離している場合、
  sanity.avg_odds_check に "suspicious" / "warning" を記録する。
  2026-04-24 発覚のオッズパースバグ（avg_odds が異常に高く ROI +794% が幻影だった事例）を
  早期検知する目的。判定のみで exit code には影響しない。
"""
import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"

# ゾーン閾値（%）
ZONE_THRESHOLDS = {
    "normal": 500.0,
    "caution": 300.0,
    "warning": 0.0,
    # danger: ROI < 0%
}

# サニティチェック: avg_odds の中央値比による乖離警告（H3 対応）
SANITY_HISTORY_WINDOW = 12      # 過去何ランまでを参照するか
SANITY_MIN_SAMPLES = 3          # 判定に必要な最小サンプル数
SANITY_SUSPICIOUS_RATIO = 2.0   # 中央値の 2 倍以上で "suspicious"
SANITY_WARNING_RATIO = 3.0      # 中央値の 3 倍以上で "warning"

# kpi_history の source として許容する値（H4 対応）
VALID_SOURCES = {
    "manual",              # 手動実行（デフォルト）
    "inner-loop",          # /inner-loop（現在凍結中）
    "model-loop",          # /model-loop
    "auto-backtest-loop",  # フェーズ2 の定期ワークフロー
    "quarterly-walkforward",
    "production",          # 本番 predict 結果
}


def classify_zone(roi: float) -> str:
    if roi >= ZONE_THRESHOLDS["normal"]:
        return "normal"
    if roi >= ZONE_THRESHOLDS["caution"]:
        return "caution"
    if roi >= ZONE_THRESHOLDS["warning"]:
        return "warning"
    return "danger"


def compute_kpi(df: pd.DataFrame) -> dict:
    bet_df = df[df["bets_placed"] > 0].copy()

    total_bets = int(df["bets_placed"].sum())
    total_wagered = float(df["amount_wagered"].sum())
    total_payout = float(df["payout_received"].sum())
    wins = int(df["matched"].sum())

    roi = (total_payout / total_wagered - 1) * 100 if total_wagered > 0 else 0.0
    win_rate = wins / total_bets * 100 if total_bets > 0 else 0.0

    matched_df = df[df["matched"]]
    avg_odds = float(matched_df["matched_odds"].mean()) if len(matched_df) > 0 else 0.0
    avg_top_prob = float(bet_df["top_prob"].mean()) if len(bet_df) > 0 else 0.0

    period_from = str(df["race_date"].min())
    period_to = str(df["race_date"].max())

    return {
        "period_from": period_from,
        "period_to": period_to,
        "total_bets": total_bets,
        "total_wagered": total_wagered,
        "total_payout": total_payout,
        "profit": total_payout - total_wagered,
        "roi_pct": round(roi, 2),
        "wins": wins,
        "win_rate_pct": round(win_rate, 4),
        "avg_odds": round(avg_odds, 2),
        "avg_top_prob": round(avg_top_prob, 6),
    }


def get_commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def get_model_version() -> str:
    models = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
    return models[0].stem if models else "unknown"


def get_model_version_hash() -> str:
    """最新モデルファイルの内容ハッシュ（短縮 SHA256）を返す（H4 対応）。

    同じ model_version_* 名でも中身が違えば別モデルとして区別できるように、
    実ファイルのハッシュを kpi_history に残す。kpi 行がどのモデルで
    生成されたかを事後に厳密に突合できる。
    """
    models = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
    if not models:
        return "unknown"
    try:
        h = hashlib.sha256()
        with open(models[0], "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:12]
    except Exception:
        return "unknown"


def load_recent_avg_odds(window: int = SANITY_HISTORY_WINDOW) -> list[float]:
    """kpi_history.jsonl から直近 window 件の avg_odds を取得（H3 対応）。"""
    history_path = ARTIFACTS_DIR / "kpi_history.jsonl"
    if not history_path.exists():
        return []
    values: list[float] = []
    try:
        with open(history_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                odds = rec.get("avg_odds")
                if isinstance(odds, (int, float)) and odds > 0:
                    values.append(float(odds))
    except Exception:
        return []
    return values[-window:]


def check_avg_odds_sanity(avg_odds: float) -> dict:
    """avg_odds が過去の中央値比で大きく乖離していないか判定（H3 対応）。

    2026-04-24 のオッズパースバグでは avg_odds が異常値となり ROI +794% が
    幻影となった。同様の破損を早期検知するため、過去 N 件の中央値との
    比率でサニティチェックする。
    """
    history = load_recent_avg_odds()
    if len(history) < SANITY_MIN_SAMPLES:
        return {
            "avg_odds_check": "insufficient_data",
            "avg_odds_history_n": len(history),
            "avg_odds_median": None,
            "avg_odds_ratio": None,
        }
    median = statistics.median(history)
    ratio = avg_odds / median if median > 0 else None

    if ratio is None:
        status = "insufficient_data"
    elif ratio >= SANITY_WARNING_RATIO or ratio <= 1.0 / SANITY_WARNING_RATIO:
        status = "warning"
    elif ratio >= SANITY_SUSPICIOUS_RATIO or ratio <= 1.0 / SANITY_SUSPICIOUS_RATIO:
        status = "suspicious"
    else:
        status = "ok"

    return {
        "avg_odds_check": status,
        "avg_odds_history_n": len(history),
        "avg_odds_median": round(median, 2),
        "avg_odds_ratio": round(ratio, 3) if ratio is not None else None,
    }


def build_gate_result(
    kpi: dict,
    year: int,
    month: int,
    label: str | None = None,
    source: str = "manual",
) -> dict:
    zone = classify_zone(kpi["roi_pct"])
    sanity = check_avg_odds_sanity(kpi["avg_odds"])
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "period": f"{year}-{month:02d}",
        "zone": zone,
        "source": source,
        "commit_sha": get_commit_sha(),
        "model_version": get_model_version(),
        "model_version_hash": get_model_version_hash(),
        **kpi,
        "sanity": sanity,
    }
    if label:
        result["label"] = label
    return result


def append_kpi_history(record: dict) -> None:
    history_path = ARTIFACTS_DIR / "kpi_history.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[gate] KPI history appended: {history_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="バックテスト結果のゲートチェック（KPI 機械判定）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--year",  type=int, help="テスト年（--csv 未指定時に使用）")
    parser.add_argument("--month", type=int, help="テスト月（--csv 未指定時に使用）")
    parser.add_argument("--csv",   type=str, default=None, help="バックテスト結果 CSV のパス")
    parser.add_argument("--no-append", action="store_true", help="kpi_history.jsonl に追記しない")
    parser.add_argument("--label",     type=str, default=None, help="ラン識別ラベル（baseline / candidate-iter1 など）。JSON ファイル名のサフィックスに付与")
    parser.add_argument("--source",    type=str, default="manual", choices=sorted(VALID_SOURCES), help="kpi_history に記録する由来（H4 対応）")
    args = parser.parse_args()

    # CSV パスの解決
    if args.csv:
        csv_path = Path(args.csv)
    elif args.year and args.month:
        csv_path = ARTIFACTS_DIR / f"backtest_{args.year}{args.month:02d}.csv"
    else:
        parser.error("--year/--month または --csv を指定してください")

    if not csv_path.exists():
        print(f"[gate] ERROR: CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    # 年月の推定（--csv 指定時）
    year = args.year
    month = args.month
    if year is None or month is None:
        stem = csv_path.stem  # e.g. "backtest_202512"
        try:
            yyyymm = stem.split("_")[-1]
            year = int(yyyymm[:4])
            month = int(yyyymm[4:6])
        except (ValueError, IndexError):
            year, month = 0, 0

    df = pd.read_csv(csv_path)
    kpi = compute_kpi(df)
    result = build_gate_result(kpi, year, month, label=args.label, source=args.source)

    # --- ゾーン表示 ---
    zone = result["zone"]
    roi = result["roi_pct"]
    ZONE_LABELS = {
        "normal":  "[NORMAL ] ROI >= 500%",
        "caution": "[CAUTION] ROI 300-499%",
        "warning": "[WARNING] ROI 0-299%",
        "danger":  "[DANGER ] ROI < 0%",
    }
    print()
    print("=" * 62)
    print("  評価ゲート判定結果")
    print("=" * 62)
    print(f"  期間      : {result['period_from']} 〜 {result['period_to']}")
    print(f"  ROI       : {roi:+.1f}%")
    print(f"  ゾーン    : {ZONE_LABELS[zone]}")
    print(f"  ベット数  : {result['total_bets']:,} 点")
    print(f"  的中      : {result['wins']:,} 件  ({result['win_rate_pct']:.2f}%)")
    print(f"  平均オッズ: {result['avg_odds']:.1f}x")
    print(f"  avg prob  : {result['avg_top_prob']:.4f}")
    print(f"  model     : {result['model_version']}")
    print(f"  model hash: {result['model_version_hash']}")
    print(f"  source    : {result['source']}")
    print(f"  commit    : {result['commit_sha']}")

    # サニティチェック表示（H3 対応）
    sanity = result["sanity"]
    check = sanity["avg_odds_check"]
    SANITY_LABELS = {
        "ok":                "[SANITY OK  ]",
        "suspicious":        "[SANITY WARN]",
        "warning":           "[SANITY ALERT]",
        "insufficient_data": "[SANITY SKIP]",
    }
    sanity_label = SANITY_LABELS.get(check, f"[SANITY {check}]")
    if sanity["avg_odds_median"] is not None:
        print(
            f"  sanity    : {sanity_label} avg_odds ratio={sanity['avg_odds_ratio']} "
            f"(median={sanity['avg_odds_median']}, n={sanity['avg_odds_history_n']})"
        )
    else:
        print(f"  sanity    : {sanity_label} n={sanity['avg_odds_history_n']}")

    if check == "warning":
        print()
        print("  ⚠️  avg_odds が過去中央値から大きく乖離しています。")
        print("     オッズパースバグの再発（2026-04-24 発覚事例）を疑ってください。")
        print("     run_backtest.py / odds_downloader.py の出力を手動で確認することを推奨。")
    elif check == "suspicious":
        print(f"  ⚠️  avg_odds が中央値の {sanity['avg_odds_ratio']}x 乖離。監視対象。")

    print("=" * 62)
    print()

    # --- JSON 保存 ---
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    suffix = f"_{args.label}" if args.label else ""
    out_path = ARTIFACTS_DIR / f"gate_result_{year}{month:02d}{suffix}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[gate] Result saved: {out_path}")

    # --- kpi_history 追記 ---
    if not args.no_append:
        append_kpi_history(result)

    # --- exit code ---
    if zone in ("warning", "danger"):
        print(f"[gate] FAIL: zone={zone} (exit 1)")
        sys.exit(1)

    print(f"[gate] PASS: zone={zone} (exit 0)")
    sys.exit(0)


if __name__ == "__main__":
    main()
