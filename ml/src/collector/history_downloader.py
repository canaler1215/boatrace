"""
mbrace.or.jp から競走成績データ（K ファイル）をダウンロード・パースする

データソース:
  https://www1.mbrace.or.jp/od2/K/dindex.html
  日次 LZH ファイル (2012年〜) / 全24場分の成績が1ファイルに格納

URL パターン:
  https://www1.mbrace.or.jp/od2/K/{YYYYMM}/k{YY}{MM}{DD}.lzh
  例: https://www1.mbrace.or.jp/od2/K/202604/k260401.lzh

K ファイル CSV フォーマット (Shift-JIS, タブ or スペース区切り):
  各レースは「レースヘッダー行 + 6 艇行」の計 7 行で構成される。

  ヘッダー行:
    [0] 場コード          (2 桁, 01-24)
    [1] 年月日            (8 桁, YYYYMMDD)
    [2] レース番号        (1-2 桁, 1-12)
    [3] 1 着艇番
    [4] 2 着艇番
    [5] 3 着艇番
    [6] 4 着艇番
    [7] 5 着艇番
    [8] 6 着艇番
    [9] 天候              (1: 晴, 2: 曇, 3: 雨, 4: 霧, 5: 雪)
    [10] 風向             (1-16)
    [11] 風速 (m)
    [12] 水面
    [13] 波高 (cm)
    [14以降] 配当情報 (3連単, 3連複, etc.) ※今回は使用しない

  艇行 (艇番 1〜6 の順に 6 行):
    [0]  艇番             (1-6)
    [1]  登録番号         (4 桁)
    [2]  選手名           (姓名, スペース区切り)
    [3]  支部
    [4]  体重 (kg)
    [5]  F 数
    [6]  L 数
    [7]  平均 ST          (小数点なし 4 桁, 例: 0180 → 0.18)
    [8]  全国勝率         (小数点なし 4 桁, 例: 0650 → 6.50)
    [9]  全国 2 連率
    [10] 当地勝率
    [11] 当地 2 連率
    [12] モーター番号
    [13] モーター 2 連率
    [14] ボート番号
    [15] ボート 2 連率
    [16] 展示タイム       (小数点なし 4 桁, 例: 0685 → 6.85)
    [17] チルト角度
    [18] スタートタイミング (符号付き 3 桁, 例: 015 → 0.15, -01 → フライング)
    [19] 着順

  ※ 列位置はファイルの実態に合わせて _BOAT_COLS で調整可。
"""
import datetime
import logging
import shutil
import subprocess
import tempfile
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

