"""
バックテストエンジン

1 レースごとに:
  1. K ファイル由来の特徴量でモデルを推論
  2. モデル確率 × オッズ（実オッズ or 合成オッズ）で期待値計算
  3. 的中確率 >= prob_threshold の組み合わせに賭け
  4. 実際の着順と照合して P&L を記録

オッズの優先順位:
  race_odds 引数（実オッズ）→ SYNTHETIC_ODDS（合成オッズ）にフォールバック
  実オッズが 60 組未満の場合（ページ取得失敗等）も合成オッズを使用

run_backtest_batch は全レース分の特徴量を一括生成して model.predict を
1 回だけ呼ぶため、run_race を逐次呼ぶより大幅に高速。
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


def _build_race_result(
    race_id: str,
    race_group: pd.DataFrame,
    actual_combo: str,
    ev_results: list[dict],
    alerts: list[dict],
    effective_odds: dict[str, float],
    use_real_odds: bool,
    bet_amount: int,
) -> dict:
    """run_race / run_backtest_batch 共通の結果辞書を組み立てる。"""
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
        "race_date":       str(race_group["race_date"].iloc[0]),
        "stadium_id":      int(race_group["stadium_id"].iloc[0]) if "stadium_id" in race_group.columns else None,
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
    prob_threshold: float,
    bet_amount: int,
    max_bets_per_race: int,
    race_odds: dict[str, float] | None = None,
    ev_threshold: float = 0.0,
) -> dict[str, Any] | None:
    """
    1 レース分のバックテストを実行する。

    Parameters
    ----------
    race_df          : 1 レース 6 艇分のデータ（finish_position 列含む）
    model            : LightGBM Booster
    prob_threshold   : 賭け実行の的中確率閾値（例: 0.05 = 5%）
    bet_amount       : 1 点あたりの賭け金（円）
    max_bets_per_race: 1 レースで賭ける最大点数
    race_odds        : 実オッズ {"1-2-3": 12.5, ...}（None の場合は合成オッズ）
    ev_threshold     : 賭け実行の期待値閾値（例: 1.2）。0.0 で無効（全組み合わせ対象）

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

    # ── 6. 的中確率閾値・EV閾値超えの組み合わせに賭け ──────────
    # ev_results は EV 降順ソート済み
    alerts = [
        r for r in ev_results
        if r["win_probability"] >= prob_threshold
        and r["expected_value"] >= ev_threshold
    ]
    alerts = alerts[:max_bets_per_race]

    return _build_race_result(
        race_id, race_df, actual_combo, ev_results, alerts,
        effective_odds, use_real_odds, bet_amount,
    )


def run_backtest_batch(
    df_test: pd.DataFrame,
    model: Any,
    odds_by_race: dict[str, dict[str, float]],
    prob_threshold: float,
    bet_amount: int,
    max_bets_per_race: int,
    ev_threshold: float = 0.0,
    collect_combos: bool = False,
) -> tuple[list[dict], int] | tuple[list[dict], int, list[dict]]:
    """
    全レースのバックテストをバッチ処理で実行する。

    model.predict を全レース分まとめて 1 回だけ呼ぶため、
    run_race を逐次呼ぶ方式（4000+ 回呼び出し）に比べて大幅に高速。

    Parameters
    ----------
    df_test          : テスト月の全レースデータ（K ファイル由来）
    model            : LightGBM Booster
    odds_by_race     : {race_id: {"1-2-3": 12.5, ...}}（空 dict = 合成オッズ使用）
    prob_threshold   : 賭け実行の的中確率閾値（例: 0.05 = 5%）
    bet_amount       : 1 点あたりの賭け金（円）
    max_bets_per_race: 1 レースで賭ける最大点数
    ev_threshold     : 賭け実行の期待値閾値（例: 1.2）。0.0 で無効
    collect_combos   : True の場合、全組み合わせの生データを combo_records として返す
                       グリッドサーチ用。戻り値が (results, skipped, combo_records) になる。

    Returns
    -------
    collect_combos=False: (results, skipped)
        results : list[dict]  レース結果リスト
        skipped : int         データ不足・DNF 等でスキップしたレース数
    collect_combos=True: (results, skipped, combo_records)
        combo_records: list[dict]  全組み合わせのprob/ev/actual情報（グリッドサーチ用）
    """
    # ── 1. 全データの特徴量を一括生成 ─────────────────────────
    try:
        X_all, _ = build_features_from_history(df_test)
    except Exception as exc:
        logger.error("Batch feature build failed: %s", exc)
        return [], 0

    if X_all.empty:
        logger.warning("No valid rows for batch feature build")
        return [], 0

    # build_features_from_history 内の dropna/filter 後のインデックスを取得
    df_valid = df_test.loc[X_all.index].copy()

    # ── 2. 全艇分を一括予測（model.predict 呼び出し 1 回）────────
    raw_probs = model.predict(X_all)
    # multiclass: shape (N, 6) → クラス 0 (1 着) の確率列
    first_place_probs = raw_probs[:, 0] if raw_probs.ndim == 2 else raw_probs
    df_valid["_fp"] = first_place_probs

    results: list[dict] = []
    combo_records: list[dict] = []
    skipped = 0

    # ── 3. レースごとに後処理 ──────────────────────────────────
    for race_id, race_group in df_valid.groupby("race_id"):
        if len(race_group) != 6:
            logger.debug("Race %s: %d rows (expected 6), skip", race_id, len(race_group))
            skipped += 1
            continue

        actual_combo = get_actual_combo(race_group)
        if actual_combo is None:
            logger.debug("Race %s: actual combo undetermined (DNF/missing), skip", race_id)
            skipped += 1
            continue

        race_odds = odds_by_race.get(str(race_id))
        use_real_odds = race_odds is not None and len(race_odds) >= 60
        effective_odds = race_odds if use_real_odds else SYNTHETIC_ODDS

        # boat_no = 1〜6 の順で first_place_prob を並べる
        # （calc_trifecta_probs は win_probs[boat_no - 1] でアクセスするため）
        fp = race_group.sort_values("boat_no")["_fp"].values

        trifecta_probs = calc_trifecta_probs(fp)
        ev_results = calc_expected_values(trifecta_probs, effective_odds)

        alerts = [
            r for r in ev_results
            if r["win_probability"] >= prob_threshold
            and r["expected_value"] >= ev_threshold
        ]
        alerts = alerts[:max_bets_per_race]

        results.append(_build_race_result(
            str(race_id), race_group, actual_combo, ev_results, alerts,
            effective_odds, use_real_odds, bet_amount,
        ))

        # グリッドサーチ用：全組み合わせの生データを収集
        if collect_combos:
            race_date = str(race_group["race_date"].iloc[0])
            stadium_id = int(race_group["stadium_id"].iloc[0]) if "stadium_id" in race_group.columns else None
            for r in ev_results:
                combo_records.append({
                    "race_id":        str(race_id),
                    "race_date":      race_date,
                    "stadium_id":     stadium_id,
                    "combination":    r["combination"],
                    "win_probability": r["win_probability"],
                    "expected_value": r["expected_value"],
                    "odds":           effective_odds.get(r["combination"], 0.0),
                    "odds_source":    "real" if use_real_odds else "synthetic",
                    "actual_combo":   actual_combo,
                    "is_hit":         r["combination"] == actual_combo,
                    "bet_amount":     bet_amount,
                })

    if collect_combos:
        return results, skipped, combo_records
    return results, skipped
