"""B ファイル (出走表) の独自パーサ.

既存 ml/src/collector/program_downloader.py:parse_program_file() は
LightGBM 学習用に最小限の列 (race_id / racer_id / racer_grade /
racer_win_rate / motor_win_rate / boat_win_rate) しか抽出しない。

LLM レースカード生成では選手名・年齢・支部・体重・全国2連率・当地勝率/2連率・
モーター/ボート番号などを Markdown に埋め込みたいため、ここでフル情報を取る。

既存 collector のロジックには触らず、download_day_data() と extract_lzh()
だけを再利用する。
"""
from __future__ import annotations

import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from collector.history_downloader import extract_lzh
from collector.program_downloader import download_day_data

# ---------------------------------------------------------------------------
# 正規表現
# ---------------------------------------------------------------------------

_BBGN_RE = re.compile(r"^(\d{2})BBGN")
_BEND_RE = re.compile(r"^\d{2}BEND")
_DATE_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")

# レースヘッダー (全角): "　１Ｒ  一般...   Ｈ１８００ｍ  電話投票締切予定１５：１８"
# R1〜R9 は先頭に全角スペース 1 個、R10〜R12 は先頭スペースなしの形式があるため
# `[\s　]*` (0 個以上) とする。艇行は半角数字始まりなので衝突しない。
_RACE_HDR_RE = re.compile(r"^[\s　]*([１２３４５６７８９][０-９]?)Ｒ")

_SEP_RE = re.compile(r"^-{10,}")

# 6 艇行: "1 5137栗原 崇26高知55B1 5.57 39.08 6.29 47.06 31 32.89 63 21.79 6 624 3      6"
#
# 選手名は半角スペース区切りの可能性があるが、固定幅レイアウトのため
# (4桁racer_id) のあとから (年齢2桁 + 支部 + 体重2桁 + 級別) が連続する。
# 選手名部分は 8 バイト分 (半角スペース 8 個分の幅、全角 4 文字に相当) だが、
# 実際には漢字 + 全角スペースが入りうるので可変。
# 末尾から固定パターンを切り出す方が頑健。
# 各率は小数点以下 2 桁固定 (\d+\.\d{2}).
# 福岡 (22) 等でボート NO が 3 桁になると "25.00161" のように
# モーター 2 率とボート NO が空白なしで連結するため、greedy な \d+\.\d+ では
# "25.00161" 全体を食ってしまい失敗する。\d{2} で小数部を固定して回避。
_BOAT_HEAD_RE = re.compile(
    r"^([1-6])\s"
    r"(\d{4})"  # racer_id
    r"(.+?)"  # 選手名 (lazy)
    r"(\d{2})"  # 年齢
    r"([一-鿿]{2,3})"  # 支部
    r"(\d{2})"  # 体重
    r"([AB][12])"  # 級別
    r"\s+(\d+\.\d{2})"  # 全国勝率
    r"\s+(\d+\.\d{2})"  # 全国2連率
    r"\s+(\d+\.\d{2})"  # 当地勝率
    r"\s+(\d+\.\d{2})"  # 当地2連率
    r"\s+(\d+)"  # モーター NO
    r"\s+(\d+\.\d{2})"  # モーター2連率
    r"\s*(\d+)"  # ボート NO (3 桁の場合は前の空白なし)
    r"\s+(\d+\.\d{2})"  # ボート2連率
)

# 全角数字 → 半角数字
_FW_DIGIT_TABLE = str.maketrans("０１２３４５６７８９", "0123456789")


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass
class Boat:
    """1 艇分の出走情報."""

    boat_no: int
    racer_id: int
    racer_name: str
    racer_age: int
    racer_branch: str
    racer_weight: int
    racer_grade: str
    win_rate_national: float
    place_rate_national: float  # 2連率
    win_rate_local: float
    place_rate_local: float  # 2連率
    motor_no: int
    motor_2rate: float
    boat_no_unit: int
    boat_2rate: float


@dataclass
class Race:
    """1 レース分の情報 (race header + 6 艇)."""

    stadium_id: int
    race_date: str  # "YYYY-MM-DD"
    race_no: int
    race_name: str  # 例: "一般" / "予選" / "優勝戦"
    race_distance_m: int | None  # 例: 1800
    deadline: str | None  # "HH:MM"
    boats: list[Boat] = field(default_factory=list)

    @property
    def race_id(self) -> str:
        ymd = self.race_date.replace("-", "")
        return f"{self.stadium_id:02d}{ymd}{self.race_no:02d}"


# ---------------------------------------------------------------------------
# レースヘッダー行の解析
# ---------------------------------------------------------------------------


