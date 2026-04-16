"""
推論・期待値計算

Session 3 変更点:
  - load_model: 新形式 dict {"booster": ..., "calibrators": [...]} に対応
  - predict_win_prob: キャリブレーター適用（旧形式モデルは calibrators=None でスキップ）
  - 後方互換性: 旧形式（lgb.Booster 直接）も動作する
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
    dict  {"booster": lgb.Booster, "calibrators": list[IsotonicRegression] or None}
          ※ 旧形式（lgb.Booster 直接）の場合も dict 形式に正規化して返す
    """
    obj = joblib.load(model_path)
    if isinstance(obj, dict) and "booster" in obj:
        return obj  # 新形式: {"booster": ..., "calibrators": [...]}
    # 旧形式: lgb.Booster そのもの
    return {"booster": obj, "calibrators": None}


def predict_win_prob(model, X: pd.DataFrame) -> np.ndarray:
    """
    各艇の1着確率を推定 (shape: [n_races, 6])

    キャリブレーターが存在する場合は補正済み確率を返す。
    キャリブレーターは各クラスに独立した Isotonic Regression。
    """
    booster = model["booster"]
    calibrators = model.get("calibrators", None)

    raw_probs = booster.predict(X)  # (N, 6)

    if calibrators is None:
        return raw_probs

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
