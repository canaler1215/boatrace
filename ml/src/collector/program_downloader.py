"""
mbrace.or.jp から出走表（B ファイル）をダウンロード・パースする

データソース:
  https://www1.mbrace.or.jp/od2/B/dindex.html
  日次 LZH ファイル (2012年〜) / 全24場分の出走表が1ファイルに格納

URL パターン:
  https://www1.mbrace.or.jp/od2/B/{YYYYMM}/b{YY}{MM}{DD}.lzh
  例: https://www1.mbrace.or.jp/od2/B/202604/b260413.lzh

B ファイル フォーマット (Shift-JIS テキスト):
  複数の会場ブロックが 1 ファイルに格納される。
  各会場ブロックは {JCD}BBGN 〜 {JCD}BEND で囲まれる
  （K ファイルは KBGN/KEND）。

  ブロック先頭のヘッダーに「YYYY年MM月DD日」形式（全角）で開催日が含まれる。

  各レースのセクション:
    ・レースヘッダー行 (全角数字 + 全角R): 例 "　１Ｒ  一般..."
    ・カラムヘッダー 2 行
    ・セパレータ行 ("---..." が10文字以上)
    ・6艇分の出走表行:
        "1 3761山本光雄54滋賀54B1 5.31 34.48 5.04 36.00 26 33.90 25 33.15 ..."
        フィールド (1行正規表現でパース — split() は全角スペースで分割されるため不使用):
          艇番     (1-6)
          racer_id (4桁)
          選手名   (漢字 + 全角スペース、age/pref/weightと連続)
          grade    (A1/A2/B1/B2)
          全国勝率  → racer_win_rate
          全国2率   (使用しない)
          当地勝率  (使用しない)
          当地2率   (使用しない)
          モーターNO (使用しない)
          モーター2率 → motor_win_rate
          ボートNO  (使用しない)
          ボート2率  → boat_win_rate
"""
import datetime
import logging
import re
import shutil
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

from collector.history_downloader import extract_lzh

logger = logging.getLogger(__name__)

BASE_URL = "https://www1.mbrace.or.jp/od2/B"
DATA_DIR = Path(__file__).parents[3] / "data" / "program"
REQUEST_INTERVAL = 0.5
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BoatracePredictor/1.0)",
    "Accept-Language": "ja",
    "Referer": "https://www1.mbrace.or.jp/od2/B/dindex.html",
}

# ---- 正規表現 ---------------------------------------------------------------

_BBGN_RE = re.compile(r'^(\d{2})BBGN')
_BEND_RE  = re.compile(r'^\d{2}BEND')

