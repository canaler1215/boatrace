"""
mbrace.or.jp から競走成績データ（K ファイル）をダウンロード・パースする

データソース:
  https://www1.mbrace.or.jp/od2/K/dindex.html
  日次 LZH ファイル (2012年〜) / 全24場分の成績が1ファイルに格納

URL パターン:
  https://www1.mbrace.or.jp/od2/K/{YYYYMM}/k{YY}{MM}{DD}.lzh
  例: https://www1.mbrace.or.jp/od2/K/202604/k260401.lzh

K ファイル フォーマット (Shift-JIS 固定幅テキスト):
  複数の会場ブロックが 1 ファイルに格納される。
  各会場ブロックは {JCD}KBGN 〜 {JCD}KEND で囲まれる。

  ブロック先頭のヘッダーに「YYYY/ M/ D」形式で開催日が含まれる。

  各レースのセクション:
    ・レースヘッダー行 (2〜6スペース後に "{race_no}R" が続く):
        例: "   1R       一般　　　　   H1800m  晴　  風  北西　 1m  波　  1cm"
    ・カラムヘッダー行
    ・セパレータ行 ("---..." が10文字以上)
    ・6艇分の結果行 (着順順):
        "  01  1 4966 田　川　　大　貴 47   64  6.84   1    0.12     1.55.0"
        フィールド (line.split() で分割):
          [0] 着順   ('01'-'06', 'S0'=スタート, 'F0'=フライング, etc.)
          [1] 艇番   (1-6)
          [2] 登録番号 (4桁)
          [3] 選手名  (全角スペース区切り → split()では1トークン)
          [4] モーター番号
          [5] ボート番号 (機材)
          [6] 展示タイム
          [7] 進入コース (1-6)
          [8] スタートタイミング
          [9] レースタイム (DNF は '.' など)
"""
import datetime
import logging
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www1.mbrace.or.jp/od2/K"
DATA_DIR = Path(__file__).parents[3] / "data" / "history"
REQUEST_INTERVAL = 0.5   # 礼儀正しいクロール間隔 (秒)
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BoatracePredictor/1.0)",
    "Accept-Language": "ja",
    "Referer": "https://www1.mbrace.or.jp/od2/K/dindex.html",
}

# 正規表現
_KBGN_RE    = re.compile(r'^(\d{2})KBGN')
_KEND_RE    = re.compile(r'^\d{2}KEND')
_DATE_RE    = re.compile(r'(\d{4})/\s*(\d{1,2})/\s*(\d{1,2})')
_RACE_HDR_RE = re.compile(r'^\s{2,6}(\d{1,2})R\s')   # 2〜6スペース後に "NR " (払戻行は11スペース超)
_SEP_RE     = re.compile(r'^-{10,}')

# 風向の日本語表記 → 数値エンコーディング (feature_builder.py の 1=北 … 16=北北西 と対応)
_WIND_DIR_MAP: dict[str, int] = {
    "北": 1, "北北東": 2, "北東": 3, "東北東": 4,
    "東": 5, "東南東": 6, "南東": 7, "南南東": 8,
    "南": 9, "南南西": 10, "南西": 11, "西南西": 12,
    "西": 13, "西北西": 14, "北西": 15, "北北西": 16,
}


# ---------------------------------------------------------------------------
# ダウンロード
# ---------------------------------------------------------------------------

def _make_url(year: int, month: int, day: int) -> str:
    """URL を生成する。年は 2 桁 (2026 → 26)"""
    yy = year % 100
    yyyymm = f"{year}{month:02d}"
    filename = f"k{yy:02d}{month:02d}{day:02d}.lzh"
    return f"{BASE_URL}/{yyyymm}/{filename}"


def download_day_data(
    year: int, month: int, day: int, dest_dir: Path | None = None
) -> Path | None:
    """
    指定日の K ファイルをダウンロードして保存する。
    開催がない日は None を返す。
    """
    import time

    save_dir = dest_dir or DATA_DIR
    save_dir.mkdir(parents=True, exist_ok=True)

    yy = year % 100
    filename = f"k{yy:02d}{month:02d}{day:02d}.lzh"
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
        return None  # 開催なし → スキップ

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
# LZH 展開
# ---------------------------------------------------------------------------

