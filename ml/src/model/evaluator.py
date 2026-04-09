"""
RPS（Ranked Probability Score）・精度評価
"""
import numpy as np
import pandas as pd


def ranked_probability_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    RPS を計算（値が小さいほど良い）
    y_true: (n,) 正解クラス (0-indexed)
    y_pred: (n, 6) 予測確率
    """
    n, k = y_pred.shape
    total = 0.0
    for i in range(n):
        cum_pred = np.cumsum(y_pred[i])
        cum_true = np.zeros(k)
        cum_true[int(y_true[i]):] = 1.0
        total += np.sum((cum_pred - cum_true) ** 2) / (k - 1)
    return total / n


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    rps = ranked_probability_score(y_true, y_pred)
    top1_acc = np.mean(np.argmax(y_pred, axis=1) == y_true)
    return {"rps": rps, "top1_accuracy": top1_acc}
