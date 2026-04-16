"""
LightGBM 学習スクリプト
各艇の1着確率を推定するマルチクラス分類モデル (6クラス = 着順1〜6)

Session 3 変更点:
  - random split → 時系列 split（P7修正）
  - Isotonic Regression によるキャリブレーター学習・同梱保存
  - 保存形式: {"booster": lgb.Booster, "calibrators": [IsotonicRegression x6]}
  - 旧形式（lgb.Booster 直接）との後方互換性は predictor.py 側で担保
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from sklearn.isotonic import IsotonicRegression

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
    """
    モデルを学習して artifacts/model_{version}.pkl に保存する。

    Session 3 変更:
      - 時系列 split（最後の 10% を val）に変更（P7修正）
      - val データで各クラスの Isotonic Regression calibrator を学習
      - 保存形式: {"booster": lgb.Booster, "calibrators": list[IsotonicRegression]}

    Parameters
    ----------
    X : pd.DataFrame  特徴量 (FEATURE_COLUMNS)
    y : pd.Series     ラベル  着順 - 1  (0=1着, 1=2着, ..., 5=6着)
    version : str     バージョン文字列 (例: "202504")

    Returns
    -------
    Path  保存されたモデルファイルのパス
    """
    # --- 時系列 split: 最後の 10% を val（ランダム split を廃止） ---
    n = len(X)
    n_val = max(int(n * 0.1), 1)
    X_train, X_val = X.iloc[:-n_val], X.iloc[-n_val:]
    y_train, y_val = y.iloc[:-n_val], y.iloc[-n_val:]

    print(f"Train: {len(X_train):,} samples  Val: {len(X_val):,} samples  (時系列 split)")

    dtrain = lgb.Dataset(X_train, label=y_train)
    dval   = lgb.Dataset(X_val,   label=y_val, reference=dtrain)

    booster = lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=1000,
        valid_sets=[dval],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=True),
            lgb.log_evaluation(period=100),
        ],
    )

    # --- キャリブレーター学習（val データで各クラス独立に Isotonic Regression） ---
    raw_val_probs = booster.predict(X_val.values)  # (N_val, 6)
    calibrators: list[IsotonicRegression] = []
    ece_before: list[float] = []
    ece_after: list[float] = []

    for k in range(6):
        prob_k = raw_val_probs[:, k]
        true_k = (y_val.values == k).astype(float)

        # ECE before（10ビン）
        ece_before.append(_ece(prob_k, true_k))

        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(prob_k, true_k)

        cal_prob_k = ir.predict(prob_k)
        ece_after.append(_ece(cal_prob_k, true_k))
        calibrators.append(ir)

    print("  [Calibration ECE: before → after]")
    for k in range(6):
        print(f"    {k+1}着: {ece_before[k]:.4f} → {ece_after[k]:.4f}")

    # --- 保存: {"booster": ..., "calibrators": [...]} ---
    model_pkg = {"booster": booster, "calibrators": calibrators}
    out_path = MODEL_DIR / f"model_{version}.pkl"
    joblib.dump(model_pkg, out_path)
    print(f"Model saved: {out_path}  (best iteration: {booster.best_iteration})")
    return out_path


def _ece(prob: np.ndarray, true_bin: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error（簡易計算）"""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    n = len(prob)
    if n == 0:
        return float("nan")
    ece = 0.0
    for i in range(n_bins):
        mask = (prob >= bins[i]) & (prob < bins[i + 1])
        if mask.sum() == 0:
            continue
        ece += mask.sum() / n * abs(prob[mask].mean() - true_bin[mask].mean())
    return ece
