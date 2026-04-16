"""
場・艇番・オッズ帯別セグメント分析

combo CSV（run_grid_search.py または run_backtest.py で生成）を使って、
どのセグメントでモデルが利益を生んでいるかを可視化する。

分析軸:
  - 場別 (stadium_id 1〜24)
  - コース別 (combo の 1 番目艇番 = 1コース〜6コース)
  - オッズ帯別 (100x未満, 100-300x, 300-1000x, 1000x以上)
  - 確率帯別 (0-3%, 3-5%, 5-10%, 10%以上)

出力:
  artifacts/segment_stadium_YYYYMM.csv   場別 ROI
  artifacts/segment_course_YYYYMM.csv    コース別 ROI
  artifacts/segment_odds_YYYYMM.csv      オッズ帯別 ROI
  artifacts/segment_prob_YYYYMM.csv      確率帯別 ROI

使い方:
  # combos_202512.csv が既にある場合
  python run_segment_analysis.py --combos-csv artifacts/combos_202512.csv

  # テスト年月を指定して自動生成
  python run_segment_analysis.py --year 2025 --month 12 --real-odds

オプション:
  --combos-csv        既存の combo CSV パス（指定時はデータ生成をスキップ）
  --year              テスト年（combo CSV 生成時に使用）
  --month             テスト月（combo CSV 生成時に使用）
  --real-odds         実オッズを使用
  --prob-threshold    分析に使う確率閾値（デフォルト: 0.03 = 3%）
  --ev-threshold      分析に使う EV 閾値（デフォルト: 1.2）
  --max-bets          1 レース最大賭け点数（デフォルト: 5）
  --bet-amount        1 点賭け金（円）（デフォルト: 100）
  --output-dir        出力先ディレクトリ（デフォルト: artifacts/）
"""
import argparse
import calendar
import logging
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.history_downloader import (
    DATA_DIR,
    download_day_data,
    extract_lzh,
    parse_result_file,
)
from collector.odds_downloader import load_or_download_month_odds
from collector.program_downloader import load_program_month, merge_program_data
from backtest.engine import run_backtest_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"

# 場名マッピング
STADIUM_NAMES: dict[int, str] = {
    1: "桐生",  2: "戸田",  3: "江戸川", 4: "平和島", 5: "多摩川",
    6: "浜名湖", 7: "蒲郡",  8: "常滑",   9: "津",     10: "三国",
    11: "びわこ", 12: "住之江", 13: "尼崎", 14: "鳴門",  15: "丸亀",
    16: "児島",  17: "宮島",  18: "徳山",  19: "下関",  20: "若松",
    21: "芦屋",  22: "福岡",  23: "唐津",  24: "大村",
}


def load_month_data(year: int, month: int, max_workers: int = 8) -> pd.DataFrame:
    days_in_month = calendar.monthrange(year, month)[1]
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_seg_"))
    days = [d for d in range(1, days_in_month + 1) if date(year, month, d) <= date.today()]

    def _fetch_day(day: int) -> list[dict]:
        try:
            lzh = download_day_data(year, month, day, dest_dir=DATA_DIR)
            if lzh is None:
                return []
            extract_dir = tmpdir / lzh.stem
            files = extract_lzh(lzh, extract_dir)
            return [rec for f in files for rec in parse_result_file(f)]
        except Exception as exc:
            logger.debug("Skip %d-%02d-%02d: %s", year, month, day, exc)
            return []

    all_records: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_day, d): d for d in days}
            for future in as_completed(futures):
                all_records.extend(future.result())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    df_k = pd.DataFrame(all_records) if all_records else pd.DataFrame()
    df_b = load_program_month(year, month, max_workers=max_workers)
    return merge_program_data(df_k, df_b)


def get_model() -> object:
    existing = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
    if not existing:
        logger.error("No model found in %s.", ARTIFACTS_DIR)
        sys.exit(1)
    logger.info("Using model: %s", existing[0])
    return joblib.load(existing[0])


