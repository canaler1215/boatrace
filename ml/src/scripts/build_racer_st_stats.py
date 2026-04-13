"""
racer_st_stats テーブルを初期構築・更新するスクリプト

処理フロー:
  1. history_downloader.load_history_range() で過去2年分をダウンロード
  2. DataFrame から racer_id・start_timing を抽出
     (start_timing が None / 0 の行は除外)
  3. racer_id ごとに avg_st と sample_count を集計
  4. racer_st_stats テーブルに UPSERT

実行例:
  python ml/src/scripts/build_racer_st_stats.py
  python ml/src/scripts/build_racer_st_stats.py --start-year 2023 --end-year 2026
"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.db_writer import get_connection
from collector.history_downloader import load_history_range

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_racer_st_stats(start_year: int, end_year: int) -> None:
    """
    過去データから racer_st_stats を集計して DB に UPSERT する。

    Parameters
    ----------
    start_year : 集計開始年
    end_year   : 集計終了年
    """
    logger.info("Downloading history %d-%d ...", start_year, end_year)
    df = load_history_range(start_year=start_year, end_year=end_year)

    if df.empty:
        logger.error("No history data loaded. Aborting.")
        sys.exit(1)

    logger.info("Total records: %d", len(df))

    # start_timing が有効な行のみ使用 (None / 0 を除外)
    mask = df["start_timing"].notna() & (df["start_timing"] > 0)
    df_st = df.loc[mask, ["racer_id", "start_timing"]]
    logger.info("Records with valid start_timing: %d", len(df_st))

    # racer_id ごとに集計
    stats = (
        df_st.groupby("racer_id")["start_timing"]
        .agg(avg_st="mean", sample_count="count")
        .reset_index()
    )
    logger.info("Unique racers: %d", len(stats))

    # DB に UPSERT
    rows = [
        (int(row.racer_id), float(row.avg_st), int(row.sample_count))
        for row in stats.itertuples(index=False)
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO racer_st_stats (racer_id, avg_st, sample_count, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (racer_id) DO UPDATE SET
                    avg_st       = EXCLUDED.avg_st,
                    sample_count = EXCLUDED.sample_count,
                    updated_at   = now()
                """,
                rows,
            )
        conn.commit()
    logger.info("Upserted %d rows into racer_st_stats.", len(rows))


def main() -> None:
    today = date.today()
    default_start = today.year - 2

    parser = argparse.ArgumentParser(
        description="racer_st_stats テーブルを過去STデータで構築・更新する"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=default_start,
        help=f"集計開始年 (デフォルト: {default_start})",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=today.year,
        help=f"集計終了年 (デフォルト: {today.year})",
    )
    args = parser.parse_args()

    build_racer_st_stats(start_year=args.start_year, end_year=args.end_year)
    logger.info("=== build_racer_st_stats done ===")


if __name__ == "__main__":
    main()
