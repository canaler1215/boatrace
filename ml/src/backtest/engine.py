"""
バックテストエンジン

1 レースごとに:
  1. K ファイル由来の特徴量でモデルを推論
  2. モデル確率 × オッズ（実オッズ or 合成オッズ）で期待値計算
  3. EV >= threshold の組み合わせに賭け
  4. 実際の着順と照合して P&L を記録

オッズの優先順位:
  race_odds 引数（実オッズ）→ SYNTHETIC_ODDS（合成オッズ）にフォールバック
  実オッズが 60 組未満の場合（ページ取得失敗等）も合成オッズを使用
"""
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from features.feature_builder import build_features_from_history
from model.predictor import calc_trifecta_probs, calc_expected_values
from backtest.odds_simulator import SYNTHETIC_ODDS

logger = logging.getLogger(__name__)


def get_actual_combo(race_df: pd.DataFrame) -> str | None:
    """
    レース結果から 3 連単の実際の組み合わせ文字列を返す。

    Returns
    -------
    str | None
        "1-2-3" 形式。上位 3 艇が確定しない場合は None。
    """
    valid = race_df[race_df["finish_position"].between(1, 3)].copy()
    if len(valid) < 3:
        return None
    top3 = valid.nsmallest(3, "finish_position")
    return "-".join(str(int(b)) for b in top3["boat_no"])


def run_race(
    race_df: pd.DataFrame,
    model: Any,
    ev_threshold: float,
    bet_amount: int,
    max_bets_per_race: int,
    race_odds: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """
    1 レース分のバックテストを実行する。

    Parameters
    ----------
    race_df          : 1 レース 6 艇分のデータ（finish_position 列含む）
    model            : LightGBM Booster
    ev_threshold     : 賭け実行の EV 閾値（例: 1.2）
    bet_amount       : 1 点あたりの賭け金（円）
    max_bets_per_race: 1 レースで賭ける最大点数
    race_odds        : 実オッズ {"1-2-3": 12.5, ...}（None の場合は合成オッズ）

    Returns
    -------
    dict | None
        レース結果辞書。スキップ（データ不足・DNF 等）の場合は None。
    """
    # 有効な実オッズかどうか判定（120 組のうち 60 組以上あれば使用）
    use_real_odds = race_odds is not None and len(race_odds) >= 60
    effective_odds = race_odds if use_real_odds else SYNTHETIC_ODDS
    race_id = race_df["race_id"].iloc[0]

    # ── 1. 実際の着順取得 ──────────────────────────────────
    actual_combo = get_actual_combo(race_df)
    if actual_combo is None:
        logger.debug("Race %s: actual combo undetermined (DNF/missing), skip", race_id)
        return None

    # ── 2. 特徴量生成 ─────────────────────────────────────
    # build_features_from_history は finish_position が 1-6 の行のみ使用する。
    # 6 艇全員が正常完走していれば 6 行を返す。
    try:
        X, _ = build_features_from_history(race_df)
    except Exception as exc:
        logger.debug("Race %s: feature build failed: %s", race_id, exc)
        return None

    if len(X) != 6:
        logger.debug("Race %s: %d feature rows (expected 6), skip", race_id, len(X))
        return None

    # ── 3. 1 着確率予測 ───────────────────────────────────
    raw_probs = model.predict(X)
    # multiclass: shape (6, 6) → クラス 0 (1 着) の確率列を取得
    first_place_probs = raw_probs[:, 0] if raw_probs.ndim == 2 else raw_probs

    # ── 4. 3 連単確率計算 ─────────────────────────────────
    trifecta_probs = calc_trifecta_probs(first_place_probs)

    # ── 5. 期待値計算 ─────────────────────────────────────
    ev_results = calc_expected_values(trifecta_probs, effective_odds)

    # ── 6. EV 閾値超えの組み合わせに賭け ──────────────────
    # ev_results は EV 降順ソート済み
    alerts = [r for r in ev_results if r["expected_value"] >= ev_threshold]
    alerts = alerts[:max_bets_per_race]

    amount_wagered = len(alerts) * bet_amount
    payout_received = 0.0
    matched = False
    matched_combo: str | None = None
    matched_ev = 0.0
    matched_odds = 0.0

    for bet in alerts:
        if bet["combination"] == actual_combo:
            matched_odds = effective_odds.get(actual_combo, SYNTHETIC_ODDS.get(actual_combo, 0.0))
            payout_received = matched_odds * bet_amount
            matched = True
            matched_combo = bet["combination"]
            matched_ev = bet["expected_value"]
            break

    return {
        "race_id":         race_id,
        "race_date":       str(race_df["race_date"].iloc[0]),
        "stadium_id":      int(race_df["stadium_id"].iloc[0]) if "stadium_id" in race_df.columns else None,
        "actual_combo":    actual_combo,
        "bets_placed":     len(alerts),
        "amount_wagered":  amount_wagered,
        "payout_received": payout_received,
        "profit":          payout_received - amount_wagered,
        "matched":         matched,
        "matched_combo":   matched_combo,
        "matched_ev":      matched_ev,
        "matched_odds":    matched_odds,
        "top_ev":          ev_results[0]["expected_value"] if ev_results else 0.0,
        "top_combo":       ev_results[0]["combination"] if ev_results else None,
        "top_prob":        ev_results[0]["win_probability"] if ev_results else 0.0,
        "n_alerts":        len(alerts),
        "odds_source":     "real" if use_real_odds else "synthetic",
    }