def load_or_build_combos(
    args: argparse.Namespace,
) -> tuple[pd.DataFrame, str]:
    """combo CSV を読み込む or 生成して返す。(combos_df, label) を返す。"""
    if args.combos_csv:
        logger.info("既存 combo CSV を読み込み: %s", args.combos_csv)
        combos_df = pd.read_csv(args.combos_csv)
        label = Path(args.combos_csv).stem.replace("combos_", "")
        return combos_df, label

    if args.year is None or args.month is None:
        logger.error("--year と --month を指定してください（または --combos-csv を指定）。")
        sys.exit(1)

    label = f"{args.year}{args.month:02d}"
    combos_csv_cache = ARTIFACTS_DIR / f"combos_{label}.csv"

    if combos_csv_cache.exists():
        logger.info("キャッシュ済み combo CSV を使用: %s", combos_csv_cache)
        return pd.read_csv(combos_csv_cache), label

    logger.info("テストデータを取得中: %d-%02d", args.year, args.month)
    model = get_model()
    df_test = load_month_data(args.year, args.month)
    if df_test.empty:
        logger.error("データが見つかりません: %d-%02d", args.year, args.month)
        sys.exit(1)

    odds_by_race: dict[str, dict[str, float]] = {}
    if args.real_odds:
        odds_by_race = load_or_download_month_odds(args.year, args.month, df_test)
        logger.info("実オッズ: %d レース分取得", len(odds_by_race))

    logger.info("全組み合わせデータを収集中...")
    _, skipped, combo_records = run_backtest_batch(
        df_test=df_test,
        model=model,
        odds_by_race=odds_by_race,
        prob_threshold=0.0,
        bet_amount=args.bet_amount,
        max_bets_per_race=120,
        ev_threshold=0.0,
        collect_combos=True,
    )
    logger.info("収集完了: %d 組み合わせ、スキップ %d レース", len(combo_records), skipped)
    combos_df = pd.DataFrame(combo_records)
    combos_df.to_csv(combos_csv_cache, index=False)
    logger.info("Combo CSV 保存: %s", combos_csv_cache)
    return combos_df, label


def apply_filter(
    combos_df: pd.DataFrame,
    prob_threshold: float,
    ev_threshold: float,
    max_bets: int,
    bet_amount: int,
) -> pd.DataFrame:
    """閾値フィルタと max_bets 制限を適用したベット対象 combo を返す。"""
    mask = (
        (combos_df["win_probability"] >= prob_threshold)
        & (combos_df["expected_value"] >= ev_threshold)
    )
    filtered = combos_df[mask].copy()
    filtered = filtered.sort_values("expected_value", ascending=False)
    filtered = filtered.groupby("race_id").head(max_bets).reset_index(drop=True)
    filtered["actual_bet"] = bet_amount
    return filtered


def segment_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """指定した列でグループ化してROI等を集計する。"""
    rows = []
    for val, grp in df.groupby(group_col, observed=True):
        n_bets = len(grp)
        n_wins = int(grp["is_hit"].sum())
        wagered = float((grp["actual_bet"]).sum())
        payout = float((grp["is_hit"] * grp["odds"] * grp["actual_bet"]).sum())
        roi = (payout / wagered - 1) * 100 if wagered > 0 else float("nan")
        win_rate = n_wins / n_bets * 100 if n_bets > 0 else float("nan")
        avg_hit_odds = float(grp.loc[grp["is_hit"] == 1, "odds"].mean()) if n_wins > 0 else float("nan")
        rows.append({
            group_col:      val,
            "n_bets":       n_bets,
            "n_wins":       n_wins,
            "wagered":      wagered,
            "payout":       payout,
            "roi":          roi,
            "win_rate":     win_rate,
            "avg_hit_odds": avg_hit_odds,
        })
    return pd.DataFrame(rows)


