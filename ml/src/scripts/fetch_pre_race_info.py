"""直前情報を取得して race card MD を上書きする CLI (P2 `/predict` の前段).

使い方:
  py -3.12 ml/src/scripts/fetch_pre_race_info.py 2025-12-01 桐生 1
  py -3.12 ml/src/scripts/fetch_pre_race_info.py 2025-12-01 桐生
  py -3.12 ml/src/scripts/fetch_pre_race_info.py 2025-12-01

過去日 (race_date < today) は自動的に "past" モード (キャッシュ + K ファイル).
当日は "live" モード (boatrace.jp スクレイプ).
明示指定したい場合は --mode live|past.

artifacts/race_cards/<日付>/<場ID>_<R>.md がない場合はエラー (先に /prep-races).

出力:
  - artifacts/race_cards/<日付>/<場ID>_<R>.md (上書き、直前情報セクション置換)
  - artifacts/predictions/<日付>/<場ID>_<R>_pre.json (デバッグ用、直前情報の生データ)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

# Windows console (CP932) でも会場名 (漢字) を正しく出力するため UTF-8 を強制
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from predict_llm.pre_race_fetcher import (
    append_to_race_card,
    dump_pre_race_json,
    fetch_pre_race_info,
)
from predict_llm.stadium_resolver import (
    UnknownStadiumError,
    name_of,
    resolve,
)

logger = logging.getLogger("fetch_pre_race_info")

ARTIFACTS_ROOT = Path(__file__).resolve().parents[3] / "artifacts"
RACE_CARDS_ROOT = ARTIFACTS_ROOT / "race_cards"
PREDICTIONS_ROOT = ARTIFACTS_ROOT / "predictions"


def _parse_date(s: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(s)
    except ValueError as exc:
        raise SystemExit(f"date must be YYYY-MM-DD format: {s!r}") from exc


def _list_target_files(
    target_date: _dt.date,
    stadium_id: int | None,
    race_no: int | None,
    cards_dir: Path,
) -> list[tuple[int, int, Path]]:
    """対象 race card ファイルを (stadium_id, race_no, path) のリストで返す."""
    if not cards_dir.exists():
        raise SystemExit(
            f"race cards dir not found: {cards_dir}\n"
            f"先に /prep-races {target_date} ... を実行してください。"
        )

    out: list[tuple[int, int, Path]] = []
    for md in sorted(cards_dir.glob("*.md")):
        if md.name == "index.md":
            continue
        # ファイル名は "01_05.md" 形式
        try:
            sid_str, rno_str = md.stem.split("_")
            sid = int(sid_str)
            rno = int(rno_str)
        except ValueError:
            continue
        if stadium_id is not None and sid != stadium_id:
            continue
        if race_no is not None and rno != race_no:
            continue
        out.append((sid, rno, md))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="直前情報を取得して race card MD を上書き (P2 /predict の前段)"
    )
    parser.add_argument("date", help="対象日付 YYYY-MM-DD")
    parser.add_argument("stadium", nargs="?", default=None, help="会場 (省略時は当日全場)")
    parser.add_argument("race_no", nargs="?", type=int, default=None, help="R番号 (省略時は 1〜12)")
    parser.add_argument(
        "--mode",
        choices=["live", "past", "auto"],
        default="auto",
        help="auto = 過去日は past, 当日は live (default: auto)",
    )
    parser.add_argument(
        "--cards-root",
        default=str(RACE_CARDS_ROOT),
        help=f"race cards ルート (default: {RACE_CARDS_ROOT})",
    )
    parser.add_argument(
        "--predictions-root",
        default=str(PREDICTIONS_ROOT),
        help=f"predictions ルート (default: {PREDICTIONS_ROOT})",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="*_pre.json デバッグダンプを書かない",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    target_date = _parse_date(args.date)

    sid: int | None
    if args.stadium is None:
        sid = None
    else:
        try:
            sid = resolve(args.stadium)
        except UnknownStadiumError as exc:
            raise SystemExit(f"unknown stadium: {args.stadium!r} ({exc})")

    race_no = args.race_no
    if race_no is not None and not (1 <= race_no <= 12):
        raise SystemExit(f"race_no must be 1..12: {race_no}")

    mode = None if args.mode == "auto" else args.mode

    cards_dir = Path(args.cards_root) / target_date.isoformat()
    targets = _list_target_files(target_date, sid, race_no, cards_dir)
    if not targets:
        raise SystemExit(
            f"対象レースカードが見つかりません: dir={cards_dir} stadium={sid} race={race_no}\n"
            f"先に /prep-races を実行してください。"
        )

    # JSON ダンプ用ディレクトリ
    pred_dir = Path(args.predictions_root) / target_date.isoformat()
    if not args.no_json:
        pred_dir.mkdir(parents=True, exist_ok=True)

    print(f"[fetch-pre] date={target_date} mode={args.mode} targets={len(targets)} races")

    success = 0
    for sid_t, rno_t, md_path in targets:
        try:
            info = fetch_pre_race_info(
                stadium_id=sid_t,
                race_date=target_date.isoformat(),
                race_no=rno_t,
                mode=mode,
            )
        except Exception as exc:
            print(f"[fetch-pre] ERROR {sid_t:02d}_{rno_t:02d}: {exc}")
            continue

        try:
            append_to_race_card(md_path, info)
        except Exception as exc:
            print(f"[fetch-pre] ERROR overwriting {md_path}: {exc}")
            continue

        if not args.no_json:
            json_path = pred_dir / f"{sid_t:02d}_{rno_t:02d}_pre.json"
            try:
                dump_pre_race_json(info, json_path)
            except Exception as exc:
                logger.warning("dump_pre_race_json failed for %s: %s", json_path, exc)

        n_tri = len(info.trifecta_odds)
        n_win = len(info.win_odds)
        print(
            f"[fetch-pre] OK {sid_t:02d}({name_of(sid_t)})_{rno_t:02d} "
            f"mode={info.mode} weather={info.weather.weather or '-'} "
            f"trifecta={n_tri} win={n_win} notes={len(info.notes)}"
        )
        success += 1

    print(f"[fetch-pre] done: {success}/{len(targets)} updated -> {cards_dir}")
    return 0 if success > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
