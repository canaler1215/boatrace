"""
collect.yml から呼び出されるデータ収集スクリプト

処理フロー:
  1. 本日開催レース一覧を取得して races に upsert
  2. 各レースの出走表・直前情報・オッズを並列取得 (MAX_WORKERS)
  3. 取得結果を DB にシリアルで upsert (psycopg はスレッドセーフでないため)
  4. 終了済みレースの着順を取得して race_entries.finish_position を更新
"""
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.openapi_client import (
    fetch_race_list,
    fetch_entry_info,
    fetch_before_info,
    fetch_odds,
    fetch_race_result,
)
from collector.db_writer import (
    get_connection,
    upsert_race,
    upsert_race_entry,
    upsert_odds,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MAX_WORKERS = 5


def _collect_one(race: dict, today: str) -> dict:
    """1レース分の HTTP データを取得（DB 書き込みなし）"""
    entries: list[dict] = []
    odds: dict[str, float] = {}
    finish: dict[int, int] = {}

    try:
        entries = fetch_entry_info(race["stadium_id"], today, race["race_no"])
    except Exception as exc:
        logger.warning("entry_info %s: %s", race["id"], exc)

    try:
        before = fetch_before_info(race["stadium_id"], today, race["race_no"])
        for entry in entries:
            bn = entry["boat_no"]
            if bn in before:
                entry["exhibition_time"] = before[bn].get("exhibition_time")
                entry["start_timing"] = before[bn].get("start_timing")
    except Exception as exc:
        logger.warning("beforeinfo %s: %s", race["id"], exc)

    try:
        odds = fetch_odds(race["stadium_id"], today, race["race_no"])
    except Exception as exc:
        logger.warning("odds %s: %s", race["id"], exc)

    if race.get("status") == "finished":
        try:
            finish = fetch_race_result(race["stadium_id"], today, race["race_no"])
        except Exception as exc:
            logger.warning("raceresult %s: %s", race["id"], exc)

    return {"race": race, "entries": entries, "odds": odds, "finish": finish}


def main() -> None:
    today = date.today().isoformat()
    logger.info("=== collect start: %s ===", today)

    races = fetch_race_list(today)
    if not races:
        logger.info("No races today.")
        return

    # --- 並列 HTTP 取得 ---
    logger.info("Fetching data for %d races with %d workers...", len(races), MAX_WORKERS)
    collected: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_collect_one, race, today): race for race in races}
        for future in as_completed(futures):
            collected.append(future.result())
            done = len(collected)
            if done % 20 == 0 or done == len(races):
                logger.info("Collected %d/%d races", done, len(races))

    # --- DB 書き込み (メインスレッドで直列) ---
    logger.info("Writing %d races to DB...", len(collected))
    with get_connection() as conn:
        for r in collected:
            upsert_race(conn, r["race"])
            for entry in r["entries"]:
                upsert_race_entry(conn, entry)
            for combo, val in r["odds"].items():
                upsert_odds(conn, r["race"]["id"], combo, val)
            if r["finish"]:
                for entry in r["entries"]:
                    bn = entry["boat_no"]
                    if bn in r["finish"]:
                        entry["finish_position"] = r["finish"][bn]
                        upsert_race_entry(conn, entry)
        conn.commit()

    logger.info("=== collect done: %d races processed ===", len(races))


if __name__ == "__main__":
    main()
