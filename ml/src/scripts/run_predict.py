"""
predict.yml から呼び出される推論・期待値計算スクリプト

処理フロー:
  1. ml/artifacts/model_latest.pkl をロード
  2. 本日の未予測・未終了レースを取得
  3. 各レースに対して:
     a. 出走表 + 選手情報を取得
     b. レースメタ情報（場・潮位）を取得
     c. 特徴量生成
     d. LightGBM で各艇の1着確率を推定
     e. 3連単確率を近似計算
     f. オッズを取得して期待値を計算
     g. predictions テーブルに upsert（EV >= 1.2 で alert_flag=true）
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from datetime import datetime, timezone, timedelta

import pandas as pd

from collector.db_writer import get_connection, upsert_prediction
from features.feature_builder import build_features
from model.predictor import (
    calc_expected_values,
    calc_trifecta_probs,
    load_model,
    predict_win_prob,
)
from notifier import notify_bet_candidates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parents[3] / "artifacts" / "model_latest.pkl"


# ---------------------------------------------------------------------------
# DB クエリ関数
# ---------------------------------------------------------------------------

def fetch_race_entries(conn, race_id: str) -> pd.DataFrame:
    """出走表 + 選手勝率・級別を取得"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                re.race_id,
                re.boat_no,
                COALESCE(re.motor_win_rate, 0)   AS motor_win_rate,
                COALESCE(re.boat_win_rate,  0)   AS boat_win_rate,
                COALESCE(re.exhibition_time, 0)  AS exhibition_time,
                COALESCE(re.start_timing,   0)   AS start_timing,
                COALESCE(r.win_rate,        0)   AS racer_win_rate,
                COALESCE(r.grade,        'B1')   AS racer_grade
            FROM race_entries re
            LEFT JOIN racers r ON re.racer_id = r.id
            WHERE re.race_id = %s
            ORDER BY re.boat_no
            """,
            (race_id,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def fetch_race_meta(conn, race_id: str) -> pd.DataFrame:
    """レースメタ情報（場ID・潮位）を取得。潮位は当日最新スナップショット。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.id                              AS race_id,
                r.stadium_id,
                r.race_no,
                COALESCE(t.tidal_level, 0)        AS tidal_level,
                COALESCE(t.tidal_type, '')        AS tidal_type
            FROM races r
            LEFT JOIN tidal_data t
              ON  t.stadium_id = r.stadium_id
              AND DATE(t.recorded_at) = r.race_date::date
              AND t.recorded_at = (
                    SELECT MAX(t2.recorded_at)
                    FROM tidal_data t2
                    WHERE t2.stadium_id = r.stadium_id
                      AND DATE(t2.recorded_at) = r.race_date::date
                  )
            WHERE r.id = %s
            """,
            (race_id,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def fetch_odds(conn, race_id: str) -> dict[str, float]:
    """3連単オッズを取得（combination ごとに最新スナップショット）"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (combination)
                combination,
                odds_value
            FROM odds
            WHERE race_id = %s
            ORDER BY combination, snapshot_at DESC
            """,
            (race_id,),
        )
        rows = cur.fetchall()
    return {row[0]: float(row[1]) for row in rows}


def fetch_active_model_version_id(conn) -> int | None:
    """is_active=true のモデルバージョン ID を取得"""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM model_versions WHERE is_active = true LIMIT 1")
        row = cur.fetchone()
    return row[0] if row else None


def fetch_racer_avg_st(conn, today: str) -> dict[int, float]:
    """
    racer_st_stats テーブルから各選手の平均 ST を取得して返す。

    racer_st_stats は build_racer_st_stats.py で過去2年分の履歴から
    事前集計されており、race_entries に1日分しかない環境でも
    正確な avg_st を返すことができる。

    Parameters
    ----------
    conn  : DB 接続
    today : 互換性のために残す（使用しない）

    Returns
    -------
    {racer_id: 平均ST} の辞書。
    """
    with conn.cursor() as cur:
        cur.execute("SELECT racer_id, avg_st FROM racer_st_stats")
        rows = cur.fetchall()
    return {row[0]: float(row[1]) for row in rows}


# ---------------------------------------------------------------------------
# 購入候補抽出（Session 5 以降の運用ルールに準拠）
# ---------------------------------------------------------------------------

def extract_bet_candidates(
    results: list[dict],
    *,
    race_id: str,
    stadium_id: int | None,
    race_no: int | None,
    prob_threshold: float,
    ev_threshold: float,
    min_odds: float | None,
    exclude_courses: set[int] | None,
    exclude_stadiums: set[int] | None,
    odds_dict: dict[str, float],
) -> list[dict]:
    """
    推論結果から購入条件に合致する候補のみを抽出する。

    デフォルトは CLAUDE.md の運用ルール: prob>=7%, EV>=2.0, コース2/4/5除外,
    オッズ<100x除外, びわこ除外。
    """
    if exclude_stadiums and stadium_id in exclude_stadiums:
        return []

    candidates: list[dict] = []
    for r in results:
        prob = r.get("win_probability") or 0.0
        ev = r.get("expected_value")
        if ev is None:
            continue
        if prob < prob_threshold or ev < ev_threshold:
            continue

        combo = r["combination"]
        odds = odds_dict.get(combo)
        if odds is None:
            continue
        if min_odds is not None and odds < min_odds:
            continue

        first = int(combo.split("-")[0])
        if exclude_courses and first in exclude_courses:
            continue

        candidates.append(
            {
                "race_id": race_id,
                "stadium_id": stadium_id,
                "race_no": race_no,
                "combination": combo,
                "win_probability": prob,
                "expected_value": ev,
                "odds": odds,
            }
        )
    return candidates


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="boatrace 本番予測 + ベット候補通知")
    parser.add_argument("--notify", action="store_true",
                        help="購入候補を Discord Webhook 経由で通知する")
    parser.add_argument("--prob-threshold", type=float, default=0.07,
                        help="通知対象の的中確率閾値（デフォルト: 0.07）")
    parser.add_argument("--ev-threshold", type=float, default=2.0,
                        help="通知対象の期待値閾値（デフォルト: 2.0）")
    parser.add_argument("--min-odds", type=float, default=100.0,
                        help="通知対象のオッズ下限（デフォルト: 100.0）")
    parser.add_argument("--exclude-courses", type=int, nargs="+", default=[2, 4, 5],
                        help="通知対象から除外する1着艇番（デフォルト: 2 4 5）")
    parser.add_argument("--exclude-stadiums", type=int, nargs="+", default=[11],
                        help="通知対象から除外する場ID（デフォルト: 11=びわこ）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if not MODEL_PATH.exists():
        logger.error("Model not found at %s. Run download_model.py first.", MODEL_PATH)
        sys.exit(1)

    logger.info("Loading model from %s", MODEL_PATH)
    model = load_model(MODEL_PATH)

    with get_connection() as conn:
        model_version_id = fetch_active_model_version_id(conn)
        logger.info("Active model_version_id: %s", model_version_id)

        # 本日 (JST) の未終了レースを取得（再予測により EV を最新オッズに追従させる）
        JST = timezone(timedelta(hours=9))
        today_jst = datetime.now(JST).date().isoformat()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id
                FROM races r
                WHERE r.race_date = %s
                  AND r.status != 'finished'
                """,
                (today_jst,),
            )
            race_ids = [row[0] for row in cur.fetchall()]

        logger.info("Found %d races to predict", len(race_ids))

        # 選手ごとの過去 ST 平均を一括取得（全レースで共有）
        racer_avg_st = fetch_racer_avg_st(conn, today_jst)
        logger.info("Loaded avg ST for %d racers", len(racer_avg_st))

        exclude_courses = set(args.exclude_courses) if args.exclude_courses else None
        exclude_stadiums = set(args.exclude_stadiums) if args.exclude_stadiums else None
        all_candidates: list[dict] = []

        for race_id in race_ids:
            logger.info("Predicting race %s ...", race_id)

            # 1. 出走表取得
            entries = fetch_race_entries(conn, race_id)
            if len(entries) < 6:
                logger.warning("Race %s: only %d entries, skipping.", race_id, len(entries))
                continue

            # 2. レースメタ取得
            race_meta = fetch_race_meta(conn, race_id)
            if race_meta.empty:
                logger.warning("Race %s: no meta found, skipping.", race_id)
                continue

            # 3. 特徴量生成（過去 ST 平均をバックテストと同様に渡す）
            X = build_features(entries, race_meta, racer_avg_st=racer_avg_st)
            if len(X) < 6:
                logger.warning("Race %s: feature build produced %d rows, skipping.", race_id, len(X))
                continue

            # 4. 各艇の1着確率を推定
            raw_probs = predict_win_prob(model, X)
            # LightGBM multiclass → クラス0（1着）の確率列を使用
            if raw_probs.ndim == 2:
                first_place_probs = raw_probs[:, 0]
            else:
                first_place_probs = raw_probs

            # 5. 3連単確率を近似計算
            trifecta_probs = calc_trifecta_probs(first_place_probs)

            # 6. オッズ取得（なくても確率だけ先に保存する）
            odds_dict = fetch_odds(conn, race_id)
            if not odds_dict:
                logger.info("Race %s: no odds data, saving probabilities only.", race_id)

            # 7. 期待値計算（オッズがある組み合わせのみ）& upsert
            if odds_dict:
                results = calc_expected_values(trifecta_probs, odds_dict)
                alert_count = sum(1 for r in results if r["alert_flag"])
            else:
                # オッズなし: 全120通りを確率のみで保存
                results = [
                    {
                        "combination": combo,
                        "win_probability": prob,
                        "expected_value": None,
                        "alert_flag": False,
                    }
                    for combo, prob in trifecta_probs.items()
                ]
                alert_count = 0

            for result in results:
                upsert_prediction(
                    conn,
                    {
                        "race_id": race_id,
                        "combination": result["combination"],
                        "win_probability": result["win_probability"],
                        "expected_value": result["expected_value"],
                        "alert_flag": result["alert_flag"],
                        "model_version_id": model_version_id,
                    },
                )

            conn.commit()
            logger.info(
                "Race %s: %d predictions upserted (%d alerts, EV >= 1.2)",
                race_id, len(results), alert_count,
            )

            # ベット候補（通知対象）を抽出
            if odds_dict:
                stadium_id = int(race_meta.iloc[0]["stadium_id"])
                race_no = int(race_meta.iloc[0]["race_no"])
                all_candidates.extend(
                    extract_bet_candidates(
                        results,
                        race_id=race_id,
                        stadium_id=stadium_id,
                        race_no=race_no,
                        prob_threshold=args.prob_threshold,
                        ev_threshold=args.ev_threshold,
                        min_odds=args.min_odds,
                        exclude_courses=exclude_courses,
                        exclude_stadiums=exclude_stadiums,
                        odds_dict=odds_dict,
                    )
                )

    logger.info("Extracted %d bet candidates", len(all_candidates))
    if args.notify:
        notify_bet_candidates(all_candidates)
    elif all_candidates:
        logger.info("(--notify flag off; skipping notification)")

    logger.info("=== predict done ===")


if __name__ == "__main__":
    main()
