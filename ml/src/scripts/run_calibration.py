"""
モデルキャリブレーション分析スクリプト

モデルが出力する確率が実際の頻度と一致しているかを分析する。
例: 「P(1着)=20%と予測した艇が実際に1着になる割合は20%か？」

出力:
  artifacts/calibration_{YYYYMM}.csv
    - 予測確率ビン × クラス別のキャリブレーション統計
    - expected_prob, actual_freq, n_samples, overconfidence

分析内容:
  1. クラス別信頼度キャリブレーション（艇の1着・2着・3着確率が適切か）
  2. 3連単予測確率のキャリブレーション（高確率の組み合わせは実際に当たるか）
  3. Expected Calibration Error (ECE) の計算

使い方:
  # テストデータでキャリブレーション分析
  python run_calibration.py --year 2025 --month 12

  # 再学習したモデルで分析
  python run_calibration.py --year 2025 --month 12 --retrain

  # 既存の combo CSV を使って3連単キャリブレーションのみ
  python run_calibration.py --combos-csv artifacts/combos_202512.csv
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
from model.predictor import calc_trifecta_probs
from backtest.engine import run_backtest_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"
N_BINS = 10  # キャリブレーションビン数


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def load_month_data(year: int, month: int, max_workers: int = 8) -> pd.DataFrame:
    days_in_month = calendar.monthrange(year, month)[1]
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_cal_"))
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
# キャリブレーション計算
# ---------------------------------------------------------------------------

def calibration_curve_data(
    y_prob: np.ndarray,
    y_true_binary: np.ndarray,
    n_bins: int = N_BINS,
) -> pd.DataFrame:
    """
    予測確率を n_bins に分割し、各ビンでの期待確率と実際の正解率を計算する。

    Parameters
    ----------
    y_prob         : (N,) 予測確率
    y_true_binary  : (N,) 二値の正解ラベル（1=正解, 0=不正解）
    n_bins         : ビン数

    Returns
    -------
    DataFrame with columns:
      bin_lower, bin_upper, bin_center, expected_prob, actual_freq, n_samples, calibration_error
    """
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi)
        if mask.sum() == 0:
            continue
        mean_prob = float(y_prob[mask].mean())
        actual_freq = float(y_true_binary[mask].mean())
        n = int(mask.sum())
        rows.append({
            "bin_lower":         lo,
            "bin_upper":         hi,
            "bin_center":        (lo + hi) / 2,
            "expected_prob":     mean_prob,
            "actual_freq":       actual_freq,
            "n_samples":         n,
            "calibration_error": mean_prob - actual_freq,  # 正 = 過信、負 = 過少信頼
        })
    return pd.DataFrame(rows)


def expected_calibration_error(cal_df: pd.DataFrame) -> float:
    """ECE = Σ(n_i / N) * |expected_prob_i - actual_freq_i|"""
    n_total = cal_df["n_samples"].sum()
    if n_total == 0:
        return float("nan")
    ece = float((cal_df["n_samples"] / n_total * cal_df["calibration_error"].abs()).sum())
    return ece


def analyze_class_calibration(
    raw_probs: np.ndarray,
    y_true: np.ndarray,
    n_bins: int = N_BINS,
) -> tuple[pd.DataFrame, dict]:
    """
    各着順クラス（1〜6着）のキャリブレーションを分析する。

    Parameters
    ----------
    raw_probs : (N, 6) 全クラスの予測確率
    y_true    : (N,) 正解クラス（0-indexed: 0=1着, ..., 5=6着）

    Returns
    -------
    (cal_df, ece_dict)
      cal_df   : クラス別キャリブレーションデータ
      ece_dict : クラス別 ECE
    """
    all_rows = []
    ece_dict = {}

    for k in range(6):  # k=0 → 1着, ..., k=5 → 6着
        prob_k = raw_probs[:, k]
        true_k = (y_true == k).astype(int)

        cal_df = calibration_curve_data(prob_k, true_k, n_bins=n_bins)
        cal_df["class"] = k + 1  # 1-indexed で保存
        all_rows.append(cal_df)

        ece = expected_calibration_error(cal_df)
        ece_dict[k + 1] = ece
        logger.info("クラス %d着: ECE=%.4f  サンプル=%d", k + 1, ece, int(true_k.sum()))

    return pd.concat(all_rows, ignore_index=True), ece_dict


def analyze_trifecta_calibration(
    combos_df: pd.DataFrame,
    n_bins: int = N_BINS,
) -> tuple[pd.DataFrame, float]:
    """
    3連単予測確率のキャリブレーションを分析する。

    combos_df には win_probability, is_hit 列が必要。
    """
    prob = combos_df["win_probability"].values
    hit  = combos_df["is_hit"].astype(int).values

    cal_df = calibration_curve_data(prob, hit, n_bins=n_bins)
    ece    = expected_calibration_error(cal_df)
    logger.info("3連単 ECE=%.4f  的中件数=%d / %d", ece, int(hit.sum()), len(hit))
    return cal_df, ece


# ---------------------------------------------------------------------------
# サマリー出力
# ---------------------------------------------------------------------------

def print_calibration_summary(
    class_ece: dict,
    trifecta_ece: float,
) -> None:
    print()
    print("=" * 62)
    print("  キャリブレーション分析結果")
    print("=" * 62)
    print("  [着順クラス別 ECE]  ※ ECE が小さいほど確率が正確")
    print(f"  {'クラス':>6}  {'ECE':>8}  {'評価'}")
    print("  " + "-" * 30)
    for k, ece in sorted(class_ece.items()):
        rating = "良好" if ece < 0.02 else ("要改善" if ece < 0.05 else "不良")
        print(f"  {k:>3}着   {ece:>8.4f}  {rating}")
    print()
    avg_ece = np.mean(list(class_ece.values()))
    print(f"  平均 ECE: {avg_ece:.4f}")
    print()
    print(f"  [3連単予測 ECE]: {trifecta_ece:.4f}")
    rating = "良好" if trifecta_ece < 0.005 else ("要改善" if trifecta_ece < 0.02 else "不良")
    print(f"  評価: {rating}")
    print()
    print("  ※ ECE > 0.05（クラス別）または > 0.02（3連単）は")
    print("    キャリブレーション補正（Session 3）を推奨")
    print("=" * 62)
    print()


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="モデルキャリブレーション分析",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--year",               type=int,  default=None,  help="テスト年")
    parser.add_argument("--month",              type=int,  default=None,  help="テスト月")
    parser.add_argument("--retrain",            action="store_true",      help="モデルを再学習")
    parser.add_argument("--train-start-year",   type=int,  default=2023,  help="学習開始年")
    parser.add_argument("--train-start-month",  type=int,  default=1,     help="学習開始月")
    parser.add_argument("--real-odds",          action="store_true",      help="実オッズを使用（3連単分析用）")
    parser.add_argument("--combos-csv",         type=str,  default=None,  help="既存 combo CSV（3連単分析用）")
    parser.add_argument("--n-bins",             type=int,  default=10,    help="キャリブレーションビン数")
    parser.add_argument("--output-prefix",      type=str,  default=None,  help="出力 CSV のプレフィックス")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    # ── ラベル決定 ──────────────────────────────────────
    if args.year and args.month:
        label = f"{args.year}{args.month:02d}"
    elif args.combos_csv:
        label = Path(args.combos_csv).stem.replace("combos_", "")
    else:
        logger.error("--year/--month または --combos-csv を指定してください。")
        sys.exit(1)

    prefix = args.output_prefix or str(ARTIFACTS_DIR / f"calibration_{label}")

    # ── A. クラスキャリブレーション分析（モデルが必要） ───
    class_ece: dict[int, float] = {}
    class_cal_df: pd.DataFrame | None = None

    if args.year and args.month:
        model = get_or_train_model(args)
        df_test = load_month_data(args.year, args.month)
        if df_test.empty:
            logger.error("データが見つかりません: %d-%02d", args.year, args.month)
            sys.exit(1)

        logger.info("特徴量を生成中...")
        try:
            X_all, _ = build_features_from_history(df_test)
        except Exception as exc:
            logger.error("特徴量生成失敗: %s", exc)
            sys.exit(1)

        if X_all.empty:
            logger.error("有効な特徴量行がありません。")
            sys.exit(1)

        # 正解ラベルを取得（着順 - 1、0-indexed）
        df_valid = df_test.loc[X_all.index].copy()
        if "finish_position" not in df_valid.columns:
            logger.warning("finish_position 列がありません。クラスキャリブレーションをスキップ。")
        else:
            y_true = (df_valid["finish_position"] - 1).clip(0, 5).values.astype(int)
            # 新形式 dict の場合は booster を取り出す（キャリブレーション前の生確率を使用）
            booster = model["booster"] if isinstance(model, dict) else model
            raw_probs = booster.predict(X_all)

            if raw_probs.ndim == 1 or raw_probs.shape[1] != 6:
                logger.warning("予測形状が (N, 6) ではありません。クラスキャリブレーションをスキップ。")
            else:
                logger.info("クラスキャリブレーション分析中 (%d サンプル)...", len(y_true))
                class_cal_df, class_ece = analyze_class_calibration(raw_probs, y_true, n_bins=args.n_bins)
                out_class = f"{prefix}_class.csv"
                class_cal_df.to_csv(out_class, index=False)
                logger.info("クラスキャリブレーション保存: %s", out_class)

    # ── B. 3連単キャリブレーション分析 ────────────────────
    combos_df: pd.DataFrame | None = None

    if args.combos_csv:
        combos_df = pd.read_csv(args.combos_csv)
    elif args.year and args.month:
        # グリッドサーチ用 combo CSV があれば再利用
        combos_csv_cache = ARTIFACTS_DIR / f"combos_{label}.csv"
        if combos_csv_cache.exists():
            logger.info("キャッシュ済み combo CSV を使用: %s", combos_csv_cache)
            combos_df = pd.read_csv(combos_csv_cache)
        else:
            # combo CSV を生成（全組み合わせ収集）
            if args.year and args.month and "model" in dir():
                odds_by_race: dict[str, dict[str, float]] = {}
                if args.real_odds:
                    odds_by_race = load_or_download_month_odds(args.year, args.month, df_test)
                    logger.info("実オッズ: %d レース分取得", len(odds_by_race))

                logger.info("全 3 連単組み合わせデータを収集中...")
                _, _, combo_records = run_backtest_batch(
                    df_test=df_test,
                    model=model,
                    odds_by_race=odds_by_race,
                    prob_threshold=0.0,
                    bet_amount=100,
                    max_bets_per_race=120,
                    ev_threshold=0.0,
                    collect_combos=True,
                )
                combos_df = pd.DataFrame(combo_records)
                combos_df.to_csv(combos_csv_cache, index=False)
                logger.info("Combo CSV 保存: %s", combos_csv_cache)

    trifecta_ece = float("nan")
    if combos_df is not None and not combos_df.empty:
        logger.info("3連単キャリブレーション分析中 (%d 組み合わせ)...", len(combos_df))
        trifecta_cal_df, trifecta_ece = analyze_trifecta_calibration(
            combos_df, n_bins=args.n_bins
        )
        out_trifecta = f"{prefix}_trifecta.csv"
        trifecta_cal_df.to_csv(out_trifecta, index=False)
        logger.info("3連単キャリブレーション保存: %s", out_trifecta)

        # 過信・過少信頼の概要
        over = trifecta_cal_df[trifecta_cal_df["calibration_error"] > 0.005]
        under = trifecta_cal_df[trifecta_cal_df["calibration_error"] < -0.005]
        logger.info(
            "3連単: 過信ビン=%d  過少信頼ビン=%d",
            len(over), len(under),
        )
    else:
        logger.warning("3連単キャリブレーション: データなし（--combos-csv または --real-odds を指定）")

    # ── C. サマリー出力 ──────────────────────────────────
    if class_ece or not np.isnan(trifecta_ece):
        print_calibration_summary(class_ece, trifecta_ece)
    else:
        logger.warning("分析データが不足しています。引数を確認してください。")

    # ── D. 要約 CSV 保存 ────────────────────────────────
    summary_rows = []
    for k, ece in class_ece.items():
        summary_rows.append({"analysis": f"class_{k}着", "ece": ece})
    if not np.isnan(trifecta_ece):
        summary_rows.append({"analysis": "trifecta", "ece": trifecta_ece})

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        out_summary = f"{prefix}_summary.csv"
        summary_df.to_csv(out_summary, index=False)
        logger.info("要約保存: %s", out_summary)


if __name__ == "__main__":
    main()
