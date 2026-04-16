"""
Walk-Forward バックテスト（複数月連続検証）

各テスト月の直前までのデータでモデルを再学習し、テスト月で検証する。
これを複数月繰り返して、時系列リークのない累積 ROI を計測する。

使い方:
  # 2025年10月〜12月の Walk-Forward（各月で再学習）
  python run_walkforward.py --start 2025-10 --end 2025-12 --retrain --real-odds

  # 再学習なし（固定モデルで複数月検証）
  python run_walkforward.py --start 2025-10 --end 2025-12 --real-odds

  # 合成オッズで高速確認
  python run_walkforward.py --start 2025-10 --end 2025-12

オプション:
  --start             テスト開始月 (YYYY-MM 形式、必須)
  --end               テスト終了月 (YYYY-MM 形式、必須)
  --prob-threshold    的中確率閾値（デフォルト: 0.05）
  --ev-threshold      期待値閾値（デフォルト: 1.2）
  --bet-amount        1 点賭け金 円（デフォルト: 100）
  --max-bets          1 レースあたり最大賭け点数（デフォルト: 5）
  --retrain           各テスト月の直前データでモデルを再学習（Walk-Forward）
  --train-start-year  --retrain 時の学習開始年（デフォルト: 2023）
  --train-start-month --retrain 時の学習開始月（デフォルト: 1）
  --real-odds         実オッズを使用
  --output            結果 CSV の保存先
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
    load_history_range,
    parse_result_file,
)
from collector.odds_downloader import load_or_download_month_odds
from collector.program_downloader import (
    load_program_month,
    load_program_range,
    merge_program_data,
)
from features.feature_builder import build_features_from_history
from model.evaluator import evaluate
from model.trainer import train
from backtest.engine import run_backtest_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def parse_ym(s: str) -> tuple[int, int]:
    """'YYYY-MM' → (year, month)"""
    try:
        year, month = s.split("-")
        return int(year), int(month)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid month format: '{s}'. Use YYYY-MM.")


def month_range(start_year: int, start_month: int, end_year: int, end_month: int):
    """(start_year, start_month) から (end_year, end_month) まで月を列挙するジェネレータ。"""
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def prev_month(year: int, month: int) -> tuple[int, int]:
    if month > 1:
        return year, month - 1
    return year - 1, 12


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def load_month_data(year: int, month: int, max_workers: int = 8) -> pd.DataFrame:
    """1 か月分の K ファイル + B ファイルをダウンロード・マージして返す。"""
    days_in_month = calendar.monthrange(year, month)[1]
    save_dir = DATA_DIR
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_wf_"))

    days = [
        d for d in range(1, days_in_month + 1)
        if date(year, month, d) <= date.today()
    ]

    def _fetch_day(day: int) -> list[dict]:
        try:
            lzh = download_day_data(year, month, day, dest_dir=save_dir)
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


# ---------------------------------------------------------------------------
# モデル取得 / 再学習
# ---------------------------------------------------------------------------

def get_model_for_month(
    test_year: int,
    test_month: int,
    retrain: bool,
    train_start_year: int,
    train_start_month: int,
    cached_model=None,
):
    """
    テスト月用のモデルを返す。

    retrain=True  : テスト月直前データで再学習したモデルを返す
    retrain=False : cached_model があればそのまま返す。なければ artifacts/ の最新を使う
    """
    if not retrain:
        if cached_model is not None:
            return cached_model
        existing = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
        if not existing:
            logger.error("No model found in %s. Use --retrain or run_retrain.py first.", ARTIFACTS_DIR)
            sys.exit(1)
        logger.info("Using existing model: %s", existing[0])
        return joblib.load(existing[0])

    # テスト月の前月末までを学習データとする
    train_end_year, train_end_month = prev_month(test_year, test_month)

    logger.info(
        "Training model for %d-%02d: train %d-%02d → %d-%02d",
        test_year, test_month,
        train_start_year, train_start_month,
        train_end_year, train_end_month,
    )

    df_train = load_history_range(
        start_year=train_start_year,
        end_year=train_end_year,
        start_month=train_start_month,
        end_month=train_end_month,
    )
    if df_train.empty or len(df_train) < 1000:
        logger.error("Training data too small (%d rows).", len(df_train))
        sys.exit(1)

    df_prog = load_program_range(
        start_year=train_start_year,
        end_year=train_end_year,
        start_month=train_start_month,
        end_month=train_end_month,
    )
    df_train = merge_program_data(df_train, df_prog)

    X, y = build_features_from_history(df_train)
    version = (
        f"{train_end_year}{train_end_month:02d}"
        f"_from{train_start_year}{train_start_month:02d}"
        f"_wf"
    )
    model_path = train(X, y, version)
    return joblib.load(model_path)


# ---------------------------------------------------------------------------
# サマリー出力
# ---------------------------------------------------------------------------

def print_monthly_table(monthly_rows: list[dict]) -> None:
    """月別サマリーテーブルを出力する。"""
    print()
    print("  [月別サマリー]")
    print(f"  {'月':>7}  {'賭け点':>6}  {'投資':>10}  {'払戻':>10}  {'ROI':>7}  {'的中'}")
    print("  " + "-" * 58)
    for row in monthly_rows:
        roi = (row["payout"] / row["wagered"] - 1) * 100 if row["wagered"] > 0 else float("nan")
        print(
            f"  {row['month']:>7}  {row['n_bets']:>6,}  "
            f"¥{row['wagered']:>9,.0f}  ¥{row['payout']:>9,.0f}  "
            f"{roi:>+6.1f}%  {row['wins']}"
        )


def print_summary(
    all_results: pd.DataFrame,
    monthly_rows: list[dict],
    prob_threshold: float,
    ev_threshold: float,
    bet_amount: int,
) -> None:
    total_wagered = float(all_results["amount_wagered"].sum())
    total_payout  = float(all_results["payout_received"].sum())
    total_profit  = float(all_results["profit"].sum())
    total_bets    = int(all_results["bets_placed"].sum())
    total_wins    = int(all_results["matched"].sum())
    roi = (total_payout / total_wagered - 1) * 100 if total_wagered > 0 else 0.0
    win_rate = total_wins / total_bets * 100 if total_bets > 0 else 0.0
    avg_odds = (
        float(all_results[all_results["matched"]]["matched_odds"].mean())
        if total_wins > 0 else 0.0
    )
    period_from = all_results["race_date"].min()
    period_to   = all_results["race_date"].max()

    print()
    print("=" * 62)
    print("  Walk-Forward バックテスト結果サマリー")
    print("=" * 62)
    print(f"  対象期間    : {period_from} 〜 {period_to}")
    print(f"  的中確率閾値: {prob_threshold * 100:.1f}%")
    print(f"  EV閾値      : {ev_threshold:.2f}")
    print(f"  賭け金/点   : ¥{bet_amount:,}")
    print(f"  総レース数  : {len(all_results):,} レース")
    print("-" * 62)
    print(f"  投資合計    : ¥{total_wagered:>12,.0f}")
    print(f"  払戻合計    : ¥{total_payout:>12,.0f}")
    print(f"  損益        : ¥{total_profit:>+12,.0f}")
    print(f"  ROI         : {roi:>+.1f}%")
    print("-" * 62)
    print(f"  的中        : {total_wins} / {total_bets} 点  ({win_rate:.2f}%)")
    print(f"  平均配当    : {avg_odds:.1f}x")

    print_monthly_table(monthly_rows)

    if "odds_source" in all_results.columns:
        real_count = int((all_results["odds_source"] == "real").sum())
        syn_count  = int((all_results["odds_source"] == "synthetic").sum())
        print()
        print(f"  [オッズソース]  実オッズ: {real_count:,} レース  合成オッズ: {syn_count:,} レース")

    print("=" * 62)
    print()


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk-Forward バックテスト（複数月連続検証）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start",  type=str, required=True, help="テスト開始月 YYYY-MM")
    parser.add_argument("--end",    type=str, required=True, help="テスト終了月 YYYY-MM")
    parser.add_argument("--prob-threshold",    type=float, default=0.05, help="的中確率閾値")
    parser.add_argument("--ev-threshold",      type=float, default=1.2,  help="期待値閾値（0.0 で無効）")
    parser.add_argument("--bet-amount",        type=int,   default=100,  help="1 点賭け金（円）")
    parser.add_argument("--max-bets",          type=int,   default=5,    help="1 レース最大賭け点数")
    parser.add_argument("--retrain",           action="store_true",      help="各月で再学習（Walk-Forward）")
    parser.add_argument("--train-start-year",  type=int,   default=2023, help="学習開始年")
    parser.add_argument("--train-start-month", type=int,   default=1,    help="学習開始月")
    parser.add_argument("--real-odds",         action="store_true",      help="実オッズを使用")
    parser.add_argument("--exclude-courses",   type=int,   nargs="+",   help="除外する1着艇番（例: 2 4 5）")
    parser.add_argument("--min-odds",          type=float, default=None, help="購入するオッズの下限（例: 100.0 → 100倍未満は除外）")
    parser.add_argument("--exclude-stadiums",  type=int,   nargs="+",   help="除外する場ID（例: 11 → びわこ）")
    parser.add_argument("--output",            type=str,   default=None, help="結果 CSV の保存先")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    start_year,  start_month  = parse_ym(args.start)
    end_year,    end_month    = parse_ym(args.end)

    if (start_year, start_month) > (end_year, end_month):
        logger.error("--start は --end 以前の月を指定してください。")
        sys.exit(1)

    months = list(month_range(start_year, start_month, end_year, end_month))
    logger.info("Walk-Forward: %d 月分を検証します (%s → %s)", len(months), args.start, args.end)

    if not args.real_odds:
        logger.warning(
            "--real-odds が指定されていません。合成オッズを使用します。"
            "ROI の絶対値は実際の収益性を反映しません。"
        )

    all_results_list: list[pd.DataFrame] = []
    monthly_rows: list[dict] = []
    cached_model = None  # retrain=False 時にモデルをキャッシュ

    for test_year, test_month in months:
        logger.info("── %d-%02d のバックテスト開始 ──", test_year, test_month)

        # 1. モデル取得
        model = get_model_for_month(
            test_year, test_month,
            retrain=args.retrain,
            train_start_year=args.train_start_year,
            train_start_month=args.train_start_month,
            cached_model=cached_model,
        )
        if not args.retrain:
            cached_model = model  # 同じモデルを再利用

        # 2. テストデータ取得
        df_test = load_month_data(test_year, test_month)
        if df_test.empty:
            logger.warning("%d-%02d: データなし、スキップ", test_year, test_month)
            continue

        # 3. 実オッズ取得
        odds_by_race: dict[str, dict[str, float]] = {}
        if args.real_odds:
            odds_by_race = load_or_download_month_odds(test_year, test_month, df_test)
            logger.info("実オッズ: %d レース分取得", len(odds_by_race))

        # 4. バックテスト
        n_races = df_test["race_id"].nunique()
        logger.info("%d-%02d: %d レースをバックテスト中...", test_year, test_month, n_races)
        results, skipped = run_backtest_batch(
            df_test=df_test,
            model=model,
            odds_by_race=odds_by_race,
            prob_threshold=args.prob_threshold,
            bet_amount=args.bet_amount,
            max_bets_per_race=args.max_bets,
            ev_threshold=args.ev_threshold,
            exclude_courses=args.exclude_courses,
            min_odds=args.min_odds,
            exclude_stadiums=args.exclude_stadiums,
        )
        logger.info("%d-%02d: 完了 %d レース、スキップ %d", test_year, test_month, len(results), skipped)

        if not results:
            continue

        df_month = pd.DataFrame(results)
        all_results_list.append(df_month)

        # 月別集計
        wagered = float(df_month["amount_wagered"].sum())
        payout  = float(df_month["payout_received"].sum())
        n_bets  = int(df_month["bets_placed"].sum())
        wins    = int(df_month["matched"].sum())
        monthly_rows.append({
            "month":   f"{test_year}-{test_month:02d}",
            "wagered": wagered,
            "payout":  payout,
            "n_bets":  n_bets,
            "wins":    wins,
        })

    if not all_results_list:
        logger.error("全月でデータが取得できませんでした。")
        sys.exit(1)

    all_results = pd.concat(all_results_list, ignore_index=True).sort_values(["race_date", "race_id"])

    # 5. CSV 保存
    label_start = f"{start_year}{start_month:02d}"
    label_end   = f"{end_year}{end_month:02d}"
    output_path = args.output or str(ARTIFACTS_DIR / f"walkforward_{label_start}-{label_end}.csv")
    all_results.to_csv(output_path, index=False)
    logger.info("結果を保存: %s", output_path)

    # 6. サマリー表示
    print_summary(all_results, monthly_rows, args.prob_threshold, args.ev_threshold, args.bet_amount)


if __name__ == "__main__":
    main()
