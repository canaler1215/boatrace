"""
LightGBM 学習スクリプト
各艇の1着確率を推定するマルチクラス分類モデル
"""
import lightgbm as lgb
import pandas as pd
import numpy as np
from pathlib import Path
import joblib


MODEL_DIR = Path(__file__).parents[3] / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)

LGB_PARAMS = {
    "objective": "multiclass",
    "num_class": 6,
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
    "n_jobs": -1,
}


def train(X: pd.DataFrame, y: pd.Series, version: str) -> Path:
    """モデルを学習して artifacts/ に保存する"""
    dtrain = lgb.Dataset(X, label=y)
    model = lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=1000,
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)],
    )
    out_path = MODEL_DIR / f"model_{version}.pkl"
    joblib.dump(model, out_path)
    print(f"Model saved: {out_path}")
    return out_path
