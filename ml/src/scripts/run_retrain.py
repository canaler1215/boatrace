"""
retrain.yml から呼び出されるモデル再学習スクリプト
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))

from collector.db_writer import get_connection
from model.trainer import train
from model.evaluator import evaluate
from features.feature_builder import build_features, FEATURE_COLUMNS
import pandas as pd
import os
from datetime import date


def main():
    version = date.today().strftime("%Y%m")
    print(f"Retraining model version {version}...")

    with get_connection() as conn:
        # TODO: 全学習データをDBから取得して学習
        # df = pd.read_sql("SELECT ...", conn)
        # X = build_features(df)
        # y = df["finish_position_encoded"]
        # model_path = train(X, y, version)
        pass

    print(f"Retrain complete: {version}")


if __name__ == "__main__":
    main()
