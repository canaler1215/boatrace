"""
boatrace.jp から過去の 3 連単・3 連複最終オッズを取得・キャッシュする

利用可能期間: 約 2018 年以降（boatrace.jp サーバー保持期間）
キャッシュ形式:
  data/odds/odds_{YYYYMM}.parquet       3連単  カラム: race_id, combination, odds
  data/odds/trio_odds_{YYYYMM}.parquet  3連複  カラム: race_id, combination, odds
  data/odds/win_odds_{YYYYMM}.parquet   単勝   カラム: race_id, combination, odds  (combination = "1"〜"6")
  data/odds/place_odds_{YYYYMM}.parquet 複勝   カラム: race_id, combination, odds_low, odds_high

使用例:
  from collector.odds_downloader import (
      load_or_download_month_odds,
      load_or_download_month_trio_odds,
      load_or_download_month_win_odds,
      load_or_download_month_place_odds,
  )

  # race_df は K ファイルから得た DataFrame（race_id / stadium_id / race_date / race_no 列が必要）
  odds_map = load_or_download_month_odds(2025, 12, race_df)
  race_odds = odds_map.get("01202512011", {})  # {"1-2-3": 12.5, ...}

  trio_map = load_or_download_month_trio_odds(2025, 12, race_df)
  trio_race_odds = trio_map.get("01202512011", {})  # {"1-2-3": 8.5, ...}

  win_map = load_or_download_month_win_odds(2025, 12, race_df)
  win_race_odds = win_map.get("01202512011", {})  # {"1": 1.7, "2": 14.0, ...}

  place_map = load_or_download_month_place_odds(2025, 12, race_df)
  place_race_odds = place_map.get("01202512011", {})  # {"1": (1.0, 1.4), "2": (2.4, 3.1), ...}
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from collector.openapi_client import (
    fetch_odds,
    fetch_place_odds,
    fetch_trio_odds,
    fetch_win_odds,
)

logger = logging.getLogger(__name__)

ODDS_DIR = Path(__file__).parents[3] / "data" / "odds"


# ---------------------------------------------------------------------------
# キャッシュ I/O
# ---------------------------------------------------------------------------

def _cache_path(year: int, month: int) -> Path:
    return ODDS_DIR / f"odds_{year}{month:02d}.parquet"


def _trio_cache_path(year: int, month: int) -> Path:
    return ODDS_DIR / f"trio_odds_{year}{month:02d}.parquet"


def _win_cache_path(year: int, month: int) -> Path:
    return ODDS_DIR / f"win_odds_{year}{month:02d}.parquet"


def _place_cache_path(year: int, month: int) -> Path:
    return ODDS_DIR / f"place_odds_{year}{month:02d}.parquet"


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


def _place_df_to_map(df: pd.DataFrame) -> dict[str, dict[str, tuple[float, float]]]:
    """parquet DataFrame → {race_id: {combination: (odds_low, odds_high)}}"""
    result: dict[str, dict[str, tuple[float, float]]] = {}
    for race_id, group in df.groupby("race_id", sort=False):
        result[str(race_id)] = {
            str(c): (float(lo), float(hi))
            for c, lo, hi in zip(
                group["combination"],
                group["odds_low"],
                group["odds_high"],
            )
        }
    return result


def _save_place_cache(rows: list[dict], cache_path: Path) -> None:
    df = pd.DataFrame(rows, columns=["race_id", "combination", "odds_low", "odds_high"])
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path, index=False)
    logger.info("Saved %d place odds entries to %s", len(df), cache_path)


# ---------------------------------------------------------------------------
# ダウンロード（汎用）
# ---------------------------------------------------------------------------

from typing import Callable


def _download_odds_generic(
    race_infos: list[dict],
    cache_path: Path,
    fetch_fn: Callable[[int, str, int], dict[str, float]],
    label: str = "odds",
    max_workers: int = 10,
) -> dict[str, dict[str, float]]:
    """
    汎用オッズダウンロード関数。3連単・3連複どちらにも使用する。

    Parameters
    ----------
    race_infos  : list of {race_id, stadium_id, race_date, race_no}
    cache_path  : 保存先 parquet パス
    fetch_fn    : fetch_odds または fetch_trio_odds
    label       : ログ用ラベル
    max_workers : 並列ダウンロード数

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
            return race_id, fetch_fn(stadium_id, race_date, race_no)
        except Exception as exc:
            logger.debug("%s fetch failed %s: %s", label, race_id, exc)
            return race_id, {}

    logger.info(
        "Starting parallel %s download: %d races, %d workers",
        label, len(to_fetch), max_workers,
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
                        "%s download: %d/%d  (ok=%d, empty=%d)",
                        label, total_done, total, success, empty,
                    )
                    _save_cache(rows, partial_path)

    logger.info(
        "%s download complete: %d races with odds, %d empty/failed (total %d)",
        label, success, empty, total,
    )

    if not rows:
        logger.warning("No %s data obtained — returning empty map", label)
        return {}

    _save_cache(rows, cache_path)
    if partial_path.exists():
        partial_path.unlink()
        logger.info("Removed partial cache %s", partial_path)

    df = pd.DataFrame(rows)
    return _df_to_map(df)


