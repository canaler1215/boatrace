"""
推論・期待値計算
"""
import lightgbm as lgb
import pandas as pd
import numpy as np
import joblib
from itertools import permutations
from pathlib import Path

EV_THRESHOLD = 1.2


def load_model(model_path: Path) -> lgb.Booster:
    return joblib.load(model_path)


def predict_win_prob(model: lgb.Booster, X: pd.DataFrame) -> np.ndarray:
    """各艇の1着確率を推定 (shape: [n_races, 6])"""
    return model.predict(X)


def calc_trifecta_probs(win_probs: np.ndarray) -> dict[str, float]:
    """
    各艇の1着確率から3連単確率を近似計算
    win_probs: shape (6,) の1着確率
    """
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
