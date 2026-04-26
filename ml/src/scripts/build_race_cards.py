"""LLM 予想用レースカード一括ビルド (P1 `/prep-races` の本体).

使い方:
  py -3.12 ml/src/scripts/build_race_cards.py 2026-04-25 桐生 平和島
  py -3.12 ml/src/scripts/build_race_cards.py 2025-12-01 1 4 12
  py -3.12 ml/src/scripts/build_race_cards.py 2026-04-27 蒲郡

会場は日本語名 / 数字 / ゼロ埋め ID を混在可.
出力先: artifacts/race_cards/<YYYY-MM-DD>/<場ID>_<R>.md と index.md.

過去日付も受け付ける (バックテスト用).
B ファイル未取得日は DL を試行する. 該当日に該当場が休場の場合は警告のみ.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from collections import defaultdict
from pathlib import Path

# ml/src/ を import path へ (既存 scripts と同じ慣習)
sys.path.insert(0, str(Path(__file__).parents[1]))

# Windows console (CP932) でも会場名 (漢字) を正しく出力するため UTF-8 を強制
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from predict_llm.history_summarizer import group_by_racer
from predict_llm.program_parser import Race, load_program_for_day
from predict_llm.race_card_builder import (
    DEFAULT_RECENT_LOCAL_N,
    DEFAULT_RECENT_NATIONAL_N,
    build_index,
    build_race_card,
)
from predict_llm.stadium_resolver import (
    UnknownStadiumError,
    name_of,
    resolve,
)

logger = logging.getLogger("build_race_cards")

ARTIFACTS_ROOT = Path(__file__).resolve().parents[3] / "artifacts" / "race_cards"


def _parse_date(s: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(s)
    except ValueError as exc:
        raise SystemExit(f"date must be YYYY-MM-DD format: {s!r}") from exc


def _resolve_stadiums(args: list[str]) -> list[int]:
    out: list[int] = []
    for a in args:
        try:
            out.append(resolve(a))
        except UnknownStadiumError as exc:
            raise SystemExit(f"unknown stadium: {a!r} ({exc})")
    # 重複排除しつつ入力順を保持
    seen: set[int] = set()
    uniq: list[int] = []
    for sid in out:
        if sid not in seen:
            uniq.append(sid)
            seen.add(sid)
    return uniq


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LLM 予想用レースカードを生成する (P1 /prep-races)"
    )
    parser.add_argument("date", help="対象日付 YYYY-MM-DD")
    parser.add_argument("stadiums", nargs="+", help="会場 (日本語名 / 数字 / ゼロ埋め ID)")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="直近 N 走集計のため遡る日数 (default: 90)",
    )
    parser.add_argument(
        "--recent-national",
        type=int,
        default=DEFAULT_RECENT_NATIONAL_N,
        help=f"全国直近 N 走 (default: {DEFAULT_RECENT_NATIONAL_N})",
    )
    parser.add_argument(
        "--recent-local",
        type=int,
        default=DEFAULT_RECENT_LOCAL_N,
        help=f"当地直近 N 走 (default: {DEFAULT_RECENT_LOCAL_N})",
    )
    parser.add_argument(
        "--output-root",
        default=str(ARTIFACTS_ROOT),
        help=f"出力ルート (default: {ARTIFACTS_ROOT})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    target_date = _parse_date(args.date)
    stadium_ids = _resolve_stadiums(args.stadiums)

    print(f"[prep-races] date={target_date} stadiums={[f'{s:02d}_{name_of(s)}' for s in stadium_ids]}")

    # B ファイル DL + パース
    print(f"[prep-races] downloading/parsing program file for {target_date} ...")
    races = load_program_for_day(
        target_date.year, target_date.month, target_date.day,
        stadium_ids=set(stadium_ids),
    )
    if not races:
        print(f"[prep-races] WARNING: no races found for {target_date} (B file missing or empty)")
        return 1

    races_by_stadium: dict[int, list[Race]] = defaultdict(list)
    for r in races:
        races_by_stadium[r.stadium_id].append(r)

    # 休場会場の警告
    open_sids = set(races_by_stadium.keys())
    for sid in stadium_ids:
        if sid not in open_sids:
            print(f"[prep-races] WARNING: stadium {sid:02d} ({name_of(sid)}) is closed on {target_date} - skipped")

    if not open_sids:
        print(f"[prep-races] no open stadiums in target list - nothing to do")
        return 1

    # 出力ディレクトリ
    out_dir = Path(args.output_root) / target_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 場ごとに history 集計 → MD 生成
    total_written = 0
    for sid in sorted(open_sids):
        rs = sorted(races_by_stadium[sid], key=lambda r: r.race_no)
        racer_ids = {b.racer_id for r in rs for b in r.boats}
        print(f"[prep-races] {sid:02d} {name_of(sid)}: {len(rs)} races, {len(racer_ids)} racers - aggregating history ...")
        grouped = group_by_racer(racer_ids, target_date, lookback_days=args.lookback_days)

        for r in rs:
            md = build_race_card(
                r, grouped,
                recent_n_national=args.recent_national,
                recent_n_local=args.recent_local,
            )
            fname = f"{sid:02d}_{r.race_no:02d}.md"
            (out_dir / fname).write_text(md, encoding="utf-8")
            total_written += 1

    # index.md
    index_md = build_index(
        target_date.isoformat(),
        {sid: races_by_stadium[sid] for sid in open_sids},
    )
    (out_dir / "index.md").write_text(index_md, encoding="utf-8")

    print(f"[prep-races] done: {total_written} race cards + index.md -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
