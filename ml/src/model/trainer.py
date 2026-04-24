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

Model Loop 拡張（2026-04-24〜）:
  - keyword-only 引数で lgb_params / num_boost_round / early_stopping_rounds / sample_weight を注入可能に
  - 戻り値を dict 化: {"model_path": Path, "metrics": {...}, "best_iteration": int}
  - 既存呼び出し (train(X, y, version)) は後方互換のため Path を直接返す動作も維持するが、
    新規コードは戻り値を dict として扱うこと。内部では _train_impl に分離。
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


def _merge_lgb_params(overrides: dict | None) -> dict:
    """LGB_PARAMS をベースに overrides をマージ。overrides が None なら LGB_PARAMS をそのまま返す。"""
    merged = dict(LGB_PARAMS)
    if overrides:
        # objective/num_class/metric/n_jobs/verbose はベース側を尊重しつつ上書き可能
        for k, v in overrides.items():
            merged[k] = v
    return merged


def train(
    X: pd.DataFrame,
    y: pd.Series,
    version: str,
    *,
    lgb_params: dict | None = None,
    num_boost_round: int = 1000,
    early_stopping_rounds: int = 50,
    sample_weight: np.ndarray | None = None,
    return_metrics: bool = False,
) -> Path | dict:
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
    lgb_params : dict | None
        LGB_PARAMS にマージする上書きパラメータ。None なら既定のまま。
    num_boost_round : int
        最大ブースティングラウンド数（デフォルト 1000）
    early_stopping_rounds : int
        early stopping の我慢回数（デフォルト 50）
    sample_weight : np.ndarray | None
        学習サンプルの重み（X と同じ行数、train split 側のみが使われる）。
        None なら均等重み。
    return_metrics : bool
        True の場合、dict を返す（model_path / metrics / best_iteration / params）。
        False（デフォルト）の場合、後方互換のため Path のみを返す。

    Returns
    -------
    Path または dict
        return_metrics=False: 保存されたモデルファイルのパス（後方互換）
        return_metrics=True:  {"model_path": Path, "metrics": {...}, "best_iteration": int, "params": dict}
    """
    # --- 時系列 split: 最後の 10% を val ---
    n = len(X)
    n_val = max(int(n * 0.1), 1)
    X_train, X_val = X.iloc[:-n_val], X.iloc[-n_val:]
    y_train, y_val = y.iloc[:-n_val], y.iloc[-n_val:]

    # sample_weight の split（指定があれば）
    w_train = None
    if sample_weight is not None:
        sw = np.asarray(sample_weight)
        if len(sw) != n:
            raise ValueError(
                f"sample_weight length ({len(sw)}) must match X length ({n})"
            )
        w_train = sw[:-n_val]

    print(f"Train: {len(X_train):,} samples  Val: {len(X_val):,} samples  (時系列 split)")
    if w_train is not None:
        print(f"  sample_weight: min={w_train.min():.3f} max={w_train.max():.3f} "
              f"mean={w_train.mean():.3f}")

    dtrain = lgb.Dataset(X_train, label=y_train, weight=w_train)
    dval   = lgb.Dataset(X_val,   label=y_val, reference=dtrain)

    params = _merge_lgb_params(lgb_params)

    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        valid_sets=[dval],
        callbacks=[
            lgb.early_stopping(stopping_rounds=early_stopping_rounds, verbose=True),
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

    if return_metrics:
        return {
            "model_path": out_path,
            "metrics": {
                "ece_rank1_raw": float(ece_before),
                "ece_rank1_calibrated": float(ece_after),
                "n_train": int(len(X_train)),
                "n_val": int(len(X_val)),
            },
            "best_iteration": int(booster.best_iteration or 0),
            "params": params,
        }
    return out_path
