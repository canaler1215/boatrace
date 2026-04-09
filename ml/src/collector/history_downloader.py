"""
boatrace.jp 公式サイトから歴史データ（2002年〜）をダウンロード・パースする

データソース:
  https://www.boatrace.jp/owpc/pc/extra/data/download.html
  月次 LZH ファイルに全場の結果 CSV が格納されている

CSV フォーマット (Shift-JIS, 固定長):
  各レースは「レースヘッダー行 + 6艇行」の 7 行で 1 ブロックを構成する。
  詳細は boatrace.jp 公式の「データ仕様書」参照。

  ヘッダー行 (1行):
    col 0   : 場コード          (2桁, 01-24)
    col 1   : 開催年月日        (8桁, YYYYMMDD)
    col 2   : レース番号        (2桁)
    col 3   : 天候              (1桁)
    col 4   : 風向              (2桁)
    col 5   : 風速              (2桁)
    col 6   : 水面              (1桁)
    col 7   : 波高              (3桁)
  艇行 (6行, 艇番1〜6の順):
    col 0   : 艇番              (1桁)
    col 1   : 登録番号          (4桁)
    col 2   : 級別              (2桁: A1/A2/B1/B2)
    col 3   : 選手名            (20桁, 空白パディング)
    col 4   : 体重              (2桁)
    col 5   : F数               (1桁)
    col 6   : L数               (1桁)
    col 7   : 平均ST            (4桁, 小数点なし, 例: 0180 → 0.18)
    col 8   : 全国勝率          (4桁, 小数点なし, 例: 0650 → 6.50)
    col 9   : 全国2連率         (4桁)
    col 10  : 当地勝率          (4桁)
    col 11  : 当地2連率         (4桁)
    col 12  : モーター番号      (2桁)
    col 13  : モーター2連率     (4桁)
    col 14  : ボート番号        (4桁)
    col 15  : ボート2連率       (4桁)
    col 16  : 展示タイム        (4桁, 例: 0680 → 6.80)
    col 17  : チルト角度        (3桁)
    col 18  : スタートタイミング (3桁, 例: 015 → 0.15)
    col 19  : 着順              (1桁)

注: 上記は一般的な形式に基づく推定。実際のファイルを確認して調整すること。
    Shift-JIS エンコーディング / タブ区切り or スペース区切りの場合もある。
"""
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

logger = logging.getLogger(__name__)

DOWNLOAD_BASE = "https://www.boatrace.jp/owpc/pc/extra/data/download"
DATA_DIR = Path(__file__).parents[3] / "data" / "history"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BoatracePredictor/1.0)",
    "Accept-Language": "ja",
    "Referer": "https://www.boatrace.jp/owpc/pc/extra/data/download.html",
}

# 天候コード
WEATHER_MAP = {"1": "晴", "2": "曇", "3": "雨", "4": "霧", "5": "雪"}
# 風向コード (1=北, 2=北北東, ... 16=北北西)
WIND_DIR_MAP = {str(i): i for i in range(1, 17)}


# ---------------------------------------------------------------------------
# ダウンロード
# ---------------------------------------------------------------------------

def download_month_data(year: int, month: int, dest_dir: Path | None = None) -> Path:
    """
    指定年月の LZH ファイルをダウンロードして保存する。

    URL 例: https://www.boatrace.jp/owpc/pc/extra/data/download?type=B&year=2024&month=01
    注: 実際の URL は boatrace.jp の仕様変更で変わることがある。
    """
    save_dir = dest_dir or DATA_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"b{year}{month:02d}.lzh"
    dest = save_dir / filename

    if dest.exists():
        logger.info("Already downloaded: %s", dest)
        return dest

    params = {"type": "B", "year": str(year), "month": f"{month:02d}"}
    logger.info("Downloading %d-%02d ...", year, month)
    resp = requests.get(
        DOWNLOAD_BASE, params=params, headers=REQUEST_HEADERS, timeout=60, stream=True
    )
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        raise ValueError(
            f"Expected binary file but got HTML. "
            f"Please verify the download URL: {resp.url}\n"
            f"Check https://www.boatrace.jp/owpc/pc/extra/data/download.html"
        )

    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)

    logger.info("Saved: %s (%.1f KB)", dest, dest.stat().st_size / 1024)
    return dest


# ---------------------------------------------------------------------------
# LZH 展開
# ---------------------------------------------------------------------------

