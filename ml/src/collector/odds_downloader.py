"""
boatrace.jp から過去の 3 連単最終オッズを取得・キャッシュする

利用可能期間: 約 2018 年以降（boatrace.jp サーバー保持期間）
キャッシュ形式: data/odds/odds_{YYYYMM}.parquet
               カラム: race_id (str), combination (str), odds (float)

使用例:
  from collector.odds_downloader import load_or_download_month_odds

  # race_df は K ファイルから得た DataFrame（race_id / stadium_id / race_date / race_no 列が必要）
  odds_map = load_or_download_month_odds(2025, 12, race_df)
  race_odds = odds_map.get("01202512011", {})  # {"1-2-3": 12.5, ...}
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from collector.openapi_client import fetch_odds

logger = logging.getLogger(__name__)

ODDS_DIR = Path(__file__).parents[3] / "data" / "odds"


# ---------------------------------------------------------------------------
# キャッシュ I/O
# ---------------------------------------------------------------------------

def _cache_path(year: int, month: int) -> Path:
    return ODDS_DIR / f"odds_{year}{month:02d}.parquet"


def _df_to_map(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """parquet DataFrame → {race_id: {combo: odds}}"""
    result: dict[str, dict[str, float]] = {}
    for race_id, group in df.groupby("race_id", sort=False):
        result[str(race_id)] = dict(zip(group["combination"], group["odds"].astype(float)))
    return result


def _save_cache(rows: list[dict], cache_path: Path) -> None:
    df = pd.DataFrame(rows, columns=["race_id", "combination", "odds"])
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path, index=False)
    logger.info("Saved %d odds entries to %s", len(df), cache_path)


# ---------------------------------------------------------------------------
# ダウンロード
# ---------------------------------------------------------------------------

def download_odds_for_races(
    race_infos: list[dict],
    cache_path: Path,
    max_workers: int = 10,
) -> dict[str, dict[str, float]]:
    """
    指定レース一覧の 3 連単オッズを boatrace.jp から取得してキャッシュする。

    並列ダウンロード（max_workers）により boatrace.jp の遅延（~9-10秒/req）を
    並列化して高速化する。グローバルレート制限は openapi_client 側で制御。
    100 レースごとに中間保存するため、中断後も再開可能。

    Parameters
    ----------
    race_infos  : list of {race_id, stadium_id, race_date, race_no}
    cache_path  : 保存先 parquet パス
    max_workers : 並列ダウンロード数（デフォルト: 5）

    Returns
    -------
    {race_id: {"1-2-3": 12.5, ...}}
    """
    # --- 中間保存からの再開 ---
    partial_path = cache_path.with_suffix(".partial.parquet")
    rows: list[dict] = []
    already_done: set[str] = set()

    if partial_path.exists():
        try:
            df_partial = pd.read_parquet(partial_path)
            rows = df_partial.to_dict("records")
            already_done = set(df_partial["race_id"].unique())
            logger.info("Resuming from partial cache: %d races already done", len(already_done))
        except Exception as exc:
            logger.warning("Could not load partial cache (%s) — starting fresh", exc)
            rows = []
            already_done = set()

    total = len(race_infos)
    to_fetch = [info for info in race_infos if str(info["race_id"]) not in already_done]

    success = len(already_done)
    empty = 0
    done = 0
    CHECKPOINT = 100
    lock = threading.Lock()

    def fetch_one(info: dict) -> tuple[str, dict[str, float]]:
        race_id    = str(info["race_id"])
        stadium_id = int(info["stadium_id"])
        race_date  = str(info["race_date"])
        race_no    = int(info["race_no"])
        try:
            return race_id, fetch_odds(stadium_id, race_date, race_no)
        except Exception as exc:
            logger.debug("fetch_odds failed %s: %s", race_id, exc)
            return race_id, {}

    logger.info(
        "Starting parallel download: %d races, %d workers",
        len(to_fetch), max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, info): info for info in to_fetch}

        for future in as_completed(futures):
            race_id, odds = future.result()

            with lock:
                done += 1
                total_done = len(already_done) + done

                if odds:
                    success += 1
                    for combo, val in odds.items():
                        rows.append({"race_id": race_id, "combination": combo, "odds": float(val)})
                else:
                    empty += 1

                if done % CHECKPOINT == 0 or total_done == total:
                    logger.info(
                        "Odds download: %d/%d  (ok=%d, empty=%d)",
                        total_done, total, success, empty,
                    )
                    _save_cache(rows, partial_path)

    logger.info(
        "Download complete: %d races with odds, %d empty/failed (total %d)",
        success, empty, total,
    )

    if not rows:
        logger.warning("No odds data obtained — returning empty map")
        return {}

    _save_cache(rows, cache_path)
    if partial_path.exists():
        partial_path.unlink()
        logger.info("Removed partial cache %s", partial_path)

    df = pd.DataFrame(rows)
    return _df_to_map(df)


# ---------------------------------------------------------------------------
# メイン API
# ---------------------------------------------------------------------------

def load_or_download_month_odds(
    year: int,
    month: int,
    race_df: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """
    指定月の 3 連単オッズを返す。
    キャッシュ（parquet）があればロード、なければ boatrace.jp からダウンロードして保存。

    Parameters
    ----------
    year, month : 対象年月
    race_df     : K ファイルから得た DataFrame
                  必須列: race_id, stadium_id, race_date, race_no

    Returns
    -------
    {race_id: {"1-2-3": 12.5, ...}}
    """
    cache_path = _cache_path(year, month)

    if cache_path.exists():
        logger.info("Loading odds cache: %s", cache_path)
        df = pd.read_parquet(cache_path)
        result = _df_to_map(df)
        logger.info("Loaded %d races from cache", len(result))
        return result

    logger.info(
        "No cache for %d-%02d. Downloading from boatrace.jp...",
        year, month,
    )

    # K ファイルデータからレース一覧を作成（1 レース 1 行）
    required_cols = {"race_id", "stadium_id", "race_date", "race_no"}
    missing = required_cols - set(race_df.columns)
    if missing:
        raise ValueError(f"race_df is missing columns: {missing}")

    race_infos = (
        race_df[list(required_cols)]
        .drop_duplicates("race_id")
        .to_dict("records")
    )

    estimated_min = len(race_infos) * 1.5 / 60
    logger.info(
        "Target: %d races — estimated %.0f min (1.5 sec/race)",
        len(race_infos), estimated_min,
    )

    return download_odds_for_races(race_infos, cache_path)
