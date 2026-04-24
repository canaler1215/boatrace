"""
評価ゲート: バックテスト結果を KPI 機械判定し、ゾーン判定を出力する。

使い方:
  python ml/src/scripts/run_gate_check.py --year 2025 --month 12
  python ml/src/scripts/run_gate_check.py --csv artifacts/backtest_202512.csv
  python ml/src/scripts/run_gate_check.py --year 2025 --month 12 --no-append  # kpi_history に追記しない

出力:
  artifacts/gate_result_YYYYMM.json  ... ゾーン判定 + KPI
  artifacts/kpi_history.jsonl        ... 1 ラン 1 行追記（--no-append で無効）

exit code:
  0  ... normal / caution（ROI >= 300%）
  1  ... warning / danger（ROI < 300% または ROI < 0%）

ゾーン定義（CLAUDE.md 運用ルール準拠）:
  normal  ... ROI >= 500%
  caution ... 300% <= ROI < 500%
  warning ... 0% <= ROI < 300%
  danger  ... ROI < 0%
"""
import argparse
import json
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


def build_gate_result(kpi: dict, year: int, month: int) -> dict:
    zone = classify_zone(kpi["roi_pct"])
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "period": f"{year}-{month:02d}",
        "zone": zone,
        "commit_sha": get_commit_sha(),
        "model_version": get_model_version(),
        **kpi,
    }


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
    result = build_gate_result(kpi, year, month)

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
    print(f"  commit    : {result['commit_sha']}")
    print("=" * 62)
    print()

    # --- JSON 保存 ---
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    out_path = ARTIFACTS_DIR / f"gate_result_{year}{month:02d}.json"
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