# NFKC 正規化後に適用（全角数字 → 半角変換済み）
_DATE_RE  = re.compile(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日')

# レースヘッダー: 全角スペース/スペース + 全角数字(1-2桁) + 全角R
# 例: "　１Ｒ  一般..." / "　１２Ｒ  ..."
_B_RACE_HDR_RE = re.compile(r'^[\s\u3000]+([１２３４５６７８９][０-９]?)Ｒ')

# セパレータ
_SEP_RE = re.compile(r'^-{10,}')

# 全角数字 → 半角変換テーブル
_FW_DIGIT_TABLE = str.maketrans('０１２３４５６７８９', '0123456789')

# 艇データ行: 1 行正規表現
# split() は全角スペース(U+3000)を区切り文字として扱うため使用不可。
# 選手名に U+3000 が含まれるケース（例: "岩井　繁"）に対応するため
# 1 行まるごとにマッチする正規表現を使用する。
_ROW_RE = re.compile(
    r'^([1-6]) '                                                # 艇番
    r'(\d{4})'                                                  # racer_id
    r'[\u3000\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]+'       # 選手名
    r'\d{2}'                                                    # 年齢
    r'[\u4E00-\u9FFF]{2,3}'                                    # 支部(都道府県) 2-3文字
    r'\d{2}'                                                    # 体重
    r'([AB][12])'                                               # 級別
    r'\s+(\d+\.\d+)'                                           # 全国勝率 → racer_win_rate
    r'\s+\d+\.\d+'                                             # 全国2率 (skip)
    r'\s+\d+\.\d+'                                             # 当地勝率 (skip)
    r'\s+\d+\.\d+'                                             # 当地2率 (skip)
    r'\s+\d+'                                                   # モーターNO (skip)
    r'\s+(\d+\.\d+)'                                           # モーター2率 → motor_win_rate
    r'\s+\d+'                                                   # ボートNO (skip)
    r'\s+(\d+\.\d+)'                                           # ボート2率 → boat_win_rate
)


# ---------------------------------------------------------------------------
# ダウンロード
# ---------------------------------------------------------------------------

def _make_url(year: int, month: int, day: int) -> str:
    yy = year % 100
    yyyymm = f"{year}{month:02d}"
    filename = f"b{yy:02d}{month:02d}{day:02d}.lzh"
    return f"{BASE_URL}/{yyyymm}/{filename}"


def download_day_data(
    year: int, month: int, day: int, dest_dir: Path | None = None
) -> Path | None:
    """
    指定日の B ファイルをダウンロードして保存する。
    開催がない日・取得不可の場合は None を返す。
    """
    save_dir = dest_dir or DATA_DIR
    save_dir.mkdir(parents=True, exist_ok=True)

    yy = year % 100
    filename = f"b{yy:02d}{month:02d}{day:02d}.lzh"
    dest = save_dir / filename

    if dest.exists() and dest.stat().st_size > 0:
        return dest  # キャッシュ済み

    url = _make_url(year, month, day)
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
    except requests.RequestException as exc:
        logger.debug("Request failed %s: %s", url, exc)
        return None

    time.sleep(REQUEST_INTERVAL)

    if resp.status_code == 404:
        return None

    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        logger.warning("Unexpected HTML response for %s", url)
        return None

    with open(dest, "wb") as f:
        f.write(resp.content)

    logger.debug("Downloaded %s (%.1f KB)", filename, dest.stat().st_size / 1024)
    return dest


# ---------------------------------------------------------------------------
# パース
# ---------------------------------------------------------------------------

def parse_program_file(filepath: Path) -> Iterator[dict]:
    """
    B ファイル（出走表）を 1 レコード (= 1 艇 × 1 レース) ずつ yield する。

    yields keys:
      race_id, stadium_id, race_date, race_no, boat_no,
      racer_id, racer_grade, racer_win_rate, motor_win_rate, boat_win_rate
    """
    try:
        text = filepath.read_text(encoding="cp932", errors="replace")
    except Exception:
        text = filepath.read_text(encoding="utf-8", errors="replace")

    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]

    venue_code: int | None = None
    date_str:   str | None = None   # "YYYYMMDD"
    race_date:  str | None = None   # "YYYY-MM-DD"
    race_no:    int | None = None
    after_sep:  bool       = False
    boat_count: int        = 0

    for line in lines:

        # ---- 会場ブロック開始 ----------------------------------------
        m = _BBGN_RE.match(line)
        if m:
            venue_code = int(m.group(1))
            date_str   = None
            race_date  = None
            race_no    = None
            after_sep  = False
            boat_count = 0
            continue

        # ---- 会場ブロック終了 ----------------------------------------
        if _BEND_RE.match(line):
            venue_code = None
            continue

        if venue_code is None:
            continue

        # ---- 日付検出 ("YYYY年MM月DD日" 形式 — 全角のため NFKC 正規化して検索) ---
        if date_str is None:
            m = _DATE_RE.search(unicodedata.normalize("NFKC", line))
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 2010 <= y <= 2030:
                    date_str  = f"{y:04d}{mo:02d}{d:02d}"
                    race_date = f"{y:04d}-{mo:02d}-{d:02d}"
            continue   # ヘッダー行はまだレースデータなし

        # ---- レースヘッダー行 (全角: "　１Ｒ") ----------------------
        m = _B_RACE_HDR_RE.match(line)
        if m:
            race_no    = int(m.group(1).translate(_FW_DIGIT_TABLE))
            after_sep  = False
            boat_count = 0
            continue

        # ---- セパレータ行 (------...) --------------------------------
        if _SEP_RE.match(line):
            if race_no is not None:
                after_sep = True
            continue

        # ---- 艇データ行 (セパレータ後、最大6艇) ----------------------
        if not (after_sep and race_no is not None and boat_count < 6):
            continue

        # 空行 → 艇セクション終了
        if not line.strip():
            if boat_count > 0:
                after_sep = False
            continue

        # カラムヘッダー行はスキップ (艇番は 1-6 の ASCII 数字で始まる)
        if not (len(line) > 1 and line[0] in "123456" and line[1] == " "):
            continue

        # 1 行正規表現でパース
        # ※ split() は全角スペース(U+3000)を区切り文字として扱うため不使用
        m = _ROW_RE.match(line)
        if m is None:
            logger.debug(
                "program_file: row regex unmatched (venue=%s race%d): %r",
                venue_code, race_no, line[:60],
            )
            continue

        try:
            boat_no        = int(m.group(1))
            racer_id       = int(m.group(2))
            racer_grade    = m.group(3)              # "A1" / "A2" / "B1" / "B2"
            racer_win_rate = float(m.group(4))
            motor_win_rate = float(m.group(5))
            boat_win_rate  = float(m.group(6))

            race_id = f"{venue_code:02d}{date_str}{race_no:02d}"

            yield {
                "race_id":        race_id,
                "stadium_id":     venue_code,
                "race_date":      race_date,
                "race_no":        race_no,
                "boat_no":        boat_no,
                "racer_id":       racer_id,
                "racer_grade":    racer_grade,
                "racer_win_rate": racer_win_rate,
                "motor_win_rate": motor_win_rate,
                "boat_win_rate":  boat_win_rate,
            }
            boat_count += 1

        except (ValueError, IndexError) as exc:
            logger.debug("program_file: parse error: %s — %r", exc, line[:60])


# ---------------------------------------------------------------------------
# まとめて読み込み
# ---------------------------------------------------------------------------

