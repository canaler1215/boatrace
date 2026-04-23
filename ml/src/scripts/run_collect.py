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
from datetime import datetime, timezone, timedelta
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
    upsert_racers_batch,
    upsert_races_batch,
    upsert_race_entries_batch,
    upsert_odds_batch,
    update_predictions_final_odds_batch,
    insert_odds_history_batch,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MAX_WORKERS = 10


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
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).date().isoformat()
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

    # --- データ集約 ---
    # finish_position を entry に事前マージしておく
    for r in collected:
        if r["finish"]:
            for entry in r["entries"]:
                bn = entry["boat_no"]
                if bn in r["finish"]:
                    entry["finish_position"] = r["finish"][bn]

    all_races   = [r["race"] for r in collected]
    all_entries = [entry for r in collected for entry in r["entries"]]

    # racers テーブルへの upsert 用: racer_id をキーに重複排除
    racers_seen: dict[int, dict] = {}
    for entry in all_entries:
        rid = entry.get("racer_id")
        if rid and rid not in racers_seen:
            racers_seen[rid] = {
                "id": rid,
                "name": entry.get("racer_name") or str(rid),
                "grade": entry.get("racer_grade"),
            }
    all_racers = list(racers_seen.values())

    all_odds    = [
        (r["race"]["id"], combo, val)
        for r in collected
        for combo, val in r["odds"].items()
    ]

    # 終了済みレースのオッズは「確定オッズ」とみなし、predictions.final_odds に記録する
    # （EV 乖離モニタリング用。NULL の行のみ一度だけ書き込む。A-3: ODDS_FRESHNESS_IMPROVEMENT）
    final_odds_rows = [
        (r["race"]["id"], combo, val)
        for r in collected
        if r["race"].get("status") == "finished"
        for combo, val in r["odds"].items()
    ]

    # オッズ履歴は未終了レース分のみ蓄積する（終了済みは final_odds に記録済み）
    # C-1: ODDS_FRESHNESS_IMPROVEMENT
    history_rows = [
        (r["race"]["id"], combo, val)
        for r in collected
        if r["race"].get("status") != "finished"
        for combo, val in r["odds"].items()
    ]

    # --- DB 書き込み (executemany でバッチ処理) ---
    logger.info(
        "Writing to DB: %d races, %d entries, %d odds rows, %d final_odds rows, %d history rows...",
        len(all_races), len(all_entries), len(all_odds), len(final_odds_rows), len(history_rows),
    )
    with get_connection() as conn:
        upsert_races_batch(conn, all_races)
        if all_racers:
            upsert_racers_batch(conn, all_racers)
        if all_entries:
            upsert_race_entries_batch(conn, all_entries)
        if all_odds:
            upsert_odds_batch(conn, all_odds)
        if final_odds_rows:
            update_predictions_final_odds_batch(conn, final_odds_rows)
        if history_rows:
            insert_odds_history_batch(conn, history_rows)
        conn.commit()

    logger.info("=== collect done: %d races processed ===", len(races))


if __name__ == "__main__":
    main()