def print_segment_table(
    seg_df: pd.DataFrame,
    group_col: str,
    title: str,
    name_map: dict | None = None,
    min_bets: int = 10,
) -> None:
    valid = seg_df[seg_df["n_bets"] >= min_bets].copy()
    if valid.empty:
        print(f"  [{title}] データ不足（賭け<{min_bets}点のセグメントのみ）")
        return

    print()
    print(f"  [{title}]  ※ 賭け点数 {min_bets} 点未満は除外")
    print(f"  {'':>12}  {'賭け点':>6}  {'投資':>10}  {'払戻':>10}  {'ROI':>7}  {'的中率':>6}  {'的中'}")
    print("  " + "-" * 66)
    for _, row in valid.sort_values("roi", ascending=False).iterrows():
        key_val = row[group_col]
        if name_map:
            label = name_map.get(int(key_val), str(key_val))
        else:
            label = str(key_val)
        print(
            f"  {label:>12}  {int(row['n_bets']):>6,}  "
            f"¥{row['wagered']:>9,.0f}  ¥{row['payout']:>9,.0f}  "
            f"{row['roi']:>+6.1f}%  {row['win_rate']:>5.2f}%  {int(row['n_wins'])}"
        )


def analyze_stadium(filtered: pd.DataFrame) -> pd.DataFrame:
    seg = segment_summary(filtered, "stadium_id")
    seg["stadium_name"] = seg["stadium_id"].apply(
        lambda x: STADIUM_NAMES.get(int(x), f"場{int(x)}")
    )
    return seg.sort_values("roi", ascending=False)


def analyze_course(filtered: pd.DataFrame) -> pd.DataFrame:
    """combo の 1 番目の艇番をコースとみなして分析する。"""
    filtered = filtered.copy()
    filtered["lead_boat"] = filtered["combination"].str.split("-").str[0].astype(int)
    seg = segment_summary(filtered, "lead_boat")
    seg = seg.rename(columns={"lead_boat": "course"})
    return seg.sort_values("roi", ascending=False)


def analyze_odds_band(filtered: pd.DataFrame) -> pd.DataFrame:
    """オッズ帯別に分析する。"""
    filtered = filtered.copy()
    bins = [0, 100, 300, 1000, float("inf")]
    labels = ["~100x", "100-300x", "300-1000x", "1000x+"]
    filtered["odds_band"] = pd.cut(filtered["odds"], bins=bins, labels=labels, right=False)
    seg = segment_summary(filtered, "odds_band")
    return seg


def analyze_prob_band(filtered: pd.DataFrame) -> pd.DataFrame:
    """確率帯別に分析する。"""
    filtered = filtered.copy()
    bins = [0, 0.03, 0.05, 0.10, float("inf")]
    labels = ["~3%", "3-5%", "5-10%", "10%+"]
    filtered["prob_band"] = pd.cut(filtered["win_probability"], bins=bins, labels=labels, right=False)
    seg = segment_summary(filtered, "prob_band")
    return seg


