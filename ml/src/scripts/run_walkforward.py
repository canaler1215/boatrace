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
import math
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
# sample_weight 生成（MODEL_LOOP タスク 2）
# ---------------------------------------------------------------------------

def build_sample_weight(
    race_dates: pd.Series,
    ref_date: pd.Timestamp,
    config: dict | None,
) -> np.ndarray | None:
    """
    trial config の sample_weight セクションから学習サンプル重みを生成する。

    Parameters
    ----------
    race_dates : pd.Series (dtype=datetime64[ns])
        X と同じ行順・長さの race_date 列。
    ref_date : pd.Timestamp
        基準日（通常は学習期間の末日 = テスト月の前月末日）。
        「直近 N ヶ月」は ref_date 起点で数える。
    config : dict | None
        {"mode": "recency", "recency_months": 12, "recency_weight": 3.0} など。
        None / {"mode": None} なら重み無し（None を返す）。

    Returns
    -------
    np.ndarray | None
        shape = (len(race_dates),) の重み配列。None なら均等重み（trainer 側でデフォルト扱い）。
    """
    if not config:
        return None
    mode = config.get("mode")
    if not mode:
        return None

    dates = pd.to_datetime(race_dates).to_numpy()
    n = len(dates)

    if mode == "recency":
        months = int(config.get("recency_months", 12))
        weight = float(config.get("recency_weight", 3.0))
        # ref_date から months ヶ月前以降を weight 倍、それ以前は 1.0
        cutoff = pd.Timestamp(ref_date) - pd.DateOffset(months=months)
        cutoff_np = np.datetime64(cutoff)
        w = np.ones(n, dtype=np.float64)
        w[dates >= cutoff_np] = weight
        return w

    if mode == "exp_decay":
        # weight = exp(-k * age_months)、age_months = (ref_date - race_date).days / 30
        k = float(config.get("decay_k", 0.1))
        ref_np = np.datetime64(pd.Timestamp(ref_date))
        age_days = (ref_np - dates) / np.timedelta64(1, "D")
        age_months = age_days.astype(np.float64) / 30.0
        # age < 0（ref_date より未来のデータ、基本起きない）は age=0 扱い
        age_months = np.clip(age_months, 0.0, None)
        return np.exp(-k * age_months)

    raise ValueError(f"Unknown sample_weight mode: {mode!r}")


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
    *,
    trial_config: dict | None = None,
    return_metrics: bool = False,
):
    """
    テスト月用のモデルを返す。

    retrain=True  : テスト月直前データで再学習したモデルを返す
    retrain=False : cached_model があればそのまま返す。なければ artifacts/ の最新を使う

    Parameters
    ----------
    trial_config : dict | None
        MODEL_LOOP の trial YAML のうち学習側のサブ dict。想定キー:
          - training.sample_weight : {"mode": ..., ...}
          - training.num_boost_round : int
          - training.early_stopping_rounds : int
          - lgb_params : dict
        retrain=False の場合は無視される。
    return_metrics : bool
        True かつ retrain=True の場合、(model_obj, metrics_dict) を返す。
        metrics_dict は trainer.train() の戻り値 dict。
        retrain=False または False の場合は model_obj のみ（後方互換）。
    """
    if not retrain:
        if cached_model is not None:
            return (cached_model, None) if return_metrics else cached_model
        existing = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
        if not existing:
            logger.error("No model found in %s. Use --retrain or run_retrain.py first.", ARTIFACTS_DIR)
            sys.exit(1)
        logger.info("Using existing model: %s", existing[0])
        model = joblib.load(existing[0])
        return (model, None) if return_metrics else model

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

    # trial config 抽出
    trial_config = trial_config or {}
    training_cfg = trial_config.get("training", {}) or {}
    sw_cfg = training_cfg.get("sample_weight")
    lgb_params = trial_config.get("lgb_params")
    num_boost_round = int(training_cfg.get("num_boost_round", 1000))
    early_stopping_rounds = int(training_cfg.get("early_stopping_rounds", 50))

    need_dates = bool(sw_cfg and sw_cfg.get("mode"))
    if need_dates:
        X, y, race_dates = build_features_from_history(df_train, return_dates=True)
    else:
        X, y = build_features_from_history(df_train)
        race_dates = None

    # ranking 系 objective なら race_ids を trainer.train に渡す（タスク 6-10-d）
    objective = (lgb_params or {}).get("objective", "multiclass")
    race_ids_for_train: pd.Series | None = None
    if objective in {"lambdarank", "rank_xendcg"}:
        if "race_id" not in df_train.columns:
            raise RuntimeError(
                f"ranking objective '{objective}' requires race_id column in df_train"
            )
        race_ids_for_train = df_train.loc[X.index, "race_id"].reset_index(drop=True)

    sample_weight = None
    if need_dates and race_dates is not None:
        # 基準日: 学習期間の末日（前月末日）
        last_day = calendar.monthrange(train_end_year, train_end_month)[1]
        ref_date = pd.Timestamp(train_end_year, train_end_month, last_day)
        sample_weight = build_sample_weight(race_dates, ref_date, sw_cfg)
        if sample_weight is not None:
            logger.info(
                "  sample_weight mode=%s (min=%.3f, max=%.3f, mean=%.3f)",
                sw_cfg.get("mode"),
                float(sample_weight.min()),
                float(sample_weight.max()),
                float(sample_weight.mean()),
            )

    version = (
        f"{train_end_year}{train_end_month:02d}"
        f"_from{train_start_year}{train_start_month:02d}"
        f"_wf"
    )
    result = train(
        X, y, version,
        lgb_params=lgb_params,
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
        sample_weight=sample_weight,
        race_ids=race_ids_for_train,
        return_metrics=return_metrics,
    )
    if return_metrics:
        model_path = result["model_path"]
        model = joblib.load(model_path)
        return model, result
    return joblib.load(result)


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
    parser.add_argument("--bet-type",          type=str,   default="trifecta", choices=["trifecta", "trio", "both"], help="賭式: trifecta=3連単, trio=3連複, both=両方")
    parser.add_argument("--output",            type=str,   default=None, help="結果 CSV の保存先")
    parser.add_argument("--chunk-total",        type=int,   default=1,   help="並列チャンク総数（GH Actions matrix 用、デフォルト: 1 = 全月実行）")
    parser.add_argument("--chunk-index",        type=int,   default=0,   help="このジョブのチャンクインデックス（0始まり）")
    parser.add_argument("--retrain-interval",   type=int,   default=1,   help="再学習間隔（月数）。デフォルト 1 = 毎月。N=3 なら 3 ヶ月に 1 回再学習し中間月はモデルを再利用。")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    start_year,  start_month  = parse_ym(args.start)
    end_year,    end_month    = parse_ym(args.end)

    if (start_year, start_month) > (end_year, end_month):
        logger.error("--start は --end 以前の月を指定してください。")
        sys.exit(1)

    months = list(month_range(start_year, start_month, end_year, end_month))

    if args.chunk_total > 1:
        chunk_size = (len(months) + args.chunk_total - 1) // args.chunk_total
        months = months[args.chunk_index * chunk_size : (args.chunk_index + 1) * chunk_size]
        if not months:
            logger.info("チャンク %d/%d: 処理対象月なし。終了します。", args.chunk_index, args.chunk_total)
            return
        logger.info(
            "チャンク %d/%d: %d-%02d 〜 %d-%02d (%d ヶ月)",
            args.chunk_index, args.chunk_total,
            months[0][0], months[0][1], months[-1][0], months[-1][1], len(months),
        )
    else:
        logger.info("Walk-Forward: %d 月分を検証します (%s → %s)", len(months), args.start, args.end)

    if not args.real_odds:
        logger.warning(
            "--real-odds が指定されていません。合成オッズを使用します。"
            "ROI の絶対値は実際の収益性を反映しません。"
        )

    bet_types = ["trifecta", "trio"] if args.bet_type == "both" else [args.bet_type]
    # bet_type ごとの集計コンテナ
    all_results_by_bt: dict[str, list[pd.DataFrame]] = {bt: [] for bt in bet_types}
    monthly_rows_by_bt: dict[str, list[dict]] = {bt: [] for bt in bet_types}
    cached_model = None

    for i, (test_year, test_month) in enumerate(months):
        logger.info("── %d-%02d のバックテスト開始 ──", test_year, test_month)

        # 1. モデル取得（retrain_interval に基づき再学習 or 前月モデル再利用）
        should_retrain = args.retrain and (i % args.retrain_interval == 0)
        model = get_model_for_month(
            test_year, test_month,
            retrain=should_retrain,
            train_start_year=args.train_start_year,
            train_start_month=args.train_start_month,
            cached_model=cached_model,
        )
        cached_model = model  # 次月以降で再利用（再学習した場合も更新）

        # 2. テストデータ取得
        df_test = load_month_data(test_year, test_month)
        if df_test.empty:
            logger.warning("%d-%02d: データなし、スキップ", test_year, test_month)
            continue

        # 3. 実オッズ取得
        odds_by_race: dict[str, dict[str, float]] = {}
        trio_odds_by_race: dict[str, dict[str, float]] = {}
        if args.real_odds:
            if "trifecta" in bet_types:
                odds_by_race = load_or_download_month_odds(test_year, test_month, df_test)
                logger.info("3連単実オッズ: %d レース分取得", len(odds_by_race))
            if "trio" in bet_types:
                trio_odds_by_race = load_or_download_month_trio_odds(test_year, test_month, df_test)
                logger.info("3連複実オッズ: %d レース分取得", len(trio_odds_by_race))

        # 4. バックテスト（bet_type ごとに実行）
        n_races = df_test["race_id"].nunique()
        for bt in bet_types:
            race_odds = trio_odds_by_race if bt == "trio" else odds_by_race
            logger.info("%d-%02d [%s]: %d レースをバックテスト中...", test_year, test_month, bt, n_races)
            results, skipped = run_backtest_batch(
                df_test=df_test,
                model=model,
                odds_by_race=race_odds,
                prob_threshold=args.prob_threshold,
                bet_amount=args.bet_amount,
                max_bets_per_race=args.max_bets,
                ev_threshold=args.ev_threshold,
                exclude_courses=args.exclude_courses,
                min_odds=args.min_odds,
                exclude_stadiums=args.exclude_stadiums,
                bet_type=bt,
            )
            logger.info("%d-%02d [%s]: 完了 %d レース、スキップ %d", test_year, test_month, bt, len(results), skipped)

            if not results:
                continue

            df_month = pd.DataFrame(results)
            all_results_by_bt[bt].append(df_month)

            wagered = float(df_month["amount_wagered"].sum())
            payout  = float(df_month["payout_received"].sum())
            n_bets  = int(df_month["bets_placed"].sum())
            wins    = int(df_month["matched"].sum())
            monthly_rows_by_bt[bt].append({
                "month":   f"{test_year}-{test_month:02d}",
                "wagered": wagered,
                "payout":  payout,
                "n_bets":  n_bets,
                "wins":    wins,
            })

    label_start = f"{start_year}{start_month:02d}"
    label_end   = f"{end_year}{end_month:02d}"
    if args.chunk_total > 1:
        chunk_suffix = f"_chunk{args.chunk_index}of{args.chunk_total}"
    else:
        chunk_suffix = ""

    any_results = False
    all_dfs_for_csv: list[pd.DataFrame] = []

    for bt in bet_types:
        if not all_results_by_bt[bt]:
            logger.warning("[%s] 全月でデータが取得できませんでした。", bt)
            continue
        any_results = True

        all_results = pd.concat(all_results_by_bt[bt], ignore_index=True).sort_values(["race_date", "race_id"])
        all_dfs_for_csv.append(all_results)

        # 5. サマリー表示
        if args.bet_type == "both":
            print(f"\n{'='*62}")
            print(f"  賭式: {'3連単 (trifecta)' if bt == 'trifecta' else '3連複 (trio)'}")
        print_summary(all_results, monthly_rows_by_bt[bt], args.prob_threshold, args.ev_threshold, args.bet_amount)

    if not any_results:
        logger.error("全月・全賭式でデータが取得できませんでした。")
        sys.exit(1)

    # 6. CSV 保存（全賭式を結合）
    combined = pd.concat(all_dfs_for_csv, ignore_index=True).sort_values(["race_date", "race_id"])
    output_path = args.output or str(ARTIFACTS_DIR / f"walkforward_{label_start}-{label_end}{chunk_suffix}.csv")
    combined.to_csv(output_path, index=False)
    logger.info("結果を保存: %s", output_path)


if __name__ == "__main__":
    main()
