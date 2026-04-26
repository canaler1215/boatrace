"""K ファイル (競走成績) のキャッシュから直近 N 走を集計する.

既存 ml/src/collector/history_downloader.py:parse_result_file() を流用 (read-only).
DL は呼ばず、data/history/ の既存 LZH キャッシュだけを使用する.
"""
from __future__ import annotations

import datetime as _dt
import logging
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from collector.history_downloader import (
    DATA_DIR as _HISTORY_DIR,
    extract_lzh,
    parse_result_file,
)

logger = logging.getLogger(__name__)


@dataclass
class RecentRun:
    """直近 1 走の情報."""

    race_date: str  # "YYYY-MM-DD"
    stadium_id: int
    race_no: int
    boat_no: int  # 艇番 (= P1 では「コース」の近似値として扱う)
    finish_position: int | None  # 1〜6 / None (F・L・失格等)
    start_timing: float | None
    exhibition_time: float | None


@dataclass
class RacerSummary:
    """1 選手分の直近 N 走サマリ."""

    racer_id: int
    runs: list[RecentRun]  # 新しい順 (直近が先頭)
    avg_st: float | None  # 直近 N 走の平均 ST (None 除外)
    win_count: int  # 1 着回数
    place_count: int  # 1〜2 着回数
    show_count: int  # 1〜3 着回数
    n_valid_finish: int  # finish_position が int で取れた走数
    n_total: int  # 集計対象走数

    @property
    def win_rate(self) -> float:
        return self.win_count / self.n_valid_finish if self.n_valid_finish else 0.0

    @property
    def show_rate(self) -> float:
        return self.show_count / self.n_valid_finish if self.n_valid_finish else 0.0


def _kfile_path(date: _dt.date, history_dir: Path) -> Path:
    yy = date.year % 100
    return history_dir / f"k{yy:02d}{date.month:02d}{date.day:02d}.lzh"


def group_by_racer(
    racer_ids: set[int],
    before_date: _dt.date,
    lookback_days: int = 90,
    history_dir: Path | None = None,
) -> dict[int, list[RecentRun]]:
    """racer_id → 直近走リスト (新しい順) のマップを返す.

    before_date の **前日から遡って** lookback_days 日分の K ファイル (data/history/)
    をキャッシュから読み、racer_id でフィルタする.
    DL は行わない (欠損日は skip).
    """
    history_dir = history_dir or _HISTORY_DIR
    target_ids = set(racer_ids)
    if not target_ids:
        return {}

    out: dict[int, list[RecentRun]] = defaultdict(list)
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_predict_history_"))
    try:
        for offset in range(1, lookback_days + 1):
            date = before_date - _dt.timedelta(days=offset)
            lzh = _kfile_path(date, history_dir)
            if not lzh.exists():
                continue
            try:
                files = extract_lzh(lzh, tmpdir / lzh.stem)
            except Exception as exc:
                logger.debug("extract_lzh failed for %s: %s", lzh.name, exc)
                continue
            for f in files:
                for rec in parse_result_file(f):
                    rid = rec.get("racer_id")
                    if rid not in target_ids:
                        continue
                    out[rid].append(
                        RecentRun(
                            race_date=rec["race_date"],
                            stadium_id=rec["stadium_id"],
                            race_no=rec["race_no"],
                            boat_no=rec["boat_no"],
                            finish_position=rec.get("finish_position"),
                            start_timing=rec.get("start_timing"),
                            exhibition_time=rec.get("exhibition_time"),
                        )
                    )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 新しい順 (race_date desc, race_no desc)
    for lst in out.values():
        lst.sort(key=lambda r: (r.race_date, r.race_no), reverse=True)
    return dict(out)


def summarize(
    grouped: dict[int, list[RecentRun]],
    racer_id: int,
    n: int = 10,
    stadium_id: int | None = None,
) -> RacerSummary:
    """group_by_racer() の出力から直近 N 走サマリを生成.

    Parameters
    ----------
    stadium_id : 指定すると当該場のみで集計 (None = 全国)
    """
    runs_all = grouped.get(racer_id, [])
    if stadium_id is not None:
        runs_all = [r for r in runs_all if r.stadium_id == stadium_id]
    runs = runs_all[:n]

    sts = [r.start_timing for r in runs if r.start_timing is not None]
    avg_st = sum(sts) / len(sts) if sts else None

    valid_fin = [r.finish_position for r in runs if isinstance(r.finish_position, int)]
    win_count = sum(1 for f in valid_fin if f == 1)
    place_count = sum(1 for f in valid_fin if f <= 2)
    show_count = sum(1 for f in valid_fin if f <= 3)

    return RacerSummary(
        racer_id=racer_id,
        runs=runs,
        avg_st=avg_st,
        win_count=win_count,
        place_count=place_count,
        show_count=show_count,
        n_valid_finish=len(valid_fin),
        n_total=len(runs),
    )
