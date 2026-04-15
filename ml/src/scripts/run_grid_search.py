"""
prob_threshold × ev_threshold グリッドサーチ

バックテストの全組み合わせ予測データ（combo CSV）に対して、
複数の (prob_threshold, ev_threshold) の組み合わせを試して
ROI・的中率・投資額を比較し、最適な閾値を特定する。

使い方:
  # STEP 1: combo CSV を生成（--collect-combos オプション付きでバックテスト実行）
  python run_grid_search.py --year 2025 --month 12 --real-odds --collect-combos
  → artifacts/combos_202512.csv が生成される

  # STEP 2: 既存の combo CSV を使ってグリッドサーチのみ実行
  python run_grid_search.py --combos-csv artifacts/combos_202512.csv

  # STEP 3: combo 生成 → グリッドサーチを一括実行
  python run_grid_search.py --year 2025 --month 12 --real-odds

オプション:
  --year              テスト年（combo CSV 生成時に必須）
  --month             テスト月（combo CSV 生成時に必須）
  --retrain           モデルを再学習してからバックテスト
  --train-start-year  --retrain 時の学習開始年（デフォルト: 2023）
  --train-start-month --retrain 時の学習開始月（デフォルト: 1）
  --real-odds         実オッズを使用
  --combos-csv        既存の combo CSV パス（指定時はデータ生成をスキップ）
  --bet-amount        1 点賭け金（デフォルト: 100）
  --max-bets          1 レース最大賭け点数（デフォルト: 5）
  --output            グリッドサーチ結果 CSV の保存先
"""
import argparse
import calendar
import logging
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from itertools import product
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
from collector.odds_downloader import load_or_download_month_odds
from collector.program_downloader import (
    load_program_month,
    load_program_range,
    merge_program_data,
)
from features.feature_builder import build_features_from_history
from model.trainer import train
from backtest.engine import run_backtest_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"

# グリッドサーチの閾値候補
PROB_THRESHOLDS = [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]
EV_THRESHOLDS   = [0.0, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0]


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def load_month_data(year: int, month: int, max_workers: int = 8) -> pd.DataFrame:
    days_in_month = calendar.monthrange(year, month)[1]
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_gs_"))
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


def get_or_train_model(args: argparse.Namespace):
    if not args.retrain:
        existing = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
        if not existing:
            logger.error("No model found in %s.", ARTIFACTS_DIR)
            sys.exit(1)
        logger.info("Using existing model: %s", existing[0])
        return joblib.load(existing[0])

    if args.month > 1:
        train_end_year, train_end_month = args.year, args.month - 1
    else:
        train_end_year, train_end_month = args.year - 1, 12

    df_train = load_history_range(
        start_year=args.train_start_year,
        end_year=train_end_year,
        start_month=args.train_start_month,
        end_month=train_end_month,
    )
    if df_train.empty or len(df_train) < 1000:
        logger.error("Training data too small (%d rows).", len(df_train))
        sys.exit(1)

    df_prog = load_program_range(
        start_year=args.train_start_year,
        end_year=train_end_year,
        start_month=args.train_start_month,
        end_month=train_end_month,
    )
    df_train = merge_program_data(df_train, df_prog)
    X, y = build_features_from_history(df_train)
    version = f"{train_end_year}{train_end_month:02d}_from{args.train_start_year}{args.train_start_month:02d}"
    model_path = train(X, y, version)
    return joblib.load(model_path)


# ---------------------------------------------------------------------------
# グリッドサーチ本体
# ---------------------------------------------------------------------------