def _fetch_day_program(
    year: int, month: int, day: int,
    save_dir: Path, tmpdir: Path,
) -> list[dict]:
    """1 日分の B ファイルをダウンロード・パースして records を返す。"""
    try:
        lzh = download_day_data(year, month, day, dest_dir=save_dir)
        if lzh is None:
            return []
        extract_dir = tmpdir / lzh.stem
        files = extract_lzh(lzh, extract_dir)
        return [rec for f in files for rec in parse_program_file(f)]
    except Exception as exc:
        logger.debug("Skip program %d-%02d-%02d: %s", year, month, day, exc)
        return []


def load_program_month(
    year: int, month: int,
    save_dir: Path | None = None,
    tmpdir: Path | None = None,
    max_workers: int = 8,
) -> pd.DataFrame:
    """
    指定月の B ファイルを並列ダウンロード・パースして DataFrame を返す。

    Parameters
    ----------
    year, month  : 対象年月
    save_dir     : LZH キャッシュ先 (None = data/program/)
    tmpdir       : 展開用一時ディレクトリ (None = 自動生成・自動削除)
    max_workers  : 並列ダウンロード数
    """
    import calendar

    _save_dir = save_dir or DATA_DIR
    _save_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today()
    days = [
        d for d in range(1, calendar.monthrange(year, month)[1] + 1)
        if datetime.date(year, month, d) <= today
    ]

    own_tmpdir = tmpdir is None
    _tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_prog_")) if own_tmpdir else tmpdir

    records: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_day_program, year, month, d, _save_dir, _tmpdir): d
                for d in days
            }
            for future in as_completed(futures):
                records.extend(future.result())
    finally:
        if own_tmpdir:
            shutil.rmtree(_tmpdir, ignore_errors=True)

    df = pd.DataFrame(records) if records else pd.DataFrame()
    logger.info("Program data: %d records for %d-%02d", len(df), year, month)
    return df


def load_program_range(
    start_year: int = 2022,
    end_year: int | None = None,
    start_month: int = 1,
    end_month: int | None = None,
    data_dir: Path | None = None,
    max_workers: int = 8,
) -> pd.DataFrame:
    """
    指定年月範囲の B ファイルを全てダウンロード・パースして DataFrame を返す。

    Parameters
    ----------
    start_year, end_year   : 開始・終了年 (end_year=None で今年まで)
    start_month, end_month : 開始・終了月 (end_month=None で 12 月まで)
    data_dir               : LZH キャッシュ先
    max_workers            : 並列ダウンロード数
    """
    if end_year is None:
        end_year = datetime.date.today().year
    if end_month is None:
        end_month = 12

    _save_dir = data_dir or DATA_DIR
    _save_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today()
    records: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_prog_"))

    try:
        for year in range(start_year, end_year + 1):
            m_start = start_month if year == start_year else 1
            m_end   = end_month   if year == end_year   else 12
            for month in range(m_start, m_end + 1):
                if datetime.date(year, month, 1) > today:
                    break
                month_df = load_program_month(
                    year, month,
                    save_dir=_save_dir,
                    tmpdir=tmpdir,
                    max_workers=max_workers,
                )
                if not month_df.empty:
                    records.extend(month_df.to_dict("records"))
                    logger.info(
                        "Program %d-%02d: +%d records (total %d)",
                        year, month, len(month_df), len(records),
                    )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    df = pd.DataFrame(records) if records else pd.DataFrame()
    logger.info("Program range total: %d records", len(df))
    return df


# ---------------------------------------------------------------------------
# マージヘルパー
# ---------------------------------------------------------------------------

# B ファイルから得られる列で K ファイルの None 列を置き換える
_PROGRAM_COLS = ["racer_win_rate", "motor_win_rate", "boat_win_rate", "racer_grade"]


def merge_program_data(df_k: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
    """
    K ファイルデータ (df_k) に B ファイルの出走表データ (df_b) をマージする。

    race_id + boat_no で左結合し、B ファイルから
      racer_win_rate, motor_win_rate, boat_win_rate, racer_grade
    を補完する。B ファイルに対応レコードがない行は None のまま
    （feature_builder.py の fillna(0) で 0 に変換される）。

    Parameters
    ----------
    df_k : K ファイル由来の DataFrame (finish_position 列を含む)
    df_b : load_program_month / load_program_range の返り値
    """
    if df_b.empty:
        logger.warning("B file data is empty — program features will be 0-filled")
        return df_k

    # K ファイル側の None 列を削除してから B ファイルの実値で補完
    drop_cols = [c for c in _PROGRAM_COLS if c in df_k.columns]
    df = df_k.drop(columns=drop_cols)

    b_cols = ["race_id", "boat_no"] + [c for c in _PROGRAM_COLS if c in df_b.columns]
    df = df.merge(df_b[b_cols], on=["race_id", "boat_no"], how="left")

    matched = df["racer_grade"].notna().sum() if "racer_grade" in df.columns else 0
    logger.info(
        "merge_program_data: %d / %d rows matched with B file data",
        matched, len(df),
    )
    return df
