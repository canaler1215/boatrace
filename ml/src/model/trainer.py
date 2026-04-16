"""
LightGBM 学習スクリプト
各艇の1着確率を推定するマルチクラス分類モデル (6クラス = 着順1〜6)

Session 5 変更点:
  - Isotonic Regression を廃止 → Temperature Scaling（全クラス一括、sum-to-1 維持）
  - val データで負対数尤度最小化により最適温度 T を探索
  - 保存形式: {"booster": lgb.Booster, "temperature": float}
  - 旧形式（lgb.Booster 直接 / calibrators 形式）との後方互換性は predictor.py 側で担保
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from scipy.optimize import minimize_scalar

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


def _softmax_with_temp(logits: np.ndarray, T: float) -> np.ndarray:
    """温度 T でスケールした softmax（sum-to-1 維持）"""
    scaled = logits / T
    shifted = scaled - scaled.max(axis=1, keepdims=True)
    exp_s = np.exp(shifted)
    return exp_s / exp_s.sum(axis=1, keepdims=True)


def _nll(T: float, logits: np.ndarray, y_true: np.ndarray) -> float:
    """負対数尤度（Temperature Scaling 最適化用）"""
    probs = _softmax_with_temp(logits, T)
    return -np.sum(np.log(probs[np.arange(len(y_true)), y_true] + 1e-12)) / len(y_true)


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


def train(X: pd.DataFrame, y: pd.Series, version: str) -> Path:
    """
    モデルを学習して artifacts/model_{version}.pkl に保存する。

    Session 5 変更:
      - 時系列 split（最後の 10% を val）
      - Temperature Scaling: val データで NLL 最小化により最適温度 T を探索
      - 保存形式: {"booster": lgb.Booster, "temperature": float}

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

    # --- Temperature Scaling: val データで最適温度 T を探索 ---
    # raw_score=True でソフトマックス前のロジットを取得
    logits_val = booster.predict(X_val.values, raw_score=True)  # (N_val, 6)
    y_val_arr  = y_val.values.astype(int)

    result = minimize_scalar(
        lambda T: _nll(T, logits_val, y_val_arr),
        bounds=(0.1, 10.0),
        method="bounded",
    )
    T_opt = float(result.x)

    # ECE 比較（1着クラス）
    raw_probs  = booster.predict(X_val.values)              # 温度補正なし (N_val, 6)
    cal_probs  = _softmax_with_temp(logits_val, T_opt)      # 温度補正あり
    true_1st   = (y_val_arr == 0).astype(float)
    ece_before = _ece(raw_probs[:, 0], true_1st)
    ece_after  = _ece(cal_probs[:, 0], true_1st)

    print(f"  [Temperature Scaling] T={T_opt:.4f}  (T>1: 確率を平滑化, T<1: 確率を鋭くする)")
    print(f"  [1着 ECE]  before={ece_before:.5f} → after={ece_after:.5f}")

    # --- 保存: {"booster": ..., "temperature": T} ---
    model_pkg = {"booster": booster, "temperature": T_opt}
    out_path = MODEL_DIR / f"model_{version}.pkl"
    joblib.dump(model_pkg, out_path)
    print(f"Model saved: {out_path}  (best iteration: {booster.best_iteration})")
    return out_path
