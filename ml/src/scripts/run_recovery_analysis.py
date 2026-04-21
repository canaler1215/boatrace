"""
T6-B リカバリー分析

3連単（S6標準パラメータ）と3連複（T6-A最適パラメータ）を同一レースで比較し、
「3連単外れ × 3連複的中」のリカバリー効果を定量化する。

使い方:
  # 合成オッズで高速確認（2025-10〜12）
  python run_recovery_analysis.py --start 2025-10 --end 2025-12

  # 実オッズで本番相当の分析
  python run_recovery_analysis.py --start 2025-10 --end 2025-12 --real-odds

  # パラメータをカスタマイズ
  python run_recovery_analysis.py --start 2025-10 --end 2025-12 --real-odds \\
    --trifecta-prob 0.07 --trifecta-ev 2.0 \\
    --trio-prob 0.20 --trio-ev 4.0

分析観点:
  - 3連単的中 & 3連複的中: 相関の強さ
  - 3連単外れ & 3連複的中: 純リカバリー件数・払戻額
  - 両方購入時の合計ROI vs 3連単単独ROI
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
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.history_downloader import (
    DATA_DIR,
    download_day_data,
    extract_lzh,
    parse_result_file,
)
from collector.odds_downloader import load_or_download_month_odds, load_or_download_month_trio_odds
from collector.program_downloader import load_program_month, merge_program_data
from backtest.engine import run_backtest_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"


def parse_ym(s: str) -> tuple[int, int]:
    try:
        year, month = s.split("-")
        return int(year), int(month)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid format: '{s}'. Use YYYY-MM.")


def month_range(start_year: int, start_month: int, end_year: int, end_month: int):
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def load_month_data(year: int, month: int, max_workers: int = 8) -> pd.DataFrame:
    days_in_month = calendar.monthrange(year, month)[1]
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_ra_"))
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


def run_month(
    year: int,
    month: int,
    model,
    odds_by_race: dict,
    trio_odds_by_race: dict,
    args: argparse.Namespace,
    df_month: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """1ヶ月分の3連単・3連複バックテストを実行し、それぞれのDataFrameを返す。"""
    common_kwargs = dict(
        df_test=df_month,
        model=model,
        bet_amount=args.bet_amount,
        max_bets_per_race=args.max_bets,
        kelly_fraction=0.0,
        kelly_bankroll=100_000.0,
        exclude_stadiums=args.exclude_stadiums,
    )

    # 3連単
    tf_results, _ = run_backtest_batch(
        odds_by_race=odds_by_race,
        prob_threshold=args.trifecta_prob,
        ev_threshold=args.trifecta_ev,
        exclude_courses=args.exclude_courses,
        min_odds=args.min_odds,
        bet_type="trifecta",
        **common_kwargs,
    )
    df_tf = pd.DataFrame(tf_results) if tf_results else pd.DataFrame()

    # 3連複
    trio_results, _ = run_backtest_batch(
        odds_by_race=trio_odds_by_race,
        prob_threshold=args.trio_prob,
        ev_threshold=args.trio_ev,
        exclude_courses=None,
        min_odds=None,
        bet_type="trio",
        **common_kwargs,
    )
    df_trio = pd.DataFrame(trio_results) if trio_results else pd.DataFrame()

    return df_tf, df_trio


def print_recovery_analysis(df_tf: pd.DataFrame, df_trio: pd.DataFrame) -> None:
    """3連単・3連複を race_id で結合してリカバリー分析を出力する。"""
    if df_tf.empty and df_trio.empty:
        print("データなし")
        return

    # race_id を文字列で揃えてマージ
    if not df_tf.empty:
        df_tf = df_tf.copy()
        df_tf["race_id"] = df_tf["race_id"].astype(str)
    if not df_trio.empty:
        df_trio = df_trio.copy()
        df_trio["race_id"] = df_trio["race_id"].astype(str)

    # 両方を outer join
    merged = pd.merge(
        df_tf[["race_id", "bets_placed", "matched", "amount_wagered", "payout_received"]].rename(
            columns={
                "bets_placed": "tf_bets",
                "matched": "tf_hit",
                "amount_wagered": "tf_wagered",
                "payout_received": "tf_payout",
            }
        ) if not df_tf.empty else pd.DataFrame(columns=["race_id", "tf_bets", "tf_hit", "tf_wagered", "tf_payout"]),
        df_trio[["race_id", "bets_placed", "matched", "amount_wagered", "payout_received"]].rename(
            columns={
                "bets_placed": "trio_bets",
                "matched": "trio_hit",
                "amount_wagered": "trio_wagered",
                "payout_received": "trio_payout",
            }
        ) if not df_trio.empty else pd.DataFrame(columns=["race_id", "trio_bets", "trio_hit", "trio_wagered", "trio_payout"]),
        on="race_id",
        how="outer",
    )

    merged["tf_bets"]    = merged["tf_bets"].fillna(0).astype(int)
    merged["tf_hit"]     = merged["tf_hit"].fillna(False).astype(bool)
    merged["tf_wagered"] = merged["tf_wagered"].fillna(0.0)
    merged["tf_payout"]  = merged["tf_payout"].fillna(0.0)
    merged["trio_bets"]   = merged["trio_bets"].fillna(0).astype(int)
    merged["trio_hit"]    = merged["trio_hit"].fillna(False).astype(bool)
    merged["trio_wagered"] = merged["trio_wagered"].fillna(0.0)
    merged["trio_payout"]  = merged["trio_payout"].fillna(0.0)

    tf_placed   = merged["tf_bets"] > 0
    trio_placed = merged["trio_bets"] > 0

    # ── カテゴリ分類 ────────────────────────────────────────────
    both_hit        = tf_placed & merged["tf_hit"] & trio_placed & merged["trio_hit"]
    tf_only_hit     = tf_placed & merged["tf_hit"] & trio_placed & ~merged["trio_hit"]
    trio_only_hit   = tf_placed & ~merged["tf_hit"] & trio_placed & merged["trio_hit"]  # 純リカバリー
    neither_hit     = tf_placed & ~merged["tf_hit"] & trio_placed & ~merged["trio_hit"]
    tf_only_placed  = tf_placed & ~trio_placed
    trio_only_placed= ~tf_placed & trio_placed
    neither_placed  = ~tf_placed & ~trio_placed

    total_races = len(merged)

    def _roi(w: float, p: float) -> str:
        if w <= 0:
            return "N/A"
        return f"{(p/w - 1)*100:+.1f}%"

    print()
    print("=" * 70)
    print("  T6-B リカバリー分析")
    print("=" * 70)
    print(f"  総レース数: {total_races:,}")
    print()

    # ── 3連単単独サマリー ────────────────────────────────────────
    tf_w = merged.loc[tf_placed, "tf_wagered"].sum()
    tf_p = merged.loc[tf_placed, "tf_payout"].sum()
    tf_hits = int(merged.loc[tf_placed, "tf_hit"].sum())
    tf_bets_total = int(merged.loc[tf_placed, "tf_bets"].sum())
    print("  [3連単 単独]")
    print(f"    ベット点数: {tf_bets_total:,}  投資: ¥{tf_w:,.0f}  払戻: ¥{tf_p:,.0f}  ROI: {_roi(tf_w, tf_p)}")
    print(f"    的中: {tf_hits:,}件  的中率/点: {tf_hits/tf_bets_total*100:.2f}%" if tf_bets_total > 0 else "    的中データなし")

    # ── 3連複単独サマリー ────────────────────────────────────────
    trio_w = merged.loc[trio_placed, "trio_wagered"].sum()
    trio_p = merged.loc[trio_placed, "trio_payout"].sum()
    trio_hits = int(merged.loc[trio_placed, "trio_hit"].sum())
    trio_bets_total = int(merged.loc[trio_placed, "trio_bets"].sum())
    print()
    print("  [3連複 単独]")
    print(f"    ベット点数: {trio_bets_total:,}  投資: ¥{trio_w:,.0f}  払戻: ¥{trio_p:,.0f}  ROI: {_roi(trio_w, trio_p)}")
    print(f"    的中: {trio_hits:,}件  的中率/点: {trio_hits/trio_bets_total*100:.2f}%" if trio_bets_total > 0 else "    的中データなし")

    # ── 組み合わせ戦略（両方購入）────────────────────────────────
    both_w = merged["tf_wagered"].sum() + merged["trio_wagered"].sum()
    both_p = merged["tf_payout"].sum() + merged["trio_payout"].sum()
    print()
    print("  [両方購入 合計]")
    print(f"    投資: ¥{both_w:,.0f}  払戻: ¥{both_p:,.0f}  ROI: {_roi(both_w, both_p)}")

    # ── カテゴリ別分析 ───────────────────────────────────────────
    print()
    print("  [カテゴリ別（両方ベット済みレースのみ）]")
    print(f"  {'カテゴリ':30}  {'レース':>6}  {'比率':>6}  {'3連複払戻':>12}")
    print("  " + "-" * 62)

    both_placed = tf_placed & trio_placed
    n_both_placed = int(both_placed.sum())

    cats = [
        ("3連単◯ & 3連複◯（両方的中）",   both_hit),
        ("3連単◯ & 3連複✗（3連単のみ）",  tf_only_hit),
        ("3連単✗ & 3連複◯（純リカバリー）", trio_only_hit),
        ("3連単✗ & 3連複✗（両方外れ）",   neither_hit),
    ]
    for label, mask in cats:
        n = int(mask.sum())
        pct = n / n_both_placed * 100 if n_both_placed > 0 else 0.0
        trio_pay = merged.loc[mask, "trio_payout"].sum()
        print(f"  {label:30}  {n:>6,}  {pct:>5.1f}%  ¥{trio_pay:>10,.0f}")

    print()
    print(f"  ※ 両方ベット実行レース: {n_both_placed:,} / {total_races:,}")

    # ── 純リカバリー詳細 ─────────────────────────────────────────
    n_recovery = int(trio_only_hit.sum())
    if n_recovery > 0:
        rec_payout = merged.loc[trio_only_hit, "trio_payout"].sum()
        rec_wagered_tf = merged.loc[trio_only_hit, "tf_wagered"].sum()
        rec_wagered_trio = merged.loc[trio_only_hit, "trio_wagered"].sum()
        net_recovery = rec_payout - rec_wagered_tf - rec_wagered_trio
        print()
        print("  [純リカバリー詳細（3連単外れ × 3連複的中）]")
        print(f"    件数       : {n_recovery:,}件")
        print(f"    3連複払戻  : ¥{rec_payout:,.0f}")
        print(f"    同レース投資: ¥{rec_wagered_tf + rec_wagered_trio:,.0f}（3連単¥{rec_wagered_tf:,.0f} + 3連複¥{rec_wagered_trio:,.0f}）")
        print(f"    純利益貢献  : ¥{net_recovery:+,.0f}（リカバリーレースの損益）")
        avg_payout = rec_payout / n_recovery
        print(f"    avg払戻/件  : ¥{avg_payout:,.0f}")

    # ── ROI比較まとめ ────────────────────────────────────────────
    print()
    print("  [ROI比較まとめ]")
    tf_roi_str    = _roi(tf_w, tf_p)
    trio_roi_str  = _roi(trio_w, trio_p)
    both_roi_str  = _roi(both_w, both_p)
    print(f"    3連単単独          : {tf_roi_str}")
    print(f"    3連複単独          : {trio_roi_str}")
    print(f"    両方購入（合算）   : {both_roi_str}")
    print()
    print("=" * 70)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T6-B リカバリー分析: 3連単(S6標準) vs 3連複(T6-A最適)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", type=parse_ym, required=True, metavar="YYYY-MM", help="分析開始月")
    parser.add_argument("--end",   type=parse_ym, required=True, metavar="YYYY-MM", help="分析終了月")
    parser.add_argument("--real-odds", action="store_true", help="実オッズ使用")
    parser.add_argument("--model-path", type=str, default=None, help="モデルファイルパス（省略時は最新）")
    parser.add_argument("--bet-amount", type=int, default=100, help="1点賭け金（円）")
    parser.add_argument("--max-bets",   type=int, default=5,   help="1レース最大ベット点数")

    # 3連単パラメータ（S6標準デフォルト）
    parser.add_argument("--trifecta-prob", type=float, default=0.07, help="3連単: 的中確率閾値")
    parser.add_argument("--trifecta-ev",   type=float, default=2.0,  help="3連単: EV閾値")
    parser.add_argument("--exclude-courses",  type=int, nargs="+", default=[2, 4, 5], help="3連単: 除外1着コース")
    parser.add_argument("--min-odds",         type=float, default=100.0, help="3連単: 最小オッズ")
    parser.add_argument("--exclude-stadiums", type=int,  nargs="+", default=[11], help="除外場ID")

    # 3連複パラメータ（T6-A最適デフォルト）
    parser.add_argument("--trio-prob", type=float, default=0.20, help="3連複: 的中確率閾値")
    parser.add_argument("--trio-ev",   type=float, default=4.0,  help="3連複: EV閾値")

    parser.add_argument("--output", type=str, default=None, help="結果CSV保存先（省略時は保存なし）")
    args = parser.parse_args()

    start_year, start_month = args.start
    end_year, end_month = args.end

    # ── モデルロード ────────────────────────────────────────────
    if args.model_path:
        model = joblib.load(args.model_path)
    else:
        existing = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
        if not existing:
            logger.error("No model found in %s. Run run_retrain.py first.", ARTIFACTS_DIR)
            sys.exit(1)
        logger.info("Using model: %s", existing[0])
        model = joblib.load(existing[0])

    all_tf_dfs: list[pd.DataFrame] = []
    all_trio_dfs: list[pd.DataFrame] = []

    for year, month in month_range(start_year, start_month, end_year, end_month):
        logger.info("Processing %d-%02d...", year, month)
        df_month = load_month_data(year, month)
        if df_month.empty:
            logger.warning("%d-%02d: no data, skip", year, month)
            continue

        odds_by_race: dict = {}
        trio_odds_by_race: dict = {}
        if args.real_odds:
            logger.info("Fetching trifecta odds for %d-%02d...", year, month)
            odds_by_race = load_or_download_month_odds(year, month, df_month)
            logger.info("Fetching trio odds for %d-%02d...", year, month)
            trio_odds_by_race = load_or_download_month_trio_odds(year, month, df_month)

        df_tf, df_trio = run_month(year, month, model, odds_by_race, trio_odds_by_race, args, df_month)

        if not df_tf.empty:
            df_tf["ym"] = f"{year}-{month:02d}"
            all_tf_dfs.append(df_tf)
        if not df_trio.empty:
            df_trio["ym"] = f"{year}-{month:02d}"
            all_trio_dfs.append(df_trio)

        # 月次表示
        print(f"\n  ── {year}-{month:02d} ──")
        print_recovery_analysis(df_tf, df_trio)

    # ── 全期間集計 ───────────────────────────────────────────────
    if len(all_tf_dfs) > 1 or len(all_trio_dfs) > 1:
        print(f"\n{'='*70}")
        print(f"  全期間合計 ({start_year}-{start_month:02d} 〜 {end_year}-{end_month:02d})")
        print(f"{'='*70}")
        all_tf  = pd.concat(all_tf_dfs,  ignore_index=True) if all_tf_dfs  else pd.DataFrame()
        all_trio= pd.concat(all_trio_dfs, ignore_index=True) if all_trio_dfs else pd.DataFrame()
        print_recovery_analysis(all_tf, all_trio)

    # CSV保存
    if args.output:
        all_tf  = pd.concat(all_tf_dfs,  ignore_index=True) if all_tf_dfs  else pd.DataFrame()
        all_trio= pd.concat(all_trio_dfs, ignore_index=True) if all_trio_dfs else pd.DataFrame()
        if not all_tf.empty:
            all_tf["bet_type"] = "trifecta"
        if not all_trio.empty:
            all_trio["bet_type"] = "trio"
        combined = pd.concat([all_tf, all_trio], ignore_index=True)
        combined.to_csv(args.output, index=False)
        logger.info("Saved to %s", args.output)


if __name__ == "__main__":
    main()
