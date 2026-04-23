"""
refresh_ev.yml から呼び出されるオッズ軽量再取得スクリプト

処理フロー:
  1. 本日の未終了レースのうち、predictions に確率が保存済みのものを取得
  2. 各レースのオッズのみを HTTP 取得（推論不要）
  3. EV = win_probability × new_odds を DB 上で直接更新
  4. alert_flag（EV >= 1.2）も再評価して上書き

run_predict.py との違い:
  - LightGBM 推論なし（win_probability は既存値をそのまま使用）
  - オッズ取得のみのため 1 実行あたり ~2-3 分（cold start 込みで ~4-5 分）
  - 10 分ごとの実行が現実的
"""
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.db_writer import get_connection, insert_odds_history_batch
from collector.openapi_client import fetch_odds as http_fetch_odds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MAX_WORKERS = 10
ALERT_EV_THRESHOLD = 1.2


def fetch_active_races(conn, today: str) -> list[dict]:
    """本日の未終了レースのうち predictions が1件以上保存済みのものを返す"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT r.id, r.stadium_id, r.race_no
            FROM races r
            JOIN predictions p ON p.race_id = r.id
            WHERE r.race_date = %s
              AND r.status != 'finished'
            ORDER BY r.id
            """,
            (today,),
        )
        rows = cur.fetchall()
    return [{"id": row[0], "stadium_id": row[1], "race_no": row[2]} for row in rows]


def fetch_stored_probs(conn, race_id: str) -> dict[str, float]:
    """predictions テーブルから保存済みの win_probability を取得"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT combination, win_probability FROM predictions WHERE race_id = %s",
            (race_id,),
        )
        rows = cur.fetchall()
    return {row[0]: float(row[1]) for row in rows}


def update_ev_batch(conn, race_id: str, updates: list[dict]) -> int:
    """
    EV と alert_flag を一括 UPDATE する。

    updates: list of {combination, expected_value, alert_flag}
    戻り値: 更新件数（updates リストの長さ = 処理した組み合わせ数）
    """
    if not updates:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE predictions
            SET expected_value   = %(expected_value)s,
                alert_flag       = %(alert_flag)s,
                predicted_at     = now(),
                odds_snapshot_at = now()
            WHERE race_id    = %(race_id)s
              AND combination = %(combination)s
            """,
            [{"race_id": race_id, **u} for u in updates],
        )
    # psycopg3 の executemany は rowcount が -1 になる場合があるため len で代替
    return len(updates)


def refresh_race(
    race: dict, today: str, stored_probs: dict[str, float]
) -> tuple[str, list[dict], dict[str, float]]:
    """
    1レース分のオッズを HTTP 取得して EV を再計算する。
    DB 書き込みはせず、更新データと取得したオッズを返す（スレッドセーフ）。
    戻り値: (race_id, EV 更新用 dict のリスト, 取得オッズ dict)
    """
    race_id = race["id"]
    if not stored_probs:
        return race_id, [], {}

    try:
        new_odds = http_fetch_odds(race["stadium_id"], today, race["race_no"])
    except Exception as exc:
        logger.warning("odds fetch failed %s: %s", race_id, exc)
        return race_id, [], {}

    if not new_odds:
        logger.info("Race %s: no odds available", race_id)
        return race_id, [], {}

    updates: list[dict] = []
    for combo, prob in stored_probs.items():
        if combo not in new_odds:
            continue
        ev = prob * new_odds[combo]
        updates.append({
            "combination": combo,
            "expected_value": round(ev, 4),
            "alert_flag": ev >= ALERT_EV_THRESHOLD,
        })

    return race_id, updates, new_odds


def main() -> None:
    JST = timezone(timedelta(hours=9))
    today_jst = datetime.now(JST).date().isoformat()
    logger.info("=== refresh_ev start: %s ===", today_jst)

    with get_connection() as conn:
        races = fetch_active_races(conn, today_jst)
        logger.info("Found %d active races with predictions", len(races))

        if not races:
            logger.info("No races to refresh. Exiting.")
            return

        # 全レースの保存済み確率を一括取得
        stored_probs_map: dict[str, dict[str, float]] = {}
        for race in races:
            stored_probs_map[race["id"]] = fetch_stored_probs(conn, race["id"])

    # --- 並列 HTTP 取得（DB 接続は使わない） ---
    logger.info("Fetching odds for %d races with %d workers...", len(races), MAX_WORKERS)
    results: list[tuple[str, list[dict], dict[str, float]]] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(refresh_race, race, today_jst, stored_probs_map[race["id"]]): race
            for race in races
        }
        for future in as_completed(futures):
            results.append(future.result())

    # --- DB 更新（シリアル）---
    total_updated = 0
    total_alerts = 0
    history_rows: list[tuple[str, str, float]] = []

    with get_connection() as conn:
        for race_id, updates, new_odds in results:
            if not updates:
                continue
            n = update_ev_batch(conn, race_id, updates)
            alerts = sum(1 for u in updates if u["alert_flag"])
            total_updated += n
            total_alerts += alerts
            logger.info("Race %s: %d EVs updated (%d alerts)", race_id, n, alerts)
            # オッズ履歴には取得できた全組合せを蓄積（EV 対象外の組合せも推移分析で必要）
            # C-1: ODDS_FRESHNESS_IMPROVEMENT
            for combo, val in new_odds.items():
                history_rows.append((race_id, combo, val))

        if history_rows:
            insert_odds_history_batch(conn, history_rows)
        conn.commit()

    logger.info(
        "=== refresh_ev done: %d races, %d predictions updated, %d alerts, %d history rows ===",
        len([r for r in results if r[1]]),
        total_updated,
        total_alerts,
        len(history_rows),
    )


if __name__ == "__main__":
    main()
