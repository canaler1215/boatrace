"""
競艇予想モデル バックテスト実行スクリプト

使い方:
  # 2025年12月のバックテスト（既存モデルを使用）
  python run_backtest.py --year 2025 --month 12

  # モデルを再学習してからバックテスト（テスト期間を学習から除外）
  python run_backtest.py --year 2025 --month 12 --retrain

  # EV 閾値や賭け条件を変えて試す
  python run_backtest.py --year 2025 --month 12 --ev-threshold 1.5 --max-bets 3

  # 実オッズを使ってバックテスト（初回はダウンロード ~90 分、2 回目以降はキャッシュ）
  python run_backtest.py --year 2025 --month 12 --real-odds

  # 既存モデルファイルを直接指定
  python run_backtest.py --year 2025 --month 12 --model-path /path/to/model.pkl

オプション:
  --year              テスト年（必須）
  --month             テスト月（必須）
  --ev-threshold      賭け実行の EV 閾値（デフォルト: 1.2）
  --bet-amount        1 点賭け金 円（デフォルト: 100）
  --max-bets          1 レースあたり最大賭け点数（デフォルト: 5）
  --train-start-year  --retrain 時の学習開始年（デフォルト: 2023）
  --train-start-month --retrain 時の学習開始月 1-12（デフォルト: 1、年内を絞るときに使用）
  --retrain           テスト期間を除外してモデルを再学習する
  --model-path        既存モデルファイルのパス（指定時はそのまま使用）
  --real-odds         boatrace.jp の実オッズを使用（初回ダウンロード ~90 分、以降キャッシュ）
  --output            結果 CSV の保存先（デフォルト: artifacts/backtest_YYYYMM.csv）

例 (高速モード): --train-start-year 2025 --train-start-month 9 → 2025年9〜11月の3ヶ月で学習
"""
import argparse
import calendar
import logging
import shutil
import sys
import tempfile
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
from features.feature_builder import build_features_from_history
from model.evaluator import evaluate
from model.trainer import train
from backtest.engine import run_race

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def load_month_data(year: int, month: int) -> pd.DataFrame:
    """指定月の K ファイルをダウンロード・パースして DataFrame を返す。"""
    days_in_month = calendar.monthrange(year, month)[1]
    records: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_bt_"))
    save_dir = DATA_DIR

    logger.info("Downloading %d-%02d K-files (%d days)...", year, month, days_in_month)

    try:
        for day in range(1, days_in_month + 1):
            if date(year, month, day) > date.today():
                break
            try:
                lzh = download_day_data(year, month, day, dest_dir=save_dir)
                if lzh is None:
                    continue  # 開催なし
                extract_dir = tmpdir / lzh.stem
                files = extract_lzh(lzh, extract_dir)
                for f in files:
                    for rec in parse_result_file(f):
                        records.append(rec)
            except Exception as exc:
                logger.debug("Skip %d-%02d-%02d: %s", year, month, day, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    df = pd.DataFrame(records) if records else pd.DataFrame()
    logger.info("Loaded %d records for %d-%02d", len(df), year, month)
    return df


# ---------------------------------------------------------------------------
# モデル取得
# ---------------------------------------------------------------------------

def get_or_train_model(args: argparse.Namespace):
    """既存モデルをロード、または指定条件で再学習する。"""

    # 1. 明示的にパス指定
    if args.model_path:
        p = Path(args.model_path)
        if not p.exists():
            logger.error("Model not found: %s", p)
            sys.exit(1)
        logger.info("Loading model from %s", p)
        return joblib.load(p), p

    # 2. artifacts/ から最新モデルを探す（--retrain 未指定時）
    if not args.retrain:
        existing = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
        if existing:
            logger.info("Using existing model: %s", existing[0])
            return joblib.load(existing[0]), existing[0]
        logger.warning(
            "No model found in %s. "
            "Use --retrain to train a new model, or specify --model-path.",
            ARTIFACTS_DIR,
        )
        sys.exit(1)

    # 3. テスト期間を除外して新規学習
    # テスト月の前月末までを学習データとする
    if args.month > 1:
        train_end_year, train_end_month = args.year, args.month - 1
    else:
        train_end_year, train_end_month = args.year - 1, 12

    test_start_iso  = f"{args.year}-{args.month:02d}-01"
    train_start_iso = f"{args.train_start_year}-{args.train_start_month:02d}-01"

    logger.info(
        "Training model: %d-%02d to %d-%02d (test period %d-%02d excluded)...",
        args.train_start_year,
        args.train_start_month,
        train_end_year,
        train_end_month,
        args.year,
        args.month,
    )

    df_train = load_history_range(
        start_year=args.train_start_year,
        end_year=train_end_year,
        start_month=args.train_start_month,
        end_month=train_end_month,
    )

    if df_train.empty or len(df_train) < 1000:
        logger.error("Training data too small (%d rows). Exiting.", len(df_train))
        sys.exit(1)

    logger.info("Training data: %d records", len(df_train))
    X, y = build_features_from_history(df_train)

    version = f"{train_end_year}{train_end_month:02d}_from{args.train_start_year}{args.train_start_month:02d}"
    model_path = train(X, y, version)

    # 評価（バリデーション分割）
    from sklearn.model_selection import train_test_split

    _, X_val, _, y_val = train_test_split(X, y, test_size=0.1, random_state=42, stratify=y)
    model = joblib.load(model_path)
    metrics = evaluate(y_val.values, model.predict(X_val))
    logger.info(
        "Train-time validation: RPS=%.4f  top1_acc=%.4f",
        metrics["rps"],
        metrics["top1_accuracy"],
    )

    return model, model_path


# ---------------------------------------------------------------------------
# サマリー出力
# ---------------------------------------------------------------------------

def print_summary(results_df: pd.DataFrame, ev_threshold: float, bet_amount: int) -> None:
    """バックテスト結果のサマリーをコンソールに出力する。"""
    total_races = len(results_df)
    races_with_bets = int((results_df["bets_placed"] > 0).sum())
    total_bets = int(results_df["bets_placed"].sum())
    total_wagered = float(results_df["amount_wagered"].sum())
    total_payout = float(results_df["payout_received"].sum())
    total_profit = float(results_df["profit"].sum())
    wins = int(results_df["matched"].sum())

    roi = (total_payout / total_wagered - 1) * 100 if total_wagered > 0 else 0.0
    win_rate = wins / total_bets * 100 if total_bets > 0 else 0.0
    avg_odds = (
        float(results_df[results_df["matched"]]["matched_odds"].mean())
        if wins > 0
        else 0.0
    )

    period_from = results_df["race_date"].min()
    period_to = results_df["race_date"].max()

    print()
    print("=" * 62)
    print("  バックテスト結果サマリー")
    print("=" * 62)
    print(f"  対象期間    : {period_from} 〜 {period_to}")
    print(f"  EV 閾値     : {ev_threshold}")
    print(f"  賭け金/点   : ¥{bet_amount:,}")
    print(f"  総レース数  : {total_races:,} レース")
    print(f"  賭け実行    : {races_with_bets:,} レース / {total_bets:,} 点")
    print("-" * 62)
    print(f"  投資合計    : ¥{total_wagered:>12,.0f}")
    print(f"  払戻合計    : ¥{total_payout:>12,.0f}")
    print(f"  損益        : ¥{total_profit:>+12,.0f}")
    print(f"  ROI         : {roi:>+.1f}%")
    print("-" * 62)
    print(f"  的中        : {wins} / {total_bets} 点  ({win_rate:.2f}%)")
    print(f"  平均配当    : {avg_odds:.1f}x  (的中時の合成オッズ)")

    # EV バケット別 ROI
    bet_df = results_df[results_df["bets_placed"] > 0].copy()
    if len(bet_df) > 0:
        bins = [ev_threshold, 1.5, 2.0, 3.0, float("inf")]
        labels = [
            f"{ev_threshold:.1f}–1.5",
            "1.5–2.0",
            "2.0–3.0",
            "3.0+",
        ]
        bet_df["ev_bucket"] = pd.cut(
            bet_df["top_ev"], bins=bins, labels=labels, right=False
        )
        print()
        print("  [EV バケット別 ROI (トップ EV のバケット)]")
        print(f"  {'EV':>10}  {'レース':>6}  {'投資':>10}  {'払戻':>10}  {'ROI':>7}  {'的中'}")
        print("  " + "-" * 56)
        for bucket, grp in bet_df.groupby("ev_bucket", observed=True):
            g_wagered = float(grp["amount_wagered"].sum())
            g_payout = float(grp["payout_received"].sum())
            g_roi = (g_payout / g_wagered - 1) * 100 if g_wagered > 0 else 0.0
            g_wins = int(grp["matched"].sum())
            print(
                f"  {str(bucket):>10}  {len(grp):>6,}  "
                f"¥{g_wagered:>9,.0f}  ¥{g_payout:>9,.0f}  "
                f"{g_roi:>+6.1f}%  {g_wins}"
            )

    # オッズソース内訳
    if "odds_source" in results_df.columns:
        real_count = int((results_df["odds_source"] == "real").sum())
        syn_count  = int((results_df["odds_source"] == "synthetic").sum())
        print()
        print(f"  [オッズソース]  実オッズ: {real_count:,} レース  合成オッズ: {syn_count:,} レース")
        if syn_count > 0:
            print("  ※ 実オッズ未取得レースは合成オッズ（艇番ベース）で代替")

    print()
    if "odds_source" not in results_df.columns or (results_df["odds_source"] == "synthetic").all():
        print("  ※ 合成オッズを使用（艇番ベース市場モデル、払戻率 75%）")
    print("  ※ K ファイルのみ使用: 勝率・モーター成績は 0 で代替")
    print("  ※ 実際の配当とは異なります")
    print("=" * 62)
    print()


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="競艇予想モデル バックテスト",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--year",  type=int, required=True, help="テスト年")
    parser.add_argument("--month", type=int, required=True, help="テスト月（1–12）")
    parser.add_argument("--ev-threshold",     type=float, default=1.2,  help="賭け実行の EV 閾値")
    parser.add_argument("--bet-amount",       type=int,   default=100,  help="1 点賭け金（円）")
    parser.add_argument("--max-bets",         type=int,   default=5,    help="1 レースあたり最大賭け点数")
    parser.add_argument("--train-start-year",  type=int,   default=2023, help="--retrain 時の学習開始年")
    parser.add_argument("--train-start-month", type=int,   default=1,    help="--retrain 時の学習開始月（1-12）")
    parser.add_argument("--retrain",           action="store_true",      help="テスト期間を除外してモデルを再学習")
    parser.add_argument("--model-path",       type=str,   default=None, help="既存モデルファイルのパス")
    parser.add_argument("--real-odds",        action="store_true",      help="boatrace.jp の実オッズを使用（初回 ~90 分）")
    parser.add_argument("--output",           type=str,   default=None, help="結果 CSV の保存先")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    # ── 1. モデル取得 ────────────────────────────────────
    model, model_path = get_or_train_model(args)
    logger.info("Model: %s", model_path)

    # ── 2. テストデータ取得 ──────────────────────────────
    df_test = load_month_data(args.year, args.month)
    if df_test.empty:
        logger.error("No data found for %d-%02d.", args.year, args.month)
        sys.exit(1)

    # ── 3. 実オッズ取得（--real-odds 指定時）────────────────
    odds_by_race: dict[str, dict[str, float]] = {}
    if args.real_odds:
        logger.info("Fetching real odds for %d-%02d...", args.year, args.month)
        odds_by_race = load_or_download_month_odds(args.year, args.month, df_test)
        logger.info("Real odds loaded for %d races", len(odds_by_race))

    # ── 4. レース別バックテスト実行 ──────────────────────
    race_groups = list(df_test.groupby("race_id"))
    logger.info("Running backtest on %d races...", len(race_groups))

    results: list[dict] = []
    skipped = 0
    for race_id, race_df in race_groups:
        result = run_race(
            race_df=race_df,
            model=model,
            ev_threshold=args.ev_threshold,
            bet_amount=args.bet_amount,
            max_bets_per_race=args.max_bets,
            race_odds=odds_by_race.get(str(race_id)),
        )
        if result is None:
            skipped += 1
        else:
            results.append(result)

    logger.info("Done: %d races processed, %d skipped", len(results), skipped)

    if not results:
        logger.error("No results generated. Check data or model.")
        sys.exit(1)

    results_df = pd.DataFrame(results).sort_values(["race_date", "race_id"])

    # ── 5. CSV 保存 ──────────────────────────────────────
    output_path = args.output or str(
        ARTIFACTS_DIR / f"backtest_{args.year}{args.month:02d}.csv"
    )
    results_df.to_csv(output_path, index=False)
    logger.info("Results saved to %s", output_path)

    # ── 6. サマリー表示 ──────────────────────────────────
    print_summary(results_df, args.ev_threshold, args.bet_amount)


if __name__ == "__main__":
    main()
