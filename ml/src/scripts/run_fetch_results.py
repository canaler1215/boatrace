"""
fetch_results.yml から呼び出されるレース結果取得スクリプト

目的:
  ダッシュボードに表示された購入候補レース（S6-4運用ルール: prob ≥ 7%, EV ≥ 2.0）の
  確定結果を日次で取得し、race_results テーブルに保存する。
  ダッシュボード側で 「predictions.combination が race_results.trifecta_combination と一致 = 的中」
  を判定できるようにする。

処理フロー:
  1. --date （YYYY-MM-DD、省略時は JST 前日）の日付に対して
     predictions に行が存在するレースを取得
  2. それぞれの (stadium_id, race_no) に対して
     boatrace.jp の raceresult ページから
       - 3連単的中組合せ（例: "1-2-3"）
       - 3連単払戻金（100円あたり円）
     を取得
  3. race_results に upsert。races.status は 'finished' に更新
  4. 取得できないレース（開催中止・中止順延）はログに残すが失敗とはしない

運用:
  取得タイミングは 23:00 JST（翌日早朝の UTC 14:00）。
  boatrace.jp 最終レース（通常 20:30〜21:00）から2時間後で払戻金が確定している。
  collect.yml の 21:30 JST 実行と分離することで、万が一 collect.yml が失敗しても
  結果だけは独立して取得できる。
"""
import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.openapi_client import fetch_race_result_full
from collector.db_writer import (
    get_connection,
    upsert_race_results_batch,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MAX_WORKERS = 10
JST = timezone(timedelta(hours=9))


def _default_target_date() -> str:
    """JST 前日の YYYY-MM-DD を返す（23:00 JST 実行で当日分を確定させるため）"""
    return (datetime.now(JST).date() - timedelta(days=1)).isoformat()


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--date",
        default=None,
        help="取得対象日 (YYYY-MM-DD)。省略時は JST 前日。",
    )
    ap.add_argument(
        "--all-races",
        action="store_true",
        help="predictions に限定せず、その日の全レースを対象にする（再取得用）",
    )
    return ap.parse_args()


def _fetch_target_races(conn, target_date: str, *, all_races: bool) -> list[dict]:
    """対象レースのメタを取得。predictions に行があるレースのみ（デフォルト）"""
    with conn.cursor() as cur:
        if all_races:
            cur.execute(
                """
                SELECT r.id, r.stadium_id, r.race_no
                FROM races r
                WHERE r.race_date = %s
                ORDER BY r.stadium_id, r.race_no
                """,
                (target_date,),
            )
        else:
            # predictions に行がある = 当日 run_predict.py が走った = ダッシュボードに
            # 表示される可能性があるレース。race_results がまだない行のみに絞る。
            cur.execute(
                """
                SELECT DISTINCT r.id, r.stadium_id, r.race_no
                FROM races r
                JOIN predictions p ON p.race_id = r.id
                LEFT JOIN race_results rr ON rr.race_id = r.id
                WHERE r.race_date = %s
                  AND rr.race_id IS NULL
                ORDER BY r.stadium_id, r.race_no
                """,
                (target_date,),
            )
        rows = cur.fetchall()
    return [{"id": rid, "stadium_id": sid, "race_no": rno} for rid, sid, rno in rows]


def _fetch_one(race: dict, race_date: str) -> dict | None:
    """1 レース分の結果を取得する。失敗時は None"""
    try:
        data = fetch_race_result_full(race["stadium_id"], race_date, race["race_no"])
    except Exception as exc:
        logger.warning("raceresult %s: %s", race["id"], exc)
        return None

    combo = data.get("trifecta_combination")
    if not combo:
        # 中止順延など、着順自体が取れなかったケース
        logger.info("race %s: no trifecta combination (cancelled?)", race["id"])
        return None

    return {
        "race_id":              race["id"],
        "trifecta_combination": combo,
        "trifecta_payout":      data.get("trifecta_payout"),
    }


def main() -> None:
    args = _parse_args()
    target_date = args.date or _default_target_date()
    logger.info("=== fetch_results start: date=%s all=%s ===", target_date, args.all_races)

    with get_connection() as conn:
        races = _fetch_target_races(conn, target_date, all_races=args.all_races)
        if not races:
            logger.info("No target races for %s. nothing to fetch.", target_date)
            return

        logger.info("Fetching results for %d races with %d workers...", len(races), MAX_WORKERS)

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_fetch_one, race, target_date): race for race in races}
            for i, future in enumerate(as_completed(futures), start=1):
                rec = future.result()
                if rec is not None:
                    results.append(rec)
                if i % 20 == 0 or i == len(races):
                    logger.info("Progress: %d/%d (collected=%d)", i, len(races), len(results))

        if not results:
            logger.warning("No results collected for %s.", target_date)
            return

        logger.info("Writing %d race_results to DB...", len(results))
        written = upsert_race_results_batch(conn, results)

        # races.status = 'finished' に更新（結果が取れたレースのみ）
        finished_ids = [r["race_id"] for r in results]
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE races
                   SET status = 'finished',
                       updated_at = now()
                 WHERE id = ANY(%s)
                   AND status != 'finished'
                """,
                (finished_ids,),
            )

        conn.commit()
        logger.info("=== fetch_results done: %d rows (of %d races) ===", written, len(races))


if __name__ == "__main__":
    main()
