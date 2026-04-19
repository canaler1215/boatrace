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
from model.predictor import predict_win_prob, calc_trifecta_probs, calc_trio_probs, calc_expected_values
from backtest.odds_simulator import SYNTHETIC_ODDS, SYNTHETIC_TRIO_ODDS

logger = logging.getLogger(__name__)


def calc_kelly_bet(
    win_prob: float,
    odds: float,
    bankroll: float,
    kelly_fraction: float,
    min_bet: int = 100,
    max_bet: int | None = None,
) -> int:
    """
    フラクショナル Kelly 基準によるベット額を計算する。

    Kelly fraction: f = (p * odds - 1) / (odds - 1)
    Bet amount    : bankroll × kelly_fraction × f (最小 min_bet、最大 max_bet、100円単位)

    Parameters
    ----------
    win_prob       : 的中確率（モデル推定）
    odds           : 3連単オッズ（例: 100.0 → 100倍）
    bankroll       : 現在の資金（円）
    kelly_fraction : ケリー分率（1.0=フルケリー、0.25=1/4ケリー推奨）
    min_bet        : 最小ベット額（円）
    max_bet        : 最大ベット額（円）。None で上限なし

    Returns
    -------
    int : ベット額（100円単位）。EV <= 1（負の期待値）の場合は 0 を返す
    """
    if odds <= 1.0:
        return 0
    ev = win_prob * odds
    if ev <= 1.0:  # 負の期待値 → ベットしない
        return 0
    kelly_f = (ev - 1.0) / (odds - 1.0)
    raw_amount = bankroll * kelly_fraction * kelly_f
    # 100円単位に丸め
    amount = max(min_bet, int(raw_amount / 100) * 100)
    if max_bet is not None:
        amount = min(amount, max_bet)
    return amount


def _is_trio_hit(actual_combo: str | None, trio_combo: str) -> bool:
    if actual_combo is None:
        return False
    return frozenset(actual_combo.split("-")) == frozenset(trio_combo.split("-"))


