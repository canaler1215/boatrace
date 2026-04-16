"""
retrain.yml から呼び出されるモデル再学習スクリプト

処理フロー:
  1. boatrace.jp から指定年範囲の歴史データをダウンロード・パース
  2. 特徴量エンジニアリング (build_features_from_history)
  3. LightGBM 学習 (train_test_split で検証データを分離)
  4. RPS 評価
  5. artifacts/model_{YYYYMM}.pkl を保存
  6. model_versions テーブルに登録 (is_active=true)
  7. GitHub Releases へのアップロードは retrain.yml の softprops/action-gh-release で行う
"""
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np

from collector.db_writer import get_connection, register_model_version
from collector.history_downloader import load_history_range
from collector.program_downloader import load_program_range, merge_program_data
from features.feature_builder import build_features_from_history
from model.evaluator import evaluate
from model.trainer import train

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 訓練に使う年範囲 (START_YEAR を古くするほど学習データが増えるが時間もかかる)
# 環境変数 TRAIN_START_YEAR / TRAIN_START_MONTH で上書き可能（retrain.yml から注入）
START_YEAR  = int(os.environ.get("TRAIN_START_YEAR",  "2022"))
START_MONTH = int(os.environ.get("TRAIN_START_MONTH", "1"))
ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"


def main() -> None:
    today = date.today()
    version = today.strftime("%Y%m")
    data_range_from = f"{START_YEAR}-{START_MONTH:02d}-01"
    data_range_to = today.isoformat()

    logger.info("=== retrain start: version=%s ===", version)
    logger.info("Data range: %s ~ %s", data_range_from, data_range_to)

    # ------------------------------------------------------------------
    # 1. 歴史データ取得
    # ------------------------------------------------------------------
    logger.info("Loading history data (%d-%02d ~ %d)...", START_YEAR, START_MONTH, today.year)
    df = load_history_range(
        start_year=START_YEAR, end_year=today.year,
        start_month=START_MONTH,
    )

    if df.empty:
        logger.error(
            "No history data loaded. "
            "Please verify the download URL in history_downloader.py and re-run."
        )
        sys.exit(1)

    logger.info("Loaded %d K-file records", len(df))

    # B ファイル（出走表）から特徴量を補完
    logger.info("Loading B-file program data (%d-%02d ~ %d)...", START_YEAR, START_MONTH, today.year)
    df_prog = load_program_range(
        start_year=START_YEAR, end_year=today.year,
        start_month=START_MONTH,
    )
    df = merge_program_data(df, df_prog)

    logger.info("Merged %d records total", len(df))

    # ------------------------------------------------------------------
    # 2. 特徴量生成
    # ------------------------------------------------------------------
    logger.info("Building features...")
    X, y = build_features_from_history(df)
    logger.info("Feature matrix: %s, label distribution:\n%s", X.shape, y.value_counts().sort_index())

    if len(X) < 1000:
        logger.error("Too few samples (%d). Training aborted.", len(X))
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. 学習
    # ------------------------------------------------------------------
    logger.info("Training LightGBM model (version=%s)...", version)
    model_path = train(X, y, version)

    # ------------------------------------------------------------------
    # 4. 評価 (validation データで RPS を計算)
    # ------------------------------------------------------------------
    from sklearn.model_selection import train_test_split
    import joblib

    _, X_val, _, y_val = train_test_split(X, y, test_size=0.1, random_state=42, stratify=y)
    model = joblib.load(model_path)
    y_pred = model.predict(X_val)
    metrics = evaluate(y_val.values, y_pred)

    logger.info("Evaluation: RPS=%.4f  top1_accuracy=%.4f", metrics["rps"], metrics["top1_accuracy"])

    # ------------------------------------------------------------------
    # 5. model_versions テーブルへ登録
    # ------------------------------------------------------------------
    logger.info("Registering model version in DB...")
    with get_connection() as conn:
        model_id = register_model_version(
            conn,
            version=version,
            trained_at=today.isoformat(),
            data_range_from=data_range_from,
            data_range_to=data_range_to,
            rps_score=metrics["rps"],
            release_url=None,  # GitHub Releases URL は retrain.yml で設定
        )
        conn.commit()

    logger.info("Registered model_versions.id=%d", model_id)
    logger.info("=== retrain done: %s ===", model_path.name)

    # artifacts/ にメタデータを書いておく (workflow で参照するため)
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    (ARTIFACTS_DIR / "latest_model_id.txt").write_text(str(model_id))
    (ARTIFACTS_DIR / "model_version.txt").write_text(version)
    (ARTIFACTS_DIR / "model_metrics.txt").write_text(
        f"version={version}\n"
        f"rps={metrics['rps']:.4f}\n"
        f"top1_accuracy={metrics['top1_accuracy']:.4f}\n"
        f"data_range={data_range_from}~{data_range_to}\n"
        f"samples={len(X)}\n"
    )


if __name__ == "__main__":
    main()