def extract_lzh(lzh_path: Path, extract_dir: Path) -> list[Path]:
    """LZH ファイルを展開してファイルリストを返す。

    優先順位:
      1. lhafile (pip install lhafile) — Windows/Linux/macOS で動作する Python 実装
      2. lhasa コマンド — Linux/WSL での従来の方法
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        import lhafile
        lha = lhafile.LhaFile(str(lzh_path))
        for name in lha.namelist():
            data = lha.read(name)
            out_path = extract_dir / Path(name).name
            out_path.write_bytes(data)
        return [f for f in extract_dir.rglob("*") if f.is_file()]
    except ImportError:
        pass

    if not shutil.which("lhasa"):
        raise RuntimeError(
            "LZH 展開に失敗しました。以下のいずれかをインストールしてください:\n"
            "  pip install lhafile          # Windows/Linux/macOS 共通（推奨）\n"
            "  sudo apt-get install lhasa   # Linux/WSL のみ"
        )

    result = subprocess.run(
        ["lhasa", "e", str(lzh_path)],
        cwd=str(extract_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"lhasa failed ({lzh_path.name}): {result.stderr[:200]}")

    return [f for f in extract_dir.rglob("*") if f.is_file()]


# ---------------------------------------------------------------------------
# テキストパース (実際のKファイル形式: 固定幅テキスト、Shift-JIS)
# ---------------------------------------------------------------------------

def parse_result_file(filepath: Path) -> Iterator[dict]:
    """
    K ファイルを 1 レコード (= 1 艇 × 1 レース) ずつ yield する。

    ファイル構造:
      {JCD}KBGN  … 会場ブロック開始
      ヘッダー (日付を含む)
      各レースセクション (レースヘッダー → 区切り線 → 6艇行)
      {JCD}KEND  … 会場ブロック終了
    """
    try:
        text = filepath.read_text(encoding="cp932", errors="replace")
    except Exception:
        text = filepath.read_text(encoding="utf-8", errors="replace")

    lines = [l.rstrip("\r\n") for l in text.splitlines()]

    venue_code:     int | None   = None
    date_str:       str | None   = None   # "YYYYMMDD"
    race_date:      str | None   = None   # "YYYY-MM-DD"
    race_no:        int | None   = None
    weather:        str | None   = None
    wind_direction: int | None   = None
    wind_speed:     float | None = None
    wave_height:    float | None = None
    after_sep:      bool         = False
    boat_count:     int          = 0

    for line in lines:

        # ---- 会場ブロック開始 ----------------------------------------
        m = _KBGN_RE.match(line)
        if m:
            venue_code = int(m.group(1))
            date_str   = None
            race_date  = None
            race_no    = None
            after_sep  = False
            boat_count = 0
            continue

        # ---- 会場ブロック終了 ----------------------------------------
        if _KEND_RE.match(line):
            venue_code = None
            continue

        if venue_code is None:
            continue

        # ---- 日付検出 (ヘッダー内にある "YYYY/ M/ D" を探す) --------
        if date_str is None:
            m = _DATE_RE.search(line)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 2010 <= y <= 2030:
                    date_str  = f"{y:04d}{mo:02d}{d:02d}"
                    race_date = f"{y:04d}-{mo:02d}-{d:02d}"
            continue   # ヘッダー行はまだレースデータなし

        # ---- レースヘッダー行 ----------------------------------------
        # 2〜6スペース + 数字(1-2桁) + "R" + 空白
        # 払戻行 ("           1R  1-5-3 ...") は先頭スペースが多く非マッチ
        m = _RACE_HDR_RE.match(line)
        if m:
            race_no        = int(m.group(1))
            after_sep      = False
            boat_count     = 0
            weather        = None
            wind_direction = None
            wind_speed     = None
            # 天候
            for w in ("晴", "曇", "雨", "霧", "雪"):
                if w in line:
                    weather = w
                    break
            # 風向・風速 ("風  北西　 1m" パターン)
            # [\s\u3000]* で ASCII スペースと全角スペースの両方に対応
            wm = re.search(r"風[\s\u3000]*([\u4E00-\u9FFF]+)[\s\u3000]*(\d+(?:\.\d+)?)m", line)
            if wm:
                wind_direction = _WIND_DIR_MAP.get(wm.group(1))
                try:
                    wind_speed = float(wm.group(2))
                except ValueError:
                    pass
            # 波高 ("波　  1cm" パターン、cm 単位 float)
            hm = re.search(r"波[\s　]*(\d+(?:\.\d+)?)cm", line)
            if hm:
                try:
                    wave_height = float(hm.group(1))
                except ValueError:
                    pass
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

        # Python の split() は全角スペース (U+3000) を分割しない。
        # よって "田　川　　大　貴" は 1 トークンとして扱われる。
        cols = line.split()

        # 最低限: [着順][艇番][登番][名前][モーター][ボート][展示][進入][ST]
        if len(cols) < 9:
            after_sep = False
            continue

        finish_field = cols[0]   # '01'-'06', 'S0', 'F0', etc.
        if len(finish_field) != 2:
            after_sep = False
            continue

        try:
            boat_no = int(cols[1])
            if not (1 <= boat_no <= 6):
                after_sep = False
                continue

            # 登録番号は4桁数字
            if not (cols[2].isdigit() and len(cols[2]) == 4):
                after_sep = False
                continue
            racer_id = int(cols[2])

            # 選手名は姓・名それぞれが半角スペース区切りのため複数トークン
            # (例: "田 川 大 貴" = 4トークン, "村 上 遼" = 3トークン)
            # 固定位置での列アクセスは不可のため、末尾から読む:
            #   完走: [..., モータ, ボート, 展示, 進入, ST, レースタイム]
            #   不完走: [..., モータ, ボート, 展示, 進入, ST, '.', '.']
            if cols[-1] == ".":
                # DNF / 失格 → 末尾2つが "." "."
                ex_time  = float(cols[-5])
                st_str   = cols[-3]
            else:
                # 完走
                ex_time  = float(cols[-4])
                st_str   = cols[-2]

            start_timing = float(st_str) if st_str not in (".", "") else None
            finish_pos = int(finish_field) if finish_field.isdigit() else None

            race_id = f"{venue_code:02d}{date_str}{race_no:02d}"

            yield {
                "race_id":         race_id,
                "stadium_id":      venue_code,
                "race_date":       race_date,
                "race_no":         race_no,
                "boat_no":         boat_no,
                "racer_id":        racer_id,
                # K ファイルには勝率・級別なし (B ファイルに格納)
                "racer_win_rate":  None,
                "motor_win_rate":  None,
                "boat_win_rate":   None,
                "racer_grade":     None,
                "exhibition_time": ex_time,
                "start_timing":    start_timing,
                "finish_position": finish_pos,
                "weather":         weather,
                "wind_direction":  wind_direction,
                "wind_speed":      wind_speed,
                "wave_height":     wave_height,
            }
            boat_count += 1

        except (ValueError, IndexError):
            pass   # パース失敗は無視して継続


# ---------------------------------------------------------------------------
# まとめて読み込み
# ---------------------------------------------------------------------------

def load_history_range(
    start_year: int = 2022,
    end_year: int | None = None,
    start_month: int = 1,
    end_month: int | None = None,
    data_dir: Path | None = None,
    max_workers: int = 8,
) -> pd.DataFrame:
    """
    指定年月範囲の全データをダウンロード・パースして DataFrame を返す。

    Parameters
    ----------
    start_year  : 開始年 (2012 以降)
    end_year    : 終了年 (None = 今年)
    start_month : 開始月 1-12 (start_year 内の開始月, デフォルト 1)
    end_month   : 終了月 1-12 (end_year 内の終了月, None = 12)
    data_dir    : ダウンロード先 (None = ml/data/history/)
    max_workers : 日ごとのダウンロード並列数（デフォルト: 8）
    """
    if end_year is None:
        end_year = datetime.date.today().year
    if end_month is None:
        end_month = 12

    save_dir = data_dir or DATA_DIR
    records: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_k_"))
    today = datetime.date.today()

    def _fetch_day(year: int, month: int, day: int) -> list[dict]:
        try:
            lzh = download_day_data(year, month, day, dest_dir=save_dir)
            if lzh is None:
                return []
            extract_dir = tmpdir / lzh.stem
            csvs = extract_lzh(lzh, extract_dir)
            return [rec for f in csvs for rec in parse_result_file(f)]
        except Exception as exc:
            logger.debug("Skip %d-%02d-%02d: %s", year, month, day, exc)
            return []

    try:
        for year in range(start_year, end_year + 1):
            month_start = start_month if year == start_year else 1
            month_end   = end_month   if year == end_year   else 12
            for month in range(month_start, month_end + 1):
                # 未来月はスキップ
                if datetime.date(year, month, 1) > today:
                    break
                days_in_month = (
                    datetime.date(year, month % 12 + 1, 1) - datetime.timedelta(days=1)
                ).day if month < 12 else 31

                days = [
                    d for d in range(1, days_in_month + 1)
                    if datetime.date(year, month, d) <= today
                ]

                month_records: list[dict] = []
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(_fetch_day, year, month, d): d for d in days}
                    for future in as_completed(futures):
                        month_records.extend(future.result())

                records.extend(month_records)
                if month_records:
                    logger.info(
                        "%d-%02d: +%d records (total %d)",
                        year, month, len(month_records), len(records),
                    )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    df = pd.DataFrame(records) if records else pd.DataFrame()
    logger.info("Total records loaded: %d", len(df))
    return df