def _build_race_result(
    race_id: str,
    race_group: pd.DataFrame,
    actual_combo: str,
    ev_results: list[dict],
    alerts: list[dict],
    effective_odds: dict[str, float],
    use_real_odds: bool,
    bet_amount: int,
    bet_amounts: dict[str, int] | None = None,
    bet_type: str = "trifecta",
) -> dict:
    """run_race / run_backtest_batch 共通の結果辞書を組み立てる。

    Parameters
    ----------
    bet_amounts : Kelly基準使用時の組み合わせ別ベット額 {"1-2-3": 300, ...}
                  None の場合は bet_amount を一律適用
    """
    if bet_amounts is None:
        amount_wagered = len(alerts) * bet_amount
    else:
        amount_wagered = sum(bet_amounts.get(b["combination"], bet_amount) for b in alerts)

    payout_received = 0.0
    matched = False
    matched_combo: str | None = None
    matched_ev = 0.0
    matched_odds = 0.0

    for bet in alerts:
        combo_hit = (
            _is_trio_hit(actual_combo, bet["combination"])
            if bet_type == "trio"
            else bet["combination"] == actual_combo
        )
        if combo_hit:
            matched_odds = effective_odds.get(bet["combination"], SYNTHETIC_ODDS.get(bet["combination"], 0.0))
            actual_bet = (bet_amounts or {}).get(bet["combination"], bet_amount)
            payout_received = matched_odds * actual_bet
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
        "bet_type":        bet_type,
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
    kelly_fraction: float = 0.0,
    kelly_bankroll: float = 100_000.0,
    exclude_courses: list[int] | None = None,
    min_odds: float | None = None,
    exclude_stadiums: list[int] | None = None,
    bet_type: str = "trifecta",
) -> dict[str, Any] | None:
    """
    1 レース分のバックテストを実行する。

    Parameters
    ----------
    race_df          : 1 レース 6 艇分のデータ（finish_position 列含む）
    model            : LightGBM Booster
    prob_threshold   : 賭け実行の的中確率閾値（例: 0.05 = 5%）
    bet_amount       : 1 点あたりの賭け金（円）。kelly_fraction > 0 の場合は最小ベット額として使用
    max_bets_per_race: 1 レースで賭ける最大点数
    race_odds        : 実オッズ {"1-2-3": 12.5, ...}（None の場合は合成オッズ）
    ev_threshold     : 賭け実行の期待値閾値（例: 1.2）。0.0 で無効（全組み合わせ対象）
    kelly_fraction   : Kelly 分率（0.0 = 固定ベット, 0.25 = 1/4 Kelly 推奨）
    kelly_bankroll   : Kelly 計算用の資金額（円）
    exclude_courses  : 除外する1着艇番（コース）リスト（例: [2, 4, 5]）
    min_odds         : 購入するオッズの下限（例: 100.0 → 100倍未満は除外）
    exclude_stadiums : 除外する場ID リスト（例: [11] → びわこ除外）
    bet_type         : "trifecta"（3連単）or "trio"（3連複）

    Returns
    -------
    dict | None
        レース結果辞書。スキップ（データ不足・DNF・除外場等）の場合は None。
    """
    # ── 0. 場フィルタ（レース単位でスキップ）──────────────────
    if exclude_stadiums and "stadium_id" in race_df.columns:
        sid = int(race_df["stadium_id"].iloc[0])
        if sid in exclude_stadiums:
            return None

    # 有効な実オッズかどうか判定
    # 3連単: 120組のうち60組以上、3連複: 20組のうち10組以上
    min_real_odds_count = 10 if bet_type == "trio" else 60
    use_real_odds = race_odds is not None and len(race_odds) >= min_real_odds_count
    fallback_odds = SYNTHETIC_TRIO_ODDS if bet_type == "trio" else SYNTHETIC_ODDS
    effective_odds = race_odds if use_real_odds else fallback_odds
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

    # ── 3. 1 着確率予測（キャリブレーション補正済み）────────────
    raw_probs = predict_win_prob(model, X)
    # multiclass: shape (6, 6) → クラス 0 (1 着) の確率列を取得
    first_place_probs = raw_probs[:, 0] if raw_probs.ndim == 2 else raw_probs

    # ── 4. 確率計算（3連単 or 3連複）─────────────────────────
    if bet_type == "trio":
        combo_probs = calc_trio_probs(first_place_probs)
    else:
        combo_probs = calc_trifecta_probs(first_place_probs)

    # ── 5. 期待値計算 ─────────────────────────────────────
    ev_results = calc_expected_values(combo_probs, effective_odds)

    # ── 6. 的中確率閾値・EV閾値・コース/オッズフィルタで絞り込み ──
    # ev_results は EV 降順ソート済み
    alerts = [
        r for r in ev_results
        if r["win_probability"] >= prob_threshold
        and r["expected_value"] >= ev_threshold
    ]
    # exclude_coursesは3連単のみ（3連複はパイロット後に検討）
    if exclude_courses and bet_type == "trifecta":
        alerts = [r for r in alerts if int(r["combination"].split("-")[0]) not in exclude_courses]
    if min_odds is not None:
        alerts = [r for r in alerts if effective_odds.get(r["combination"], 0.0) >= min_odds]
    alerts = alerts[:max_bets_per_race]

    # ── 7. Kelly 基準によるベット額計算 ───────────────────────
    bet_amounts: dict[str, int] | None = None
    if kelly_fraction > 0.0:
        bet_amounts = {
            r["combination"]: calc_kelly_bet(
                win_prob=r["win_probability"],
                odds=effective_odds.get(r["combination"], 0.0),
                bankroll=kelly_bankroll,
                kelly_fraction=kelly_fraction,
                min_bet=bet_amount,
            )
            for r in alerts
        }
        # ベット額が 0 になった組み合わせ（EV<=1）を除外
        alerts = [r for r in alerts if bet_amounts.get(r["combination"], 0) > 0]

    return _build_race_result(
        race_id, race_df, actual_combo, ev_results, alerts,
        effective_odds, use_real_odds, bet_amount, bet_amounts,
        bet_type=bet_type,
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
    kelly_fraction: float = 0.0,
    kelly_bankroll: float = 100_000.0,
    exclude_courses: list[int] | None = None,
    min_odds: float | None = None,
    exclude_stadiums: list[int] | None = None,
    bet_type: str = "trifecta",
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
    bet_amount       : 1 点あたりの賭け金（円）。kelly_fraction > 0 の場合は最小ベット額
    max_bets_per_race: 1 レースで賭ける最大点数
    ev_threshold     : 賭け実行の期待値閾値（例: 1.2）。0.0 で無効
    collect_combos   : True の場合、全組み合わせの生データを combo_records として返す
                       グリッドサーチ用。戻り値が (results, skipped, combo_records) になる。
    kelly_fraction   : Kelly 分率（0.0 = 固定ベット, 0.25 = 1/4 Kelly 推奨）
    kelly_bankroll   : Kelly 計算用の資金額（円）
    exclude_courses  : 除外する1着艇番（コース）リスト（例: [2, 4, 5]）
    min_odds         : 購入するオッズの下限（例: 100.0 → 100倍未満は除外）
    exclude_stadiums : 除外する場ID リスト（例: [11] → びわこ除外）
    bet_type         : "trifecta"（3連単）or "trio"（3連複）

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

    # ── 2. 全艇分を一括予測（キャリブレーション補正済み、1 回のみ）──
    raw_probs = predict_win_prob(model, X_all)
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

        # 場フィルタ（除外場はスキップ）
        if exclude_stadiums and "stadium_id" in race_group.columns:
            sid = int(race_group["stadium_id"].iloc[0])
            if sid in exclude_stadiums:
                skipped += 1
                continue

        actual_combo = get_actual_combo(race_group)
        if actual_combo is None:
            logger.debug("Race %s: actual combo undetermined (DNF/missing), skip", race_id)
            skipped += 1
            continue

        race_odds = odds_by_race.get(str(race_id))
        min_real_odds_count = 10 if bet_type == "trio" else 60
        use_real_odds = race_odds is not None and len(race_odds) >= min_real_odds_count
        fallback_odds = SYNTHETIC_TRIO_ODDS if bet_type == "trio" else SYNTHETIC_ODDS
        effective_odds = race_odds if use_real_odds else fallback_odds

        # boat_no = 1〜6 の順で first_place_prob を並べる
        fp = race_group.sort_values("boat_no")["_fp"].values

        if bet_type == "trio":
            combo_probs = calc_trio_probs(fp)
        else:
            combo_probs = calc_trifecta_probs(fp)
        ev_results = calc_expected_values(combo_probs, effective_odds)

        alerts = [
            r for r in ev_results
            if r["win_probability"] >= prob_threshold
            and r["expected_value"] >= ev_threshold
        ]
        # exclude_coursesは3連単のみ（3連複はパイロット後に検討）
        if exclude_courses and bet_type == "trifecta":
            alerts = [r for r in alerts if int(r["combination"].split("-")[0]) not in exclude_courses]
        if min_odds is not None:
            alerts = [r for r in alerts if effective_odds.get(r["combination"], 0.0) >= min_odds]
        alerts = alerts[:max_bets_per_race]

        # Kelly 基準によるベット額計算
        race_bet_amounts: dict[str, int] | None = None
        if kelly_fraction > 0.0:
            race_bet_amounts = {
                r["combination"]: calc_kelly_bet(
                    win_prob=r["win_probability"],
                    odds=effective_odds.get(r["combination"], 0.0),
                    bankroll=kelly_bankroll,
                    kelly_fraction=kelly_fraction,
                    min_bet=bet_amount,
                )
                for r in alerts
            }
            alerts = [r for r in alerts if race_bet_amounts.get(r["combination"], 0) > 0]

        results.append(_build_race_result(
            str(race_id), race_group, actual_combo, ev_results, alerts,
            effective_odds, use_real_odds, bet_amount, race_bet_amounts,
            bet_type=bet_type,
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
                    "is_hit":         (
                        _is_trio_hit(actual_combo, r["combination"])
                        if bet_type == "trio"
                        else r["combination"] == actual_combo
                    ),
                    "bet_amount":     bet_amount,
                    "bet_type":       bet_type,
                })

    if collect_combos:
        return results, skipped, combo_records
    return results, skipped