def extract_lzh(lzh_path: Path, extract_dir: Path | None = None) -> list[Path]:
    """
    LZH ファイルを展開して、展開されたファイルのパスリストを返す。
    `lhasa` コマンドが必要 (Ubuntu: apt-get install lhasa)。
    """
    out_dir = extract_dir or lzh_path.parent / lzh_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("lhasa"):
        raise RuntimeError(
            "lhasa コマンドが見つかりません。"
            "Ubuntu: sudo apt-get install -y lhasa"
        )

    result = subprocess.run(
        ["lhasa", "e", str(lzh_path)],
        cwd=str(out_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"lhasa failed: {result.stderr}")

    extracted = list(out_dir.rglob("*"))
    files = [f for f in extracted if f.is_file()]
    logger.info("Extracted %d files from %s", len(files), lzh_path.name)
    return files


# ---------------------------------------------------------------------------
# CSV パース
# ---------------------------------------------------------------------------

def parse_result_csv(filepath: Path) -> Iterator[dict]:
    """
    結果 CSV を 1 レコード (= 1 艇 × 1 レース) ずつ yield する。

    Note: 実際のファイルを確認して col_*_pos 定数を調整すること。
    """
    try:
        lines = filepath.read_text(encoding="cp932", errors="replace").splitlines()
    except Exception:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        parts = _split_line(line)
        if len(parts) < 5:
            i += 1
            continue

        # --- ヘッダー行の判定: 8桁の数字 (YYYYMMDD) があれば日付列とみなす ---
        date_str = None
        venue_code = None
        race_no = None
        weather = None
        wind_dir = None
        wind_speed = None
        wave_height = None

        for j, p in enumerate(parts):
            if len(p) == 8 and p.isdigit() and p[:4] in [str(y) for y in range(2002, 2030)]:
                date_str = p
                venue_code = int(parts[j - 1]) if j > 0 and parts[j - 1].isdigit() else None
                if j + 1 < len(parts):
                    race_no_str = parts[j + 1].strip()
                    race_no = int(race_no_str) if race_no_str.isdigit() else None
                # 気象データ (ヘッダー行の後半)
                weather_parts = parts[j + 2:]
                if len(weather_parts) >= 4:
                    weather = WEATHER_MAP.get(weather_parts[0], weather_parts[0])
                    wind_dir = _safe_int(weather_parts[1])
                    wind_speed = _safe_float(weather_parts[2])
                    wave_height = _safe_float(weather_parts[3])
                break

        if date_str is None or venue_code is None or race_no is None:
            i += 1
            continue

        race_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        race_id = f"{venue_code:02d}{date_str}{race_no:02d}"

        # --- 続く 6 行が艇データ ---
        for k in range(1, 7):
            if i + k >= len(lines):
                break
            boat_line = lines[i + k].strip()
            if not boat_line:
                continue
            boat_parts = _split_line(boat_line)
            rec = _parse_boat_line(boat_parts)
            if rec is None:
                continue
            rec.update({
                "race_id": race_id,
                "stadium_id": venue_code,
                "race_date": race_date,
                "race_no": race_no,
                "weather": weather,
                "wind_direction": wind_dir,
                "wind_speed": wind_speed,
                "wave_height": wave_height,
            })
            yield rec

        i += 7  # ヘッダー1行 + 艇6行


def _split_line(line: str) -> list[str]:
    """タブまたはスペース区切りで分割"""
    if "\t" in line:
        return line.split("\t")
    return line.split()


def _parse_boat_line(parts: list[str]) -> dict | None:
    """艇行をパースして dict を返す。失敗時は None"""
    if len(parts) < 10:
        return None
    try:
        boat_no = int(parts[0])
        if boat_no < 1 or boat_no > 6:
            return None
        racer_id = int(parts[1]) if parts[1].isdigit() else None
        grade = parts[2].strip() if len(parts) > 2 else None
        # 各レートは 4 桁整数で格納 (例: 0650 → 6.50, 0180 → 0.180)
        win_rate         = _parse_rate(parts[8])  if len(parts) > 8  else None
        motor_win_rate   = _parse_rate(parts[13]) if len(parts) > 13 else None
        boat_win_rate    = _parse_rate(parts[15]) if len(parts) > 15 else None
        exhibition_time  = _parse_time(parts[16]) if len(parts) > 16 else None
        start_timing     = _parse_st(parts[18])   if len(parts) > 18 else None
        finish_position  = int(parts[19])          if len(parts) > 19 and parts[19].isdigit() else None
        return {
            "boat_no": boat_no,
            "racer_id": racer_id,
            "racer_grade": grade,
            "racer_win_rate": win_rate,
            "motor_win_rate": motor_win_rate,
            "boat_win_rate": boat_win_rate,
            "exhibition_time": exhibition_time,
            "start_timing": start_timing,
            "finish_position": finish_position,
        }
    except (ValueError, IndexError):
        return None


def _parse_rate(s: str) -> float | None:
    """4桁整数レート → float (例: '0650' → 6.50)"""
    s = s.strip()
    if not s or not s.isdigit():
        return None
    v = int(s)
    return v / 100.0


def _parse_time(s: str) -> float | None:
    """展示タイム変換 (例: '0680' → 6.80)"""
    return _parse_rate(s)


def _parse_st(s: str) -> float | None:
    """ST変換 (例: '015' → 0.15, '-01' → -0.01 フライング)"""
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
    start_year: int = 2020,
    end_year: int | None = None,
    data_dir: Path | None = None,
) -> pd.DataFrame:
    """
    指定年範囲の全データをダウンロード・パースして DataFrame を返す。

    Parameters
    ----------
    start_year : int
        開始年 (default: 2020 — 初期訓練では 2020 年以降で十分)
    end_year   : int | None
        終了年 (None = 今年)
    data_dir   : Path | None
        ダウンロード先 (None = ml/data/history/)

    Returns
    -------
    pd.DataFrame
        columns: race_id, stadium_id, race_date, race_no,
                 boat_no, racer_id, racer_grade, racer_win_rate,
                 motor_win_rate, boat_win_rate, exhibition_time,
                 start_timing, finish_position,
                 weather, wind_direction, wind_speed, wave_height
    """
    import datetime

    if end_year is None:
        end_year = datetime.date.today().year

    records: list[dict] = []
    tmpdir = Path(tempfile.mkdtemp())

    try:
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                if year == end_year and month > datetime.date.today().month:
                    break
                try:
                    lzh_path = download_month_data(year, month, dest_dir=data_dir or DATA_DIR)
                    csv_files = extract_lzh(lzh_path, extract_dir=tmpdir / f"{year}{month:02d}")
                    for f in csv_files:
                        for rec in parse_result_csv(f):
                            records.append(rec)
                    logger.info("%d-%02d: %d records so far", year, month, len(records))
                except Exception as exc:
                    logger.warning("Skip %d-%02d: %s", year, month, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    df = pd.DataFrame(records)
    logger.info("Total records loaded: %d", len(df))
    return df
