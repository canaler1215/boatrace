"""
推論・期待値計算

Session 6 変更点:
  - predict_win_prob: softmax_calibrators がある場合 → 正規化 → IR → 再正規化（最優先）
  - 後方互換性: temperature（S5）/ calibrators（S3）/ raw（S1） の順にフォールバック

タスク 6-10-d 拡張（2026-04-25〜）:
  - booster.params の objective を読み、lambdarank / rank_xendcg なら
    race-level softmax で (N,) → 1 着確率 → (N, 6) にブロードキャスト
  - 引数 race_ids が必要（None だとエラー）。multiclass モデルでは race_ids 無視
"""
import lightgbm as lgb
import pandas as pd
import numpy as np
import joblib
from itertools import permutations, combinations
from pathlib import Path

EV_THRESHOLD = 1.2

RANKING_OBJECTIVES = {"lambdarank", "rank_xendcg"}


def _race_softmax_pred(score: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    """レース単位で score を softmax 正規化して 1 着確率（per-row）を返す。"""
    out = np.zeros_like(score, dtype=float)
    df = pd.DataFrame({"race_id": race_ids, "score": score})
    for _, idx in df.groupby("race_id", sort=False).groups.items():
        s = score[idx]
        s = s - s.max()
        e = np.exp(s)
        total = e.sum()
        out[idx] = (e / total) if total > 0 else (1.0 / len(s))
    return out


def _broadcast_first_to_six(p_first: np.ndarray) -> np.ndarray:
    """1 着確率 (N,) を (N, 6) に展開（trainer._broadcast_first_to_six と同実装）。"""
    n = len(p_first)
    out = np.zeros((n, 6), dtype=float)
    out[:, 0] = p_first
    rest = np.clip(1.0 - p_first, 0.0, 1.0) / 5.0
    out[:, 1:] = rest[:, None]
    return out


def _booster_objective(booster: "lgb.Booster") -> str:
    """booster.params から objective を取得。取れなければ multiclass を仮定。"""
    try:
        obj = (booster.params or {}).get("objective", "multiclass")
    except Exception:
        obj = "multiclass"
    return obj or "multiclass"


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


def predict_win_prob(
    model,
    X: pd.DataFrame,
    race_ids: pd.Series | np.ndarray | None = None,
) -> np.ndarray:
    """
    各艇の1着確率を推定 (shape: [n_races, 6])

    優先順位:
      1. softmax_calibrators → 正規化 → IR → 再正規化（Session 6 新形式）
         - lambdarank モデルの場合は booster.predict (N,) → race-level softmax →
           (N, 6) ブロードキャスト → 上記パス（race_ids 引数が必須）
      2. temperature → Temperature Scaling（Session 5 旧形式）
      3. calibrators → Isotonic Regression（Session 3 旧形式、非推奨）
      4. なし → raw softmax 確率をそのまま返す

    Parameters
    ----------
    model : dict   load_model の戻り値
    X : pd.DataFrame  特徴量
    race_ids : pd.Series | np.ndarray | None
        ranking 系（lambdarank / rank_xendcg）モデルでは必須。
        multiclass モデルでは無視される。長さは X と一致すること。
    """
    booster             = model["booster"]
    softmax_calibrators = model.get("softmax_calibrators", None)
    temperature         = model.get("temperature", None)
    calibrators         = model.get("calibrators", None)

    if softmax_calibrators is not None:
        # Session 6: raw probs → softmax 正規化 → IR → 再正規化
        objective = _booster_objective(booster)
        if objective in RANKING_OBJECTIVES:
            if race_ids is None:
                raise ValueError(
                    f"ranking model (objective={objective}) requires race_ids "
                    f"argument to predict_win_prob"
                )
            rid_arr = np.asarray(
                race_ids.values if hasattr(race_ids, "values") else race_ids
            )
            if len(rid_arr) != len(X):
                raise ValueError(
                    f"race_ids length ({len(rid_arr)}) must match X length ({len(X)})"
                )
            scores = booster.predict(X)               # (N,)
            p_first = _race_softmax_pred(scores, rid_arr)
            raw_probs = _broadcast_first_to_six(p_first)
        else:
            raw_probs = booster.predict(X)            # (N, 6)
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


def calc_trio_probs(win_probs: np.ndarray) -> dict[str, float]:
    """3連複確率をPlackett-Luceで計算。キーはソート済み艇番文字列 "1-2-3"。"""
    p = win_probs / max(win_probs.sum(), 1e-9)
    boats = list(range(1, 7))
    result = {}
    for combo in combinations(boats, 3):
        key = "-".join(map(str, combo))
        prob = 0.0
        for perm in permutations(combo):
            a, b, c = perm[0] - 1, perm[1] - 1, perm[2] - 1
            denom_b = 1.0 - p[a]
            denom_c = 1.0 - p[a] - p[b]
            if denom_b > 0 and denom_c > 0:
                prob += p[a] * (p[b] / denom_b) * (p[c] / denom_c)
        result[key] = float(prob)
    return result  # 20エントリ、合計≒1.0


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