def main() -> None:
    parser = argparse.ArgumentParser(
        description="場・艇番・オッズ帯別セグメント分析",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--combos-csv",    type=str,   default=None,  help="既存 combo CSV のパス")
    parser.add_argument("--year",          type=int,   default=None,  help="テスト年（combo 生成時）")
    parser.add_argument("--month",         type=int,   default=None,  help="テスト月（combo 生成時）")
    parser.add_argument("--real-odds",     action="store_true",       help="実オッズを使用")
    parser.add_argument("--prob-threshold",type=float, default=0.03,  help="確率閾値")
    parser.add_argument("--ev-threshold",  type=float, default=1.2,   help="EV 閾値")
    parser.add_argument("--max-bets",      type=int,   default=5,     help="1 レース最大賭け点数")
    parser.add_argument("--bet-amount",    type=int,   default=100,   help="1 点賭け金（円）")
    parser.add_argument("--min-bets",      type=int,   default=10,    help="表示最小賭け点数（少ないセグメントを除外）")
    parser.add_argument("--output-dir",    type=str,   default=None,  help="出力先ディレクトリ")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else ARTIFACTS_DIR
    out_dir.mkdir(exist_ok=True)

    # ── 1. combo CSV 取得 ──────────────────────────────────
    combos_df, label = load_or_build_combos(args)

    if combos_df.empty:
        logger.error("combos_df が空です。")
        sys.exit(1)

    logger.info("combo 総数: %d", len(combos_df))

    # ── 2. 閾値フィルタ適用 ──────────────────────────────────
    filtered = apply_filter(
        combos_df,
        prob_threshold=args.prob_threshold,
        ev_threshold=args.ev_threshold,
        max_bets=args.max_bets,
        bet_amount=args.bet_amount,
    )
    logger.info(
        "フィルタ後: %d 点 / %d レース  (prob≥%.1f%% × EV≥%.2f)",
        len(filtered),
        filtered["race_id"].nunique() if not filtered.empty else 0,
        args.prob_threshold * 100,
        args.ev_threshold,
    )

    if filtered.empty:
        logger.error("フィルタ後にデータがありません。閾値を緩めてください。")
        sys.exit(1)

    # 全体サマリー
    n_bets = len(filtered)
    n_wins = int(filtered["is_hit"].sum())
    wagered = float(filtered["actual_bet"].sum())
    payout = float((filtered["is_hit"] * filtered["odds"] * filtered["actual_bet"]).sum())
    roi = (payout / wagered - 1) * 100 if wagered > 0 else float("nan")
    win_rate = n_wins / n_bets * 100 if n_bets > 0 else float("nan")

    print()
    print("=" * 70)
    print(f"  セグメント分析  [{label}]  prob≥{args.prob_threshold*100:.0f}% × EV≥{args.ev_threshold:.1f}")
    print("=" * 70)
    print(f"  ベット合計: {n_bets:,} 点 / 投資: ¥{wagered:,.0f} / ROI: {roi:+.1f}% / 的中率: {win_rate:.2f}%")

    # ── 3. 場別分析 ──────────────────────────────────────
    stadium_seg = analyze_stadium(filtered)
    out_stadium = out_dir / f"segment_stadium_{label}.csv"
    stadium_seg.to_csv(out_stadium, index=False)
    logger.info("場別セグメント保存: %s", out_stadium)

    print_segment_table(
        stadium_seg.rename(columns={"stadium_id": "key"}),
        "key",
        "場別 ROI",
        name_map={i: f"{i}.{STADIUM_NAMES.get(i, '?')}" for i in range(1, 25)},
        min_bets=args.min_bets,
    )

    # ── 4. コース別分析（1着艇番）─────────────────────────
    course_seg = analyze_course(filtered)
    out_course = out_dir / f"segment_course_{label}.csv"
    course_seg.to_csv(out_course, index=False)
    logger.info("コース別セグメント保存: %s", out_course)

    print_segment_table(
        course_seg.rename(columns={"course": "key"}),
        "key",
        "コース別 ROI（combo 1着艇番）",
        name_map={i: f"{i}コース" for i in range(1, 7)},
        min_bets=args.min_bets,
    )

    # ── 5. オッズ帯別分析 ─────────────────────────────────
    odds_seg = analyze_odds_band(filtered)
    out_odds = out_dir / f"segment_odds_{label}.csv"
    odds_seg.to_csv(out_odds, index=False)
    logger.info("オッズ帯別セグメント保存: %s", out_odds)

    print_segment_table(
        odds_seg.rename(columns={"odds_band": "key"}),
        "key",
        "オッズ帯別 ROI",
        min_bets=args.min_bets,
    )

    # ── 6. 確率帯別分析 ─────────────────────────────────
    prob_seg = analyze_prob_band(filtered)
    out_prob = out_dir / f"segment_prob_{label}.csv"
    prob_seg.to_csv(out_prob, index=False)
    logger.info("確率帯別セグメント保存: %s", out_prob)

    print_segment_table(
        prob_seg.rename(columns={"prob_band": "key"}),
        "key",
        "確率帯別 ROI（trifecta 過大推定に注意）",
        min_bets=args.min_bets,
    )

    print()
    print("=" * 70)
    print("  ※ trifecta 10%以上は Plackett-Luce 過大推定（7〜31x）の可能性あり")
    print(f"  出力先: {out_dir}/segment_*_{label}.csv")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