# 天候コード
WEATHER_MAP = {"1": "晴", "2": "曇", "3": "雨", "4": "霧", "5": "雪"}


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
    """LZH ファイルを展開してファイルリストを返す。lhasa が必要。"""
    extract_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("lhasa"):
        raise RuntimeError(
            "lhasa コマンドが見つかりません。"
            "Ubuntu: sudo apt-get install -y lhasa"
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
# CSV パース
# ---------------------------------------------------------------------------

def parse_result_file(filepath: Path) -> Iterator[dict]:
    """
    K ファイルの CSV を 1 レコード (= 1 艇 × 1 レース) ずつ yield する。
    """
    try:
        text = filepath.read_text(encoding="cp932", errors="replace")
    except Exception:
        text = filepath.read_text(encoding="utf-8", errors="replace")

    lines = [l.rstrip("\r\n") for l in text.splitlines()]

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        cols = _split(line)

        # --- レースヘッダー行の判定 ---
        # [0]=場コード(2桁), [1]=YYYYMMDD(8桁), [2]=レース番号
        if len(cols) < 9:
            i += 1
            continue

        if not (_is_venue(cols[0]) and _is_date(cols[1]) and _is_raceno(cols[2])):
            i += 1
            continue

        venue = int(cols[0])
        date_str = cols[1]
        race_no = int(cols[2])
        race_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        race_id = f"{venue:02d}{date_str}{race_no:02d}"

        # 着順 (ヘッダーの [3]〜[8])
        finish_order: dict[int, int] = {}
        for pos, idx in enumerate(range(3, 9), start=1):
            if idx < len(cols) and cols[idx].isdigit():
                boat = int(cols[idx])
                if 1 <= boat <= 6:
                    finish_order[boat] = pos

        # 気象 ([9][10][11][12][13])
        weather    = WEATHER_MAP.get(cols[9],  cols[9])  if len(cols) > 9  else None
        wind_dir   = _safe_int(cols[10])                  if len(cols) > 10 else None
        wind_speed = _safe_float(cols[11])                if len(cols) > 11 else None
        wave_h     = _safe_float(cols[13])                if len(cols) > 13 else None

        # --- 続く 6 行が艇データ ---
        boat_rows_found = 0
        for k in range(1, 7):
            if i + k >= len(lines):
                break
            bcols = _split(lines[i + k])
            rec = _parse_boat_cols(bcols)
            if rec is None:
                continue
            rec.update({
                "race_id":       race_id,
                "stadium_id":    venue,
                "race_date":     race_date,
                "race_no":       race_no,
                "finish_position": finish_order.get(rec["boat_no"]),
                "weather":       weather,
                "wind_direction": wind_dir,
                "wind_speed":    wind_speed,
                "wave_height":   wave_h,
            })
            # ヘッダーの着順リストを優先し、艇行の着順で補完
            if rec["finish_position"] is None and rec.get("finish_position_boat"):
                rec["finish_position"] = rec.pop("finish_position_boat")
            else:
                rec.pop("finish_position_boat", None)
            yield rec
            boat_rows_found += 1

        i += 1 + max(boat_rows_found, 6)


def _split(line: str) -> list[str]:
    if "\t" in line:
        return line.split("\t")
    return line.split()


def _is_venue(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 24

def _is_date(s: str) -> bool:
    return len(s) == 8 and s.isdigit() and s[:4] in [str(y) for y in range(2002, 2030)]

def _is_raceno(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 12


def _parse_boat_cols(cols: list[str]) -> dict | None:
    """艇行をパース。失敗時は None。"""
    if len(cols) < 8:
        return None
    try:
        boat_no = int(cols[0])
        if boat_no < 1 or boat_no > 6:
            return None
        racer_id    = int(cols[1])  if len(cols) > 1 and cols[1].isdigit() else None
        grade       = cols[3].strip() if len(cols) > 3 else None  # 支部の前が名前
        win_rate    = _parse_rate4(cols[8])  if len(cols) > 8  else None
        motor_rate  = _parse_rate4(cols[13]) if len(cols) > 13 else None
        boat_rate   = _parse_rate4(cols[15]) if len(cols) > 15 else None
        ex_time     = _parse_rate4(cols[16]) if len(cols) > 16 else None
        st          = _parse_st(cols[18])    if len(cols) > 18 else None
        fin_pos_raw = int(cols[19]) if len(cols) > 19 and cols[19].isdigit() else None
        return {
            "boat_no":             boat_no,
            "racer_id":            racer_id,
            "racer_grade":         grade,
            "racer_win_rate":      win_rate,
            "motor_win_rate":      motor_rate,
            "boat_win_rate":       boat_rate,
            "exhibition_time":     ex_time,
            "start_timing":        st,
            "finish_position_boat": fin_pos_raw,
        }
    except (ValueError, IndexError):
        return None


def _parse_rate4(s: str) -> float | None:
    """4 桁整数レート → float (0650 → 6.50)"""
    s = s.strip()
    if not s or not s.isdigit():
        return None
    return int(s) / 100.0


def _parse_st(s: str) -> float | None:
    """ST 変換 ('015' → 0.15, '-01' → -0.01 フライング)"""
    s = s.strip()
    if not s:
        return None
    try:
        return int(s) / 100.0
    except ValueError:
        return None


def _safe_int(s: str) -> int | None:
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return None


def _safe_float(s: str) -> float | None:
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# まとめて読み込み
# ---------------------------------------------------------------------------

def load_history_range(
    start_year: int = 2022,
    end_year: int | None = None,
    data_dir: Path | None = None,
) -> pd.DataFrame:
    """
    指定年範囲の全データをダウンロード・パースして DataFrame を返す。

    Parameters
    ----------
    start_year : 開始年 (2012 以降)
    end_year   : 終了年 (None = 今年)
    data_dir   : ダウンロード先 (None = ml/data/history/)
    """
    if end_year is None:
        end_year = datetime.date.today().year

    save_dir  = data_dir or DATA_DIR
    records: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_k_"))

    today = datetime.date.today()

    try:
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                # 未来月はスキップ
                if datetime.date(year, month, 1) > today:
                    break
                days_in_month = (
                    datetime.date(year, month % 12 + 1, 1) - datetime.timedelta(days=1)
                ).day if month < 12 else 31

                month_records = 0
                for day in range(1, days_in_month + 1):
                    if datetime.date(year, month, day) > today:
                        break
                    try:
                        lzh = download_day_data(year, month, day, dest_dir=save_dir)
                        if lzh is None:
                            continue  # 開催なし
                        extract_dir = tmpdir / lzh.stem
                        csvs = extract_lzh(lzh, extract_dir)
                        for f in csvs:
                            for rec in parse_result_file(f):
                                records.append(rec)
                                month_records += 1
                    except Exception as exc:
                        logger.debug("Skip %d-%02d-%02d: %s", year, month, day, exc)

                if month_records:
                    logger.info("%d-%02d: +%d records (total %d)", year, month, month_records, len(records))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    df = pd.DataFrame(records) if records else pd.DataFrame()
    logger.info("Total records loaded: %d", len(df))
    return df
