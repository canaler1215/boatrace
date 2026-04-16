"""
特徴量重要度・SHAP値の可視化スクリプト

処理フロー:
  1. 最新の学習済みモデルをロード
  2. 指定月の K+B ファイルから検証データを生成
  3. LightGBM feature importance (gain / split) を CSV + PNG に保存
  4. SHAP 値を計算して beeswarm plot を PNG に保存
  5. 全出力は artifacts/feature_importance_{YYYYMM}_{type}.{csv,png}

Usage:
  python ml/src/scripts/run_feature_importance.py [--year YEAR] [--month MONTH] [--model MODEL]

  --year    検証データの年 (デフォルト: 今年)
  --month   検証データの月 (デフォルト: 先月)
  --model   モデルファイルパス (デフォルト: artifacts/model_latest.pkl)
  --no-shap SHAP 計算をスキップ (shap ライブラリ未インストール時など)
"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.history_downloader import load_history_range
from collector.program_downloader import load_program_range, merge_program_data
from features.feature_builder import build_features_from_history, FEATURE_COLUMNS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"


def _load_model(model_path: Path):
    logger.info("Loading model: %s", model_path)
    return joblib.load(model_path)


def _get_validation_data(year: int, month: int) -> tuple[pd.DataFrame, pd.Series]:
    """指定月の K+B データから検証用特徴量・ラベルを生成"""
    logger.info("Loading K-file data for %d-%02d...", year, month)
    df_k = load_history_range(
        start_year=year, end_year=year,
        start_month=month, end_month=month,
    )
    if df_k.empty:
        raise RuntimeError(f"No K-file data for {year}-{month:02d}")

    logger.info("Loading B-file data for %d-%02d...", year, month)
    df_b = load_program_range(
        start_year=year, end_year=year,
        start_month=month, end_month=month,
    )
    df = merge_program_data(df_k, df_b)
    logger.info("Merged %d records", len(df))

    X, y = build_features_from_history(df)
    logger.info("Feature matrix: %s", X.shape)
    return X, y


def save_feature_importance(model, version: str) -> None:
    """LightGBM の gain / split 重要度を CSV + PNG に保存"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available — skipping importance plots")
        return

    for importance_type in ("gain", "split"):
        importance = model.feature_importance(importance_type=importance_type)
        fi = pd.DataFrame({
            "feature": FEATURE_COLUMNS,
            "importance": importance,
        }).sort_values("importance", ascending=False)

        csv_path = ARTIFACTS_DIR / f"feature_importance_{version}_{importance_type}.csv"
        fi.to_csv(csv_path, index=False)
        logger.info("Saved: %s", csv_path)

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(fi["feature"][::-1], fi["importance"][::-1])
        ax.set_title(f"Feature Importance ({importance_type})  [{version}]")
        ax.set_xlabel(importance_type.capitalize())
        ax.set_ylabel("Feature")
        fig.tight_layout()
        png_path = ARTIFACTS_DIR / f"feature_importance_{version}_{importance_type}.png"
        fig.savefig(png_path, dpi=150)
        plt.close(fig)
        logger.info("Saved: %s", png_path)


def save_shap_analysis(model, X: pd.DataFrame, y: pd.Series, version: str) -> None:
    """SHAP 値を計算して beeswarm / bar plot を保存"""
    try:
        import shap
    except ImportError:
        logger.warning("shap not installed — skipping SHAP analysis. Run: pip install shap")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available — skipping SHAP plots")
        return

    logger.info("Computing SHAP values (this may take a minute)...")

    # サンプリング: 大きすぎると遅いので最大 5000 行
    if len(X) > 5000:
        idx = np.random.default_rng(42).choice(len(X), size=5000, replace=False)
        X_sample = X.iloc[idx].reset_index(drop=True)
    else:
        X_sample = X.reset_index(drop=True)

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)  # shape: [n_classes, n_samples, n_features]

    # クラス 0 (1着) の SHAP 値を可視化
    sv_class0 = shap_values[0]  # shape: [n_samples, n_features]

    # --- Beeswarm (summary) plot ---
    fig, ax = plt.subplots(figsize=(9, 6))
    shap.summary_plot(
        sv_class0, X_sample, feature_names=FEATURE_COLUMNS,
        show=False, max_display=12,
    )
    plt.title(f"SHAP Summary (1着確率 Class 0)  [{version}]")
    plt.tight_layout()
    png_path = ARTIFACTS_DIR / f"shap_summary_{version}.png"
    plt.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("Saved: %s", png_path)

    # --- Bar plot (mean |SHAP|) ---
    mean_abs_shap = np.abs(sv_class0).mean(axis=0)
    fi_shap = pd.DataFrame({
        "feature": FEATURE_COLUMNS,
        "mean_abs_shap": mean_abs_shap,
    }).sort_values("mean_abs_shap", ascending=False)

    csv_path = ARTIFACTS_DIR / f"shap_importance_{version}.csv"
    fi_shap.to_csv(csv_path, index=False)
    logger.info("Saved: %s", csv_path)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(fi_shap["feature"][::-1], fi_shap["mean_abs_shap"][::-1])
    ax.set_title(f"Mean |SHAP| (1着確率)  [{version}]")
    ax.set_xlabel("Mean |SHAP value|")
    fig.tight_layout()
    png_path = ARTIFACTS_DIR / f"shap_bar_{version}.png"
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    logger.info("Saved: %s", png_path)

    # --- 全クラスの SHAP 重要度 CSV ---
    all_class_shap = pd.DataFrame(index=FEATURE_COLUMNS)
    for cls_idx in range(len(shap_values)):
        all_class_shap[f"class_{cls_idx}_mean_abs"] = np.abs(shap_values[cls_idx]).mean(axis=0)
    all_class_shap.index.name = "feature"
    all_csv = ARTIFACTS_DIR / f"shap_all_classes_{version}.csv"
    all_class_shap.to_csv(all_csv)
    logger.info("Saved: %s", all_csv)


def main() -> None:
    today = date.today()
    default_month = today.month - 1 if today.month > 1 else 12
    default_year = today.year if today.month > 1 else today.year - 1

    parser = argparse.ArgumentParser(description="特徴量重要度・SHAP値の可視化")
    parser.add_argument("--year", type=int, default=default_year)
    parser.add_argument("--month", type=int, default=default_month)
    parser.add_argument(
        "--model",
        type=Path,
        default=ARTIFACTS_DIR / "model_latest.pkl",
        help="モデルファイルパス",
    )
    parser.add_argument(
        "--no-shap",
        action="store_true",
        help="SHAP 計算をスキップ",
    )
    args = parser.parse_args()

    version = f"{args.year}{args.month:02d}"
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    # 1. モデルロード
    if not args.model.exists():
        logger.error("Model not found: %s", args.model)
        sys.exit(1)
    model = _load_model(args.model)

    # 2. 検証データ生成
    X, y = _get_validation_data(args.year, args.month)

    # 3. LightGBM feature importance
    logger.info("Computing LightGBM feature importance...")
    save_feature_importance(model, version)

    # 4. SHAP値
    if not args.no_shap:
        save_shap_analysis(model, X, y, version)
    else:
        logger.info("SHAP analysis skipped (--no-shap)")

    logger.info("=== run_feature_importance done (version=%s) ===", version)
    logger.info("Output files in: %s", ARTIFACTS_DIR)


if __name__ == "__main__":
    main()
