"""
推論・期待値計算

Session 6 変更点:
  - predict_win_prob: softmax_calibrators がある場合 → 正規化 → IR → 再正規化（最優先）
  - 後方互換性: temperature（S5）/ calibrators（S3）/ raw（S1） の順にフォールバック
"""
import lightgbm as lgb
import pandas as pd
import numpy as np
import joblib
from itertools import permutations
from pathlib import Path

EV_THRESHOLD = 1.2


def load_model(model_path: Path):
    """
    モデルをロードする。

    Returns
    -------
    dict  {"booster": lgb.Booster, "softmax_calibrators": list}  # Session 6 新形式
          {"booster": lgb.Booster, "temperature": float}          # Session 5 旧形式
          {"booster": lgb.Booster, "calibrators": list|None}      # Session 3 旧形式
          ※ 旧形式（lgb.Booster 直接）の場合も dict 形式に正規化して返す
    """
    obj = joblib.load(model_path)
    if isinstance(obj, dict) and "booster" in obj:
        return obj
    return {"booster": obj, "calibrators": None}


def _softmax_normalize(probs: np.ndarray) -> np.ndarray:
    row_sum = probs.sum(axis=1, keepdims=True)
    return probs / np.maximum(row_sum, 1e-9)


def predict_win_prob(model, X: pd.DataFrame) -> np.ndarray:
    """
    各艇の1着確率を推定 (shape: [n_races, 6])

    優先順位:
      1. softmax_calibrators → 正規化 → IR → 再正規化（Session 6 新形式）
      2. temperature → Temperature Scaling（Session 5 旧形式）
      3. calibrators → Isotonic Regression（Session 3 旧形式、非推奨）
      4. なし → raw softmax 確率をそのまま返す
    """
    booster             = model["booster"]
    softmax_calibrators = model.get("softmax_calibrators", None)
    temperature         = model.get("temperature", None)
    calibrators         = model.get("calibrators", None)

    if softmax_calibrators is not None:
        # Session 6: raw probs → softmax 正規化 → IR → 再正規化
        raw_probs  = booster.predict(X)               # (N, 6)
        normalized = _softmax_normalize(raw_probs)    # sum-to-1 per race
        cal_raw = np.stack(
            [softmax_calibrators[k].predict(normalized[:, k]) for k in range(6)], axis=1
        )
        return _softmax_normalize(cal_raw)            # 再正規化で sum-to-1 を維持

    if temperature is not None:
        # Session 5 legacy: Temperature Scaling
        logits  = booster.predict(X, raw_score=True)
        scaled  = logits / temperature
        shifted = scaled - scaled.max(axis=1, keepdims=True)
        exp_s   = np.exp(shifted)
        return exp_s / exp_s.sum(axis=1, keepdims=True)

    raw_probs = booster.predict(X)

    if calibrators is None:
        return raw_probs

    # Session 3 legacy: 各クラス独立 IR（sum-to-1 非保証）
    calibrated = np.zeros_like(raw_probs)
    for k in range(6):
        calibrated[:, k] = calibrators[k].predict(raw_probs[:, k])
    return calibrated


def calc_trifecta_probs(win_probs: np.ndarray) -> dict[str, float]:
    """
    各艇の1着確率から3連単確率を近似計算
    win_probs: shape (6,) の1着確率

    注意: LightGBM multiclass は艇ごとに独立した softmax を持つため、
    6艇の1着確率の合計が 1.0 にならない場合がある。
    Plackett-Luce 式は合計=1を前提とするため、事前に正規化する。
    """
    total = win_probs.sum()
    if total > 0:
        win_probs = win_probs / total
    result = {}
    boats = list(range(1, 7))
    for combo in permutations(boats, 3):
        p1 = win_probs[combo[0] - 1]
        p2 = win_probs[combo[1] - 1] / max(1 - p1, 1e-9)
        p3 = win_probs[combo[2] - 1] / max(1 - p1 - win_probs[combo[1] - 1], 1e-9)
        prob = p1 * p2 * p3
        key = f"{combo[0]}-{combo[1]}-{combo[2]}"
        result[key] = float(prob)
    return result


def calc_expected_values(
    trifecta_probs: dict[str, float], odds: dict[str, float]
) -> list[dict]:
    """
    期待値 = 的中確率 × オッズ
    EV >= 1.2 のみ alert_flag = True
    """
    results = []
    for combination, prob in trifecta_probs.items():
        odds_val = odds.get(combination, 0)
        ev = prob * odds_val
        results.append(
            {
                "combination": combination,
                "win_probability": prob,
                "expected_value": ev,
                "alert_flag": ev >= EV_THRESHOLD,
            }
        )
    return sorted(results, key=lambda x: x["expected_value"], reverse=True)