def download_odds_for_races(
    race_infos: list[dict],
    cache_path: Path,
    max_workers: int = 10,
) -> dict[str, dict[str, float]]:
    """3連単オッズをダウンロードしてキャッシュする（後方互換エントリポイント）。"""
    return _download_odds_generic(
        race_infos, cache_path, fetch_odds, label="trifecta_odds", max_workers=max_workers
    )


def download_trio_odds_for_races(
    race_infos: list[dict],
    cache_path: Path,
    max_workers: int = 10,
) -> dict[str, dict[str, float]]:
    """3連複オッズをダウンロードしてキャッシュする。"""
    return _download_odds_generic(
        race_infos, cache_path, fetch_trio_odds, label="trio_odds", max_workers=max_workers
    )


def download_win_odds_for_races(
    race_infos: list[dict],
    cache_path: Path,
    max_workers: int = 10,
) -> dict[str, dict[str, float]]:
    """単勝オッズをダウンロードしてキャッシュする。"""
    return _download_odds_generic(
        race_infos, cache_path, fetch_win_odds, label="win_odds", max_workers=max_workers
    )


def download_place_odds_for_races(
    race_infos: list[dict],
    cache_path: Path,
    max_workers: int = 10,
) -> dict[str, dict[str, tuple[float, float]]]:
    """
    複勝オッズをダウンロードしてキャッシュする。

    複勝オッズは `(low, high)` の範囲表記なので _download_odds_generic は流用せず
    専用ループを持つ。データ構造以外（並列・partial 再開・ロギング）は同等。
    """
    label = "place_odds"
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

    def fetch_one(info: dict) -> tuple[str, dict[str, tuple[float, float]]]:
        race_id    = str(info["race_id"])
        stadium_id = int(info["stadium_id"])
        race_date  = str(info["race_date"])
        race_no    = int(info["race_no"])
        try:
            return race_id, fetch_place_odds(stadium_id, race_date, race_no)
        except Exception as exc:
            logger.debug("%s fetch failed %s: %s", label, race_id, exc)
            return race_id, {}

    logger.info(
        "Starting parallel %s download: %d races, %d workers",
        label, len(to_fetch), max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, info): info for info in to_fetch}

        for future in as_completed(futures):
            race_id, place_odds = future.result()

            with lock:
                done += 1
                total_done = len(already_done) + done

                if place_odds:
                    success += 1
                    for combo, (lo, hi) in place_odds.items():
                        rows.append({
                            "race_id": race_id,
                            "combination": combo,
                            "odds_low": float(lo),
                            "odds_high": float(hi),
                        })
                else:
                    empty += 1

                if done % CHECKPOINT == 0 or total_done == total:
                    logger.info(
                        "%s download: %d/%d  (ok=%d, empty=%d)",
                        label, total_done, total, success, empty,
                    )
                    _save_place_cache(rows, partial_path)

    logger.info(
        "%s download complete: %d races with odds, %d empty/failed (total %d)",
        label, success, empty, total,
    )

    if not rows:
        logger.warning("No %s data obtained — returning empty map", label)
        return {}

    _save_place_cache(rows, cache_path)
    if partial_path.exists():
        partial_path.unlink()
        logger.info("Removed partial cache %s", partial_path)

    df = pd.DataFrame(rows)
    return _place_df_to_map(df)


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


