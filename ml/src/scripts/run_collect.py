"""
collect.yml から呼び出されるデータ収集スクリプト

処理フロー:
  1. 本日開催レース一覧を取得して races / race_entries に upsert
  2. 直前情報 (展示タイム・ST) を取得して race_entries を更新
  3. 3連単オッズを取得して odds に insert
  4. 終了済みレースの着順を取得して race_entries.finish_position を更新
"""
import logging
import sys
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


def main() -> None:
    today = date.today().isoformat()
    logger.info("=== collect start: %s ===", today)

    with get_connection() as conn:
        races = fetch_race_list(today)
        if not races:
            logger.info("No races today.")
            return

        for race in races:
            # 1. races テーブルに upsert
            upsert_race(conn, race)

            # 2. 出走表取得
            entries = fetch_entry_info(race["stadium_id"], today, race["race_no"])

            # 3. 直前情報 (展示タイム・ST) をマージ
            try:
                before = fetch_before_info(race["stadium_id"], today, race["race_no"])
                for entry in entries:
                    bn = entry["boat_no"]
                    if bn in before:
                        entry["exhibition_time"] = before[bn].get("exhibition_time")
                        entry["start_timing"]    = before[bn].get("start_timing")
            except Exception as exc:
                logger.warning("beforeinfo %s: %s", race["id"], exc)

            # 4. 出走表を upsert
            for entry in entries:
                upsert_race_entry(conn, entry)

            # 5. 3連単オッズを insert
            try:
                odds_data = fetch_odds(race["stadium_id"], today, race["race_no"])
                for combo, odds_val in odds_data.items():
                    upsert_odds(conn, race["id"], combo, odds_val)
            except Exception as exc:
                logger.warning("odds %s: %s", race["id"], exc)

            # 6. 着順取得 (レース終了後の場合のみ)
            if race.get("status") == "finished":
                try:
                    result = fetch_race_result(race["stadium_id"], today, race["race_no"])
                    for entry in entries:
                        bn = entry["boat_no"]
                        if bn in result:
                            entry["finish_position"] = result[bn]
                            upsert_race_entry(conn, entry)
                except Exception as exc:
                    logger.warning("raceresult %s: %s", race["id"], exc)

        conn.commit()

    logger.info("=== collect done: %d races processed ===", len(races))


if __name__ == "__main__":
    main()