def apply_thresholds(
    combos_df: pd.DataFrame,
    prob_threshold: float,
    ev_threshold: float,
    bet_amount: int,
    max_bets: int,
) -> dict:
    """
    combo_records DataFrame に閾値を適用して ROI 等を計算する。

    combos_df の必須列:
      race_id, combination, win_probability, expected_value,
      odds, actual_combo, is_hit, bet_amount
    """
    # 閾値フィルタ
    mask = (
        (combos_df["win_probability"] >= prob_threshold)
        & (combos_df["expected_value"] >= ev_threshold)
    )
    filtered = combos_df[mask].copy()

    if filtered.empty:
        return {
            "prob_threshold": prob_threshold,
            "ev_threshold":   ev_threshold,
            "n_races_bet":    0,
            "n_bets":         0,
            "wagered":        0.0,
            "payout":         0.0,
            "profit":         0.0,
            "roi":            float("nan"),
            "win_rate":       float("nan"),
            "n_wins":         0,
            "avg_hit_odds":   float("nan"),
        }

    # レースごとに EV 降順で max_bets 点に制限
    filtered = filtered.sort_values("expected_value", ascending=False)
    filtered = filtered.groupby("race_id").head(max_bets).reset_index(drop=True)

    n_bets     = len(filtered)
    n_races    = filtered["race_id"].nunique()
    n_wins     = int(filtered["is_hit"].sum())
    wagered    = n_bets * bet_amount
    payout     = float((filtered["is_hit"] * filtered["odds"] * bet_amount).sum())
    profit     = payout - wagered
    roi        = (payout / wagered - 1) * 100 if wagered > 0 else float("nan")
    win_rate   = n_wins / n_bets * 100 if n_bets > 0 else float("nan")
    avg_hit_odds = float(filtered.loc[filtered["is_hit"], "odds"].mean()) if n_wins > 0 else float("nan")

    return {
        "prob_threshold": prob_threshold,
        "ev_threshold":   ev_threshold,
        "n_races_bet":    n_races,
        "n_bets":         n_bets,
        "wagered":        wagered,
        "payout":         payout,
        "profit":         profit,
        "roi":            roi,
        "win_rate":       win_rate,
        "n_wins":         n_wins,
        "avg_hit_odds":   avg_hit_odds,
    }


def run_grid_search(
    combos_df: pd.DataFrame,
    bet_amount: int,
    max_bets: int,
    prob_thresholds: list[float] = PROB_THRESHOLDS,
    ev_thresholds:   list[float] = EV_THRESHOLDS,
) -> pd.DataFrame:
    rows = []
    for prob_th, ev_th in product(prob_thresholds, ev_thresholds):
        rows.append(apply_thresholds(combos_df, prob_th, ev_th, bet_amount, max_bets))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# サマリー出力
# ---------------------------------------------------------------------------

