"""
LightGBM 学習スクリプト
各艇の1着確率を推定するマルチクラス分類モデル (6クラス = 着順1〜6)

Session 6 変更点:
  - Temperature Scaling を廃止 → ソフトマックス正規化 + Isotonic Regression（per-bin 補正）
  - val データで: raw probs → softmax 正規化 → per-class IR 学習 → 再正規化
  - 保存形式: {"booster": lgb.Booster, "softmax_calibrators": list[IsotonicRegression]}
  - sum-to-1 を保持したまま構造的なビン別バイアスを補正（Session 3 の課題を解決）

Session 5 変更点（廃止済み）:
  - Temperature Scaling: T≈1.0 に収束しグローバルスカラーでは解決不可能と確定
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


def _softmax_normalize(probs: np.ndarray) -> np.ndarray:
    """行ごとに sum-to-1 正規化（各レースの6艇確率を合計1に揃える）"""
    row_sum = probs.sum(axis=1, keepdims=True)
    return probs / np.maximum(row_sum, 1e-9)


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

    Session 6 変更:
      - 時系列 split（最後の 10% を val）
      - ソフトマックス正規化 + Isotonic Regression: raw probs → 正規化 → per-class IR → 再正規化
      - 保存形式: {"booster": lgb.Booster, "softmax_calibrators": list[IsotonicRegression]}

    Parameters
    ----------
    X : pd.DataFrame  特徴量 (FEATURE_COLUMNS)
    y : pd.Series     ラベル  着順 - 1  (0=1着, 1=2着, ..., 5=6着)
    version : str     バージョン文字列 (例: "202504")

    Returns
    -------
    Path  保存されたモデルファイルのパス
    """
    # --- 時系列 split: 最後の 10% を val ---
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

    # --- Session 6: ソフトマックス正規化 → Isotonic Regression ---
    raw_probs = booster.predict(X_val.values)       # (N_val, 6)
    y_val_arr = y_val.values.astype(int)

    # Step 1: レース内 sum-to-1 正規化
    normalized = _softmax_normalize(raw_probs)      # (N_val, 6)

    # Step 2: per-class Isotonic Regression（ビン別構造バイアスを補正）
    softmax_calibrators = []
    for k in range(6):
        true_k = (y_val_arr == k).astype(float)
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(normalized[:, k], true_k)
        softmax_calibrators.append(ir)

    # ECE 比較（1着クラス）
    true_1st   = (y_val_arr == 0).astype(float)
    ece_before = _ece(raw_probs[:, 0], true_1st)

    # calibrate → 再正規化 → 1着 ECE 計測
    cal_raw = np.stack(
        [softmax_calibrators[k].predict(normalized[:, k]) for k in range(6)], axis=1
    )
    cal_probs = _softmax_normalize(cal_raw)
    ece_after = _ece(cal_probs[:, 0], true_1st)

    print(f"  [Softmax + Isotonic Regression]")
    print(f"  [1着 ECE]  before={ece_before:.5f} → after={ece_after:.5f}")

    # --- 保存: {"booster": ..., "softmax_calibrators": [...]} ---
    model_pkg = {"booster": booster, "softmax_calibrators": softmax_calibrators}
    out_path = MODEL_DIR / f"model_{version}.pkl"
    joblib.dump(model_pkg, out_path)
    print(f"Model saved: {out_path}  (best iteration: {booster.best_iteration})")
    return out_path