def load_or_download_month_trio_odds(
    year: int,
    month: int,
    race_df: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """
    指定月の 3 連複オッズを返す。
    キャッシュ（parquet）があればロード、なければ boatrace.jp からダウンロードして保存。

    Parameters
    ----------
    year, month : 対象年月
    race_df     : K ファイルから得た DataFrame
                  必須列: race_id, stadium_id, race_date, race_no

    Returns
    -------
    {race_id: {"1-2-3": 8.5, ...}}  全20通り（キーはソート済み艇番）
    """
    cache_path = _trio_cache_path(year, month)

    if cache_path.exists():
        logger.info("Loading trio odds cache: %s", cache_path)
        df = pd.read_parquet(cache_path)
        result = _df_to_map(df)
        logger.info("Loaded %d races from trio cache", len(result))
        return result

    logger.info(
        "No trio cache for %d-%02d. Downloading from boatrace.jp...",
        year, month,
    )

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

    return download_trio_odds_for_races(race_infos, cache_path)


def load_or_download_month_win_odds(
    year: int,
    month: int,
    race_df: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """
    指定月の単勝オッズを返す。
    キャッシュ（parquet）があればロード、なければ boatrace.jp からダウンロードして保存。

    Parameters
    ----------
    year, month : 対象年月
    race_df     : K ファイルから得た DataFrame
                  必須列: race_id, stadium_id, race_date, race_no

    Returns
    -------
    {race_id: {"1": 1.7, "2": 14.0, ..., "6": 16.8}}  全6通り（キー = 艇番文字列）
    """
    cache_path = _win_cache_path(year, month)

    if cache_path.exists():
        logger.info("Loading win odds cache: %s", cache_path)
        df = pd.read_parquet(cache_path)
        result = _df_to_map(df)
        logger.info("Loaded %d races from win cache", len(result))
        return result

    logger.info(
        "No win cache for %d-%02d. Downloading from boatrace.jp...",
        year, month,
    )

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

    return download_win_odds_for_races(race_infos, cache_path)


def load_or_download_month_place_odds(
    year: int,
    month: int,
    race_df: pd.DataFrame,
) -> dict[str, dict[str, tuple[float, float]]]:
    """
    指定月の複勝オッズを返す。
    キャッシュ（parquet）があればロード、なければ boatrace.jp からダウンロードして保存。

    Parameters
    ----------
    year, month : 対象年月
    race_df     : K ファイルから得た DataFrame
                  必須列: race_id, stadium_id, race_date, race_no

    Returns
    -------
    {race_id: {"1": (1.0, 1.4), "2": (2.4, 3.1), ...}}
    値は (odds_low, odds_high) tuple。実勢オッズ範囲表記を保持する。
    """
    cache_path = _place_cache_path(year, month)

    if cache_path.exists():
        logger.info("Loading place odds cache: %s", cache_path)
        df = pd.read_parquet(cache_path)
        result = _place_df_to_map(df)
        logger.info("Loaded %d races from place cache", len(result))
        return result

    logger.info(
        "No place cache for %d-%02d. Downloading from boatrace.jp...",
        year, month,
    )

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

    return download_place_odds_for_races(race_infos, cache_path)