def print_grid_summary(grid_df: pd.DataFrame) -> None:
    """グリッドサーチ結果のサマリーを出力する。"""
    valid = grid_df[grid_df["n_bets"] >= 10].copy()  # 購入点数が少なすぎるものは除外
    if valid.empty:
        print("  有効な組み合わせがありません（n_bets < 10 のみ）。")
        return

    best = valid.loc[valid["roi"].idxmax()]

    print()
    print("=" * 70)
    print("  グリッドサーチ結果")
    print("=" * 70)
    print(f"  総組み合わせ数   : {len(grid_df)}")
    print(f"  有効（賭け≥10点）: {len(valid)}")
    print()
    print("  [ROI上位5組み合わせ]")
    print(f"  {'prob(%)':>7}  {'EV':>5}  {'賭け点':>6}  {'投資':>9}  {'ROI':>7}  {'的中率':>6}  {'的中'}")
    print("  " + "-" * 60)
    for _, row in valid.nlargest(5, "roi").iterrows():
        print(
            f"  {row['prob_threshold']*100:>6.1f}%  "
            f"{row['ev_threshold']:>5.2f}  "
            f"{int(row['n_bets']):>6,}  "
            f"¥{row['wagered']:>8,.0f}  "
            f"{row['roi']:>+6.1f}%  "
            f"{row['win_rate']:>5.2f}%  "
            f"{int(row['n_wins'])}"
        )
    print()
    print(f"  最良: prob≥{best['prob_threshold']*100:.1f}% × EV≥{best['ev_threshold']:.2f}  "
          f"→ ROI {best['roi']:+.1f}%  ({int(best['n_bets'])} 点)")
    print("=" * 70)
    print()


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="prob_threshold × ev_threshold グリッドサーチ",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--year",               type=int,  default=None,  help="テスト年（combo 生成時に使用）")
    parser.add_argument("--month",              type=int,  default=None,  help="テスト月（combo 生成時に使用）")
    parser.add_argument("--retrain",            action="store_true",      help="モデルを再学習")
    parser.add_argument("--train-start-year",   type=int,  default=2023,  help="学習開始年")
    parser.add_argument("--train-start-month",  type=int,  default=1,     help="学習開始月")
    parser.add_argument("--real-odds",          action="store_true",      help="実オッズを使用")
    parser.add_argument("--combos-csv",         type=str,  default=None,  help="既存 combo CSV のパス")
    parser.add_argument("--bet-amount",         type=int,  default=100,   help="1 点賭け金（円）")
    parser.add_argument("--max-bets",           type=int,  default=5,     help="1 レース最大賭け点数")
    parser.add_argument("--output",             type=str,  default=None,  help="グリッドサーチ結果 CSV の保存先")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    # ── 1. combo CSV の取得 ──────────────────────────────
    if args.combos_csv:
        logger.info("既存 combo CSV を読み込み: %s", args.combos_csv)
        combos_df = pd.read_csv(args.combos_csv)
        label = Path(args.combos_csv).stem.replace("combos_", "")
    else:
        if args.year is None or args.month is None:
            logger.error("--year と --month を指定してください（または --combos-csv を指定）。")
            sys.exit(1)

        label = f"{args.year}{args.month:02d}"
        combos_csv_path = ARTIFACTS_DIR / f"combos_{label}.csv"

        # キャッシュ済みなら再利用
        if combos_csv_path.exists():
            logger.info("キャッシュ済み combo CSV を使用: %s", combos_csv_path)
            combos_df = pd.read_csv(combos_csv_path)
        else:
            # モデル取得
            model = get_or_train_model(args)

            # テストデータ取得
            logger.info("テストデータを取得中: %d-%02d", args.year, args.month)
            df_test = load_month_data(args.year, args.month)
            if df_test.empty:
                logger.error("データが見つかりません: %d-%02d", args.year, args.month)
                sys.exit(1)

            # 実オッズ取得
            odds_by_race: dict[str, dict[str, float]] = {}
            if args.real_odds:
                odds_by_race = load_or_download_month_odds(args.year, args.month, df_test)
                logger.info("実オッズ: %d レース分取得", len(odds_by_race))

            # バックテスト（collect_combos=True）
            logger.info("全組み合わせデータを収集中...")
            _, skipped, combo_records = run_backtest_batch(
                df_test=df_test,
                model=model,
                odds_by_race=odds_by_race,
                prob_threshold=0.0,   # 全組み合わせ収集のため閾値なし
                bet_amount=args.bet_amount,
                max_bets_per_race=120,  # 全 120 通り
                ev_threshold=0.0,
                collect_combos=True,
            )
            logger.info("Combo 収集完了: %d 組み合わせ、スキップ %d レース", len(combo_records), skipped)

            combos_df = pd.DataFrame(combo_records)
            combos_df.to_csv(combos_csv_path, index=False)
            logger.info("Combo CSV 保存: %s", combos_csv_path)

    # ── 2. グリッドサーチ実行 ────────────────────────────
    logger.info(
        "グリッドサーチ開始: prob×%d × ev×%d = %d 組み合わせ",
        len(PROB_THRESHOLDS), len(EV_THRESHOLDS),
        len(PROB_THRESHOLDS) * len(EV_THRESHOLDS),
    )
    grid_df = run_grid_search(
        combos_df,
        bet_amount=args.bet_amount,
        max_bets=args.max_bets,
    )

    # ── 3. 結果保存 ─────────────────────────────────────
    output_path = args.output or str(ARTIFACTS_DIR / f"grid_search_{label}.csv")
    grid_df.to_csv(output_path, index=False)
    logger.info("グリッドサーチ結果保存: %s", output_path)

    # ── 4. サマリー表示 ──────────────────────────────────
    print_grid_summary(grid_df)

    # 現在の設定（prob=5%, EV=1.2）の結果も表示
    current = grid_df[
        (grid_df["prob_threshold"] == 0.05) & (grid_df["ev_threshold"] == 1.2)
    ]
    if not current.empty:
        row = current.iloc[0]
        print(f"  [現行設定 prob≥5% × EV≥1.2]  ROI: {row['roi']:+.1f}%  "
              f"賭け: {int(row['n_bets'])} 点  的中: {int(row['n_wins'])}")
        print()


if __name__ == "__main__":
    main()