def _parse_race_header(line: str) -> tuple[str, int | None, str | None]:
    """レースヘッダー行から race_name / 距離 / 締切時刻 を抽出.

    例: "　１Ｒ  一般　　　　          Ｈ１８００ｍ  電話投票締切予定１５：１８"
    -> ("一般", 1800, "15:18")
    """
    # 全角 → 半角正規化
    norm = unicodedata.normalize("NFKC", line)

    # "1R" 以降を取得
    m = re.search(r"\d+R\s*(.+)", norm)
    if not m:
        return "", None, None
    rest = m.group(1)

    # 距離: "H1800m"
    distance: int | None = None
    dm = re.search(r"H(\d+)m", rest)
    if dm:
        distance = int(dm.group(1))

    # 締切時刻: 14:23 形式 (NFKC で全角コロンも半角化される)
    deadline: str | None = None
    tm = re.search(r"(\d{1,2}):(\d{2})", rest)
    if tm:
        deadline = f"{int(tm.group(1)):02d}:{tm.group(2)}"

    # レース名: "1R" の直後から最初の "H" or 距離前までの空白除去テキスト
    name_part = rest
    if dm:
        name_part = rest[: dm.start()]
    # 締切表記まで含まれる可能性があるので削除
    name_part = re.sub(r"電話投票締切予定.*", "", name_part)
    race_name = name_part.strip().strip("　").strip()

    return race_name, distance, deadline


# ---------------------------------------------------------------------------
# 艇行の解析
# ---------------------------------------------------------------------------


def _parse_boat_row(line: str) -> Boat | None:
    """艇データ行をパースして Boat を返す. 失敗時は None."""
    m = _BOAT_HEAD_RE.match(line)
    if m is None:
        return None
    try:
        # 選手名は連続する全角文字 + 全角スペース。trim する。
        name_raw = m.group(3)
        racer_name = name_raw.replace("　", " ").strip()
        # 連続スペースを 1 つに圧縮
        racer_name = re.sub(r"\s+", " ", racer_name).strip()

        return Boat(
            boat_no=int(m.group(1)),
            racer_id=int(m.group(2)),
            racer_name=racer_name,
            racer_age=int(m.group(4)),
            racer_branch=m.group(5),
            racer_weight=int(m.group(6)),
            racer_grade=m.group(7),
            win_rate_national=float(m.group(8)),
            place_rate_national=float(m.group(9)),
            win_rate_local=float(m.group(10)),
            place_rate_local=float(m.group(11)),
            motor_no=int(m.group(12)),
            motor_2rate=float(m.group(13)),
            boat_no_unit=int(m.group(14)),
            boat_2rate=float(m.group(15)),
        )
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# ファイル全体のパース
# ---------------------------------------------------------------------------


def parse_program_file_full(filepath: Path) -> Iterator[Race]:
    """B ファイル (B{YYMMDD}.TXT) を読み、Race を 1 レースずつ yield する.

    複数会場のブロックを順次処理する.
    """
    try:
        text = filepath.read_text(encoding="cp932", errors="replace")
    except Exception:
        text = filepath.read_text(encoding="utf-8", errors="replace")

    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]

    venue_code: int | None = None
    race_date: str | None = None
    current: Race | None = None
    after_sep: bool = False

    for line in lines:
        # 会場ブロック開始
        m = _BBGN_RE.match(line)
        if m:
            venue_code = int(m.group(1))
            race_date = None
            current = None
            after_sep = False
            continue

        # 会場ブロック終了
        if _BEND_RE.match(line):
            if current is not None and len(current.boats) > 0:
                yield current
                current = None
            venue_code = None
            continue

        if venue_code is None:
            continue

        # 日付検出
        if race_date is None:
            dm = _DATE_RE.search(unicodedata.normalize("NFKC", line))
            if dm:
                y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
                if 2010 <= y <= 2030:
                    race_date = f"{y:04d}-{mo:02d}-{d:02d}"
            continue

        # レースヘッダー行
        rm = _RACE_HDR_RE.match(line)
        if rm:
            # 直前のレースを yield
            if current is not None and len(current.boats) > 0:
                yield current
            race_no = int(rm.group(1).translate(_FW_DIGIT_TABLE))
            race_name, distance, deadline = _parse_race_header(line)
            current = Race(
                stadium_id=venue_code,
                race_date=race_date,
                race_no=race_no,
                race_name=race_name,
                race_distance_m=distance,
                deadline=deadline,
            )
            after_sep = False
            continue

        # セパレータ
        if _SEP_RE.match(line):
            if current is not None:
                after_sep = True
            continue

        # 艇行 (セパレータ後、最大 6 艇)
        if not (after_sep and current is not None and len(current.boats) < 6):
            continue

        if not line.strip():
            # 空行 → 艇セクション終了
            if current.boats:
                after_sep = False
            continue

        # 艇行先頭は半角数字 1-6 + " "
        if not (len(line) > 1 and line[0] in "123456" and line[1] == " "):
            continue

        boat = _parse_boat_row(line)
        if boat is not None:
            current.boats.append(boat)

    # ファイル末尾
    if current is not None and len(current.boats) > 0:
        yield current


# ---------------------------------------------------------------------------
# 高水準 API: 指定日の指定会場のレース一覧を取得
# ---------------------------------------------------------------------------


def load_program_for_day(
    year: int,
    month: int,
    day: int,
    stadium_ids: set[int] | None = None,
) -> list[Race]:
    """指定日の B ファイルを DL/キャッシュ取得し、Race リストを返す.

    Parameters
    ----------
    stadium_ids : 絞り込みたい場 ID. None なら全 24 場.
    """
    lzh = download_day_data(year, month, day)
    if lzh is None:
        return []

    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_predict_llm_"))
    try:
        files = extract_lzh(lzh, tmpdir / lzh.stem)
        races: list[Race] = []
        for f in files:
            for race in parse_program_file_full(f):
                if stadium_ids is None or race.stadium_id in stadium_ids:
                    races.append(race)
        return races
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
