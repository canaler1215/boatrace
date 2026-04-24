"""
競艇予想モデル バックテスト実行スクリプト

使い方:
  # 2025年12月のバックテスト（既存モデルを使用）
  python run_backtest.py --year 2025 --month 12

  # モデルを再学習してからバックテスト（テスト期間を学習から除外）
  python run_backtest.py --year 2025 --month 12 --retrain

  # 的中確率閾値や賭け条件を変えて試す
  python run_backtest.py --year 2025 --month 12 --prob-threshold 0.10 --max-bets 3

  # 実オッズを使ってバックテスト（初回はダウンロード ~90 分、2 回目以降はキャッシュ）
  python run_backtest.py --year 2025 --month 12 --real-odds

  # 既存モデルファイルを直接指定
  python run_backtest.py --year 2025 --month 12 --model-path /path/to/model.pkl

オプション:
  --year              テスト年（必須）
  --month             テスト月（必須）
  --prob-threshold    賭け実行の的中確率閾値（デフォルト: 0.05 = 5%）
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.history_downloader import (
    DATA_DIR,
    download_day_data,
    extract_lzh,
    load_history_range,
    parse_result_file,
)
from collector.odds_downloader import load_or_download_month_odds, load_or_download_month_trio_odds
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
# データ取得
# ---------------------------------------------------------------------------

def load_month_data(year: int, month: int, max_workers: int = 8) -> pd.DataFrame:
    """
    指定月の K ファイル（競走成績）と B ファイル（出走表）を並列ダウンロード・
    パースし、race_id + boat_no でマージして DataFrame を返す。

    B ファイルから以下の特徴量を補完する:
      racer_win_rate, motor_win_rate, boat_win_rate, racer_grade
    """
    days_in_month = calendar.monthrange(year, month)[1]
    save_dir = DATA_DIR
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_bt_"))

    days = [
        d for d in range(1, days_in_month + 1)
        if date(year, month, d) <= date.today()
    ]
    logger.info(
        "Downloading %d-%02d K-files (%d days, %d workers)...",
        year, month, len(days), max_workers,
    )

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
    logger.info("K-file: %d records for %d-%02d", len(df_k), year, month)

    # B ファイル（出走表）から特徴量を補完
    logger.info("Downloading %d-%02d B-files (program data)...", year, month)
    df_b = load_program_month(year, month, max_workers=max_workers)
    df = merge_program_data(df_k, df_b)

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

    # B ファイル（出走表）から特徴量を補完（学習データにも適用）
    logger.info("Loading B-file program data for training range...")
    df_prog_train = load_program_range(
        start_year=args.train_start_year,
        end_year=train_end_year,
        start_month=args.train_start_month,
        end_month=train_end_month,
    )
    df_train = merge_program_data(df_train, df_prog_train)

    logger.info("Training data: %d records", len(df_train))
    X, y = build_features_from_history(df_train)

    version = f"{train_end_year}{train_end_month:02d}_from{args.train_start_year}{args.train_start_month:02d}"
    model_path = train(X, y, version)

    # 評価（時系列 split で val データを取得）
    n = len(X)
    n_val = max(int(n * 0.1), 1)
    X_val = X.iloc[-n_val:]
    y_val = y.iloc[-n_val:]

    model_pkg = joblib.load(model_path)
    model = model_pkg  # run_backtest_batch に渡す（predict_win_prob が dict 対応）
    booster = model_pkg["booster"] if isinstance(model_pkg, dict) else model_pkg
    metrics = evaluate(y_val.values, booster.predict(X_val))
    logger.info(
        "Train-time validation: RPS=%.4f  top1_acc=%.4f",
        metrics["rps"],
        metrics["top1_accuracy"],
    )

    return model, model_path


# ---------------------------------------------------------------------------
# サマリー出力
# ---------------------------------------------------------------------------

def print_summary(results_df: pd.DataFrame, prob_threshold: float, bet_amount: int, ev_threshold: float = 1.2) -> None:
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
    print(f"  的中確率閾値: {prob_threshold * 100:.1f}%")
    print(f"  EV閾値      : {ev_threshold:.2f}")
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

    # 的中確率バケット別 ROI
    bet_df = results_df[results_df["bets_placed"] > 0].copy()
    if len(bet_df) > 0:
        bins = [prob_threshold, 0.10, 0.20, 0.40, float("inf")]
        # 閾値が 0.10 以上の場合はバケットを調整
        if prob_threshold >= 0.10:
            bins = [prob_threshold, 0.20, 0.40, float("inf")]
            labels = [
                f"{prob_threshold * 100:.0f}%–20%",
                "20%–40%",
                "40%+",
            ]
        else:
            labels = [
                f"{prob_threshold * 100:.0f}%–10%",
                "10%–20%",
                "20%–40%",
                "40%+",
            ]
        bet_df["prob_bucket"] = pd.cut(
            bet_df["top_prob"], bins=bins, labels=labels, right=False
        )
        print()
        print("  [的中確率バケット別 ROI (トップ確率のバケット)]")
        print(f"  {'確率':>10}  {'レース':>6}  {'投資':>10}  {'払戻':>10}  {'ROI':>7}  {'的中'}")
        print("  " + "-" * 56)
        for bucket, grp in bet_df.groupby("prob_bucket", observed=True):
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
# 戦略 YAML 読み込み
# ---------------------------------------------------------------------------

def _apply_strategy_config(args: argparse.Namespace, config_path: str) -> None:
    """YAML 戦略ファイルを読み込み、args の対応フィールドを上書きする。

    注意: 現実装では YAML 側の値が優先される（CLI で明示指定した値も上書きされる）。
    CLI と --strategy-config を同時に使わないこと。GitHub Actions の claude_fix.yml は
    --strategy-config のみを使い、閾値は YAML 経由で渡す運用（2026-04-24 C5 対応）。
    """
    p = Path(config_path)
    if not p.exists():
        logger.error("Strategy config not found: %s", p)
        sys.exit(1)

    with p.open(encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f)

    filters = cfg.get("filters", {})
    staking = cfg.get("staking", {})
    training = cfg.get("training", {})

    _set_if_default(args, "prob_threshold",    filters.get("prob_threshold"))
    _set_if_default(args, "ev_threshold",      filters.get("ev_threshold"))
    _set_if_default(args, "exclude_courses",   filters.get("exclude_courses"))
    _set_if_default(args, "min_odds",          filters.get("min_odds"))
    _set_if_default(args, "exclude_stadiums",  filters.get("exclude_stadiums"))
    _set_if_default(args, "bet_amount",        staking.get("bet_amount"))
    _set_if_default(args, "max_bets",          staking.get("max_bets"))
    _set_if_default(args, "kelly_fraction",    staking.get("kelly_fraction"))
    _set_if_default(args, "kelly_bankroll",    staking.get("kelly_bankroll"))
    _set_if_default(args, "bet_type",          cfg.get("bet_type"))
    _set_if_default(args, "train_start_year",  training.get("train_start_year"))
    _set_if_default(args, "train_start_month", training.get("train_start_month"))

    logger.info("Strategy config loaded: %s (version=%s)", p.name, cfg.get("version", "?"))


def _set_if_default(args: argparse.Namespace, key: str, value: Any) -> None:
    """YAML の値が None でなければ args を上書きする。

    歴史的な関数名だが実態は「YAML 優先の無条件上書き」。
    CLI デフォルト判定は行っていない（argparse のデフォルトと明示指定の判別には
    sentinel が必要なため、現状は簡素化している）。
    """
    if value is None:
        return
    setattr(args, key, value)


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
    parser.add_argument("--prob-threshold",    type=float, default=0.05, help="賭け実行の的中確率閾値（例: 0.05 = 5%%）")
    parser.add_argument("--ev-threshold",     type=float, default=1.2,  help="賭け実行の期待値閾値（例: 1.2）。0.0 で無効")
    parser.add_argument("--bet-amount",       type=int,   default=100,  help="1 点賭け金（円）")
    parser.add_argument("--max-bets",         type=int,   default=5,    help="1 レースあたり最大賭け点数")
    parser.add_argument("--train-start-year",  type=int,   default=2023, help="--retrain 時の学習開始年")
    parser.add_argument("--train-start-month", type=int,   default=1,    help="--retrain 時の学習開始月（1-12）")
    parser.add_argument("--retrain",           action="store_true",      help="テスト期間を除外してモデルを再学習")
    parser.add_argument("--model-path",       type=str,   default=None, help="既存モデルファイルのパス")
    parser.add_argument("--real-odds",        action="store_true",      help="boatrace.jp の実オッズを使用（初回 ~90 分）")
    parser.add_argument("--kelly-fraction",   type=float, default=0.0,  help="Kelly 分率（0.0=固定ベット, 0.25=1/4Kelly 推奨）")
    parser.add_argument("--kelly-bankroll",   type=float, default=100_000.0, help="Kelly 計算用の資金額（円）")
    parser.add_argument("--exclude-courses",  type=int,   nargs="+",    help="除外する1着艇番（例: 2 4 5）")
    parser.add_argument("--min-odds",         type=float, default=None, help="購入するオッズの下限（例: 100.0 → 100倍未満は除外）")
    parser.add_argument("--exclude-stadiums", type=int,   nargs="+",    help="除外する場ID（例: 11 → びわこ）")
    parser.add_argument("--bet-type",         type=str,   default="trifecta", choices=["trifecta", "trio", "both"], help="賭式: trifecta=3連単, trio=3連複, both=両方")
    parser.add_argument("--output",           type=str,   default=None, help="結果 CSV の保存先")
    parser.add_argument("--strategy-config",  type=str,   default=None, help="戦略パラメータ YAML ファイル（ml/configs/strategy_*.yaml）")
    args = parser.parse_args()

    # ── YAML 戦略ファイルが指定されていれば CLI 引数のデフォルトを上書き ──
    if args.strategy_config:
        _apply_strategy_config(args, args.strategy_config)

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    # ── 0. --real-odds なし時の警告 ────────────────────────
    if not args.real_odds:
        logger.warning(
            "--real-odds が指定されていません。合成オッズ（艇番ベース理論値）を使用します。\n"
            "  合成オッズは実際の市場オッズと大きく異なるため、EV・ROI の絶対値は\n"
            "  本番の収益性を正確に反映しません。\n"
            "  本番と同等の評価をするには --real-odds を指定してください（初回 ~90 分）。"
        )

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
    trio_odds_by_race: dict[str, dict[str, float]] = {}
    if args.real_odds:
        if args.bet_type in ("trifecta", "both"):
            logger.info("Fetching real trifecta odds for %d-%02d...", args.year, args.month)
            odds_by_race = load_or_download_month_odds(args.year, args.month, df_test)
            logger.info("Real trifecta odds loaded for %d races", len(odds_by_race))
        if args.bet_type in ("trio", "both"):
            logger.info("Fetching real trio odds for %d-%02d...", args.year, args.month)
            trio_odds_by_race = load_or_download_month_trio_odds(args.year, args.month, df_test)
            logger.info("Real trio odds loaded for %d races", len(trio_odds_by_race))

    # ── 4. バックテスト実行（全レース一括バッチ処理）────────────
    n_races = df_test["race_id"].nunique()
    logger.info("Running batch backtest on %d races...", n_races)

    if args.kelly_fraction > 0:
        logger.info(
            "Kelly criterion enabled: fraction=%.2f, bankroll=¥%,.0f",
            args.kelly_fraction, args.kelly_bankroll,
        )

    bet_types = ["trifecta", "trio"] if args.bet_type == "both" else [args.bet_type]
    all_results_dfs: list[pd.DataFrame] = []

    for bt in bet_types:
        race_odds = trio_odds_by_race if bt == "trio" else odds_by_race
        results, skipped = run_backtest_batch(
            df_test=df_test,
            model=model,
            odds_by_race=race_odds,
            prob_threshold=args.prob_threshold,
            bet_amount=args.bet_amount,
            max_bets_per_race=args.max_bets,
            ev_threshold=args.ev_threshold,
            kelly_fraction=args.kelly_fraction,
            kelly_bankroll=args.kelly_bankroll,
            exclude_courses=args.exclude_courses,
            min_odds=args.min_odds,
            exclude_stadiums=args.exclude_stadiums,
            bet_type=bt,
        )
        logger.info("[%s] Done: %d races processed, %d skipped", bt, len(results), skipped)

        if not results:
            logger.warning("[%s] No results generated.", bt)
            continue

        df_bt = pd.DataFrame(results).sort_values(["race_date", "race_id"])
        all_results_dfs.append(df_bt)

        # サマリー表示
        if args.bet_type == "both":
            print(f"\n{'='*62}")
            print(f"  賭式: {'3連単 (trifecta)' if bt == 'trifecta' else '3連複 (trio)'}")
        print_summary(df_bt, args.prob_threshold, args.bet_amount, args.ev_threshold)
        if args.kelly_fraction > 0:
            print(f"  [Kelly設定] 分率={args.kelly_fraction:.2f}  資金=¥{args.kelly_bankroll:,.0f}")
            print()

    if not all_results_dfs:
        logger.error("No results generated. Check data or model.")
        sys.exit(1)

    results_df = pd.concat(all_results_dfs, ignore_index=True).sort_values(["race_date", "race_id"])

    # ── 5. CSV 保存 ──────────────────────────────────────
    output_path = args.output or str(
        ARTIFACTS_DIR / f"backtest_{args.year}{args.month:02d}.csv"
    )
    results_df.to_csv(output_path, index=False)
    logger.info("Results saved to %s", output_path)


if __name__ == "__main__":
    main()
