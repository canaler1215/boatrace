"""
boatrace.jp からレース情報・出走表・直前情報・オッズを取得する

boatrace.jp エンドポイント (HTML スクレイピング):
  /owpc/pc/race/index      - 開催場一覧
  /owpc/pc/race/racelist   - 競艇場のレース一覧  ?hd=YYYYMMDD&jcd=XX
  /owpc/pc/race/racerslist - 出走表              ?hd=YYYYMMDD&jcd=XX&rno=N
  /owpc/pc/race/beforeinfo - 直前情報(展示・ST)   ?hd=YYYYMMDD&jcd=XX&rno=N
  /owpc/pc/race/odds3t     - 3連単オッズ         ?hd=YYYYMMDD&jcd=XX&rno=N
  /owpc/pc/race/raceresult - レース結果          ?hd=YYYYMMDD&jcd=XX&rno=N

注: HTML 構造は boatrace.jp のサイトリニューアルにより変わる場合がある。
    CSS セレクタは実際の HTML を確認して適宜調整すること。
"""
import logging
import re
import threading
import time
import warnings
from typing import Any

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

BASE_URL = "https://boatrace.jp/owpc/pc/race"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BoatracePredictor/1.0; +https://github.com/canaler1215/boatrace)",
    "Accept-Language": "ja,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml",
}
# 並列ダウンロード時のスレッド間レート制限 (秒)
# boatrace.jp の実測レスポンスタイムは ~9-10 秒/リクエストのため、
# 同時接続数を制御することで礼儀正しい並列アクセスを実現する
REQUEST_INTERVAL = 0.5


class _RateLimiter:
    """スレッドセーフなレート制限器: 全スレッド合計でインターバルを保証"""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._last: float = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


_rate_limiter = _RateLimiter(REQUEST_INTERVAL)


# ---------------------------------------------------------------------------
# 内部ユーティリティ
# ---------------------------------------------------------------------------

def _get(endpoint: str, params: dict[str, str]) -> BeautifulSoup:
    """GET リクエスト + グローバルレート制限（並列対応）"""
    _rate_limiter.wait()
    url = f"{BASE_URL}/{endpoint}"
    logger.debug("GET %s %s", url, params)
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "lxml")


def _hd(race_date: str) -> str:
    """YYYY-MM-DD → YYYYMMDD"""
    return race_date.replace("-", "")


def _parse_float(text: str) -> float | None:
    """テキストを float に変換。変換不能なら None"""
    s = text.strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def make_race_id(stadium_id: int, race_date: str, race_no: int) -> str:
    """race_id 生成: {jcd:02d}{yyyymmdd}{rno:02d} 例: 012024120901"""
    return f"{stadium_id:02d}{_hd(race_date)}{race_no:02d}"


# ---------------------------------------------------------------------------
# 開催情報
# ---------------------------------------------------------------------------

def fetch_race_list(race_date: str) -> list[dict[str, Any]]:
    """
    指定日に開催しているすべての競艇場のレース一覧を返す。

    Returns:
        list of {id, stadium_id, race_date, race_no, grade, status}
    """
    hd = _hd(race_date)
    races: list[dict[str, Any]] = []

    # --- step1: index ページで開催場を特定 ---
    jcds_open: set[int] = set()
    try:
        soup = _get("index", {"hd": hd})
        # 開催場へのリンク例: href="/owpc/pc/race/racelist?hd=20240101&jcd=01"
        for a in soup.find_all("a", href=True):
            m = re.search(r"racelist\?hd=" + hd + r"&jcd=(\d{2})", a["href"])
            if m:
                jcds_open.add(int(m.group(1)))
        logger.info("Open venues on %s: %s", race_date, sorted(jcds_open))
    except Exception as exc:
        logger.warning("Could not fetch index page: %s – scanning all 24 venues", exc)
        jcds_open = set(range(1, 25))

    # --- step2: 各開催場のレース一覧を取得 ---
    for jcd in sorted(jcds_open):
        try:
            venue_races = _fetch_venue_races(jcd, race_date, hd)
            races.extend(venue_races)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue
            logger.warning("venue %02d HTTP error: %s", jcd, exc)
        except Exception as exc:
            logger.warning("venue %02d: %s", jcd, exc)

    logger.info("Total races on %s: %d", race_date, len(races))
    return races


def _fetch_venue_races(jcd: int, race_date: str, hd: str) -> list[dict[str, Any]]:
    """1競艇場のレース一覧を取得"""
    soup = _get("racelist", {"hd": hd, "jcd": f"{jcd:02d}"})
    races: list[dict[str, Any]] = []

    # レース番号リンク例: href="...&rno=1" のテキストが "1R"
    seen: set[int] = set()
    for a in soup.find_all("a", href=re.compile(r"rno=\d+")):
        m = re.search(r"rno=(\d+)", a["href"])
        if not m:
            continue
        race_no = int(m.group(1))
        if race_no < 1 or race_no > 12 or race_no in seen:
            continue
        seen.add(race_no)

        # グレード: リンクテキストまたは隣接する要素から取得 (省略可)
        grade = ""
        parent = a.find_parent("td") or a.find_parent("li")
        if parent:
            grade_span = parent.find("span", class_=re.compile(r"is-gradeColor"))
            if grade_span:
                grade = grade_span.get_text(strip=True)

        races.append({
            "id": make_race_id(jcd, race_date, race_no),
            "stadium_id": jcd,
            "race_date": race_date,
            "race_no": race_no,
            "grade": grade,
            "status": "scheduled",
        })

    logger.debug("venue %02d: %d races", jcd, len(races))
    return races


# ---------------------------------------------------------------------------
# 出走表
# ---------------------------------------------------------------------------

def fetch_entry_info(stadium_id: int, race_date: str, race_no: int) -> list[dict[str, Any]]:
    """
    出走表情報を取得。

    Returns:
        list of {race_id, boat_no, racer_id, motor_win_rate, boat_win_rate,
                 exhibition_time, start_timing, finish_position}
    """
    hd = _hd(race_date)
    soup = _get("racerslist", {"hd": hd, "jcd": f"{stadium_id:02d}", "rno": str(race_no)})
    race_id = make_race_id(stadium_id, race_date, race_no)
    entries: list[dict[str, Any]] = []

    # 出走表テーブル: 各行が1艇。
    # 典型的なカラム順 (boatrace.jp):
    #   0: 艇番  1: 登番  2: 氏名  3: 級別  4: 支部/出身  5: 体重
    #   6: F/L   7: ST平均  8: 全国勝率  9: 全国2連率
    #  10: 当地勝率  11: 当地2連率  12: モーター2連率  13: ボート2連率
    for tbody in soup.select(".table1 tbody, table.is-w243 tbody, table tbody"):
        for tr in tbody.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            try:
                boat_no = int(cells[0].get_text(strip=True))
                if boat_no < 1 or boat_no > 6:
                    continue

                # 登録番号 (4桁)
                racer_id_text = cells[1].get_text(strip=True)
                m = re.search(r"(\d{4})", racer_id_text)
                racer_id = int(m.group(1)) if m else None

                # 勝率・2連率 (列位置は実際のHTMLで要確認)
                win_rate      = _parse_float(cells[8].get_text(strip=True))  if len(cells) > 8  else None
                motor_win_rate = _parse_float(cells[12].get_text(strip=True)) if len(cells) > 12 else None
                boat_win_rate  = _parse_float(cells[13].get_text(strip=True)) if len(cells) > 13 else None

                entries.append({
                    "race_id": race_id,
                    "boat_no": boat_no,
                    "racer_id": racer_id,
                    "motor_win_rate": motor_win_rate,
                    "boat_win_rate": boat_win_rate,
                    "exhibition_time": None,   # beforeinfo で更新
                    "start_timing": None,       # beforeinfo で更新
                    "finish_position": None,
                })
            except (ValueError, AttributeError, IndexError):
                continue
        if entries:
            break  # 最初の tbody で十分

    logger.debug("race_id=%s entries=%d", race_id, len(entries))
    return entries


# ---------------------------------------------------------------------------
# 直前情報
# ---------------------------------------------------------------------------

def fetch_before_info(stadium_id: int, race_date: str, race_no: int) -> dict[int, dict[str, Any]]:
    """
    直前情報（展示タイム・ST）を取得。

    Returns:
        {boat_no: {"exhibition_time": float | None, "start_timing": float | None}}
    """
    hd = _hd(race_date)
    soup = _get("beforeinfo", {"hd": hd, "jcd": f"{stadium_id:02d}", "rno": str(race_no)})
    result: dict[int, dict[str, Any]] = {}

    # 直前情報テーブル: 各行が1艇。
    # 典型的なカラム順:
    #   0: 艇番  1: 氏名  2: 体重  3: 調整重量  4: 展示タイム  5: チルト  6: プロペラ  7: ST
    for tbody in soup.select(".table1 tbody, table.is-w495 tbody, table tbody"):
        for tr in tbody.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue
            try:
                boat_no = int(cells[0].get_text(strip=True))
                if boat_no < 1 or boat_no > 6:
                    continue
                exhibition_time = _parse_float(cells[4].get_text(strip=True)) if len(cells) > 4 else None
                start_timing    = _parse_float(cells[7].get_text(strip=True)) if len(cells) > 7 else None
                result[boat_no] = {
                    "exhibition_time": exhibition_time,
                    "start_timing": start_timing,
                }
            except (ValueError, AttributeError, IndexError):
                continue
        if result:
            break

    logger.debug("beforeinfo stadium=%02d rno=%d boats=%s", stadium_id, race_no, sorted(result))
    return result


# ---------------------------------------------------------------------------
# オッズ
# ---------------------------------------------------------------------------

def fetch_odds(stadium_id: int, race_date: str, race_no: int) -> dict[str, float]:
    """
    3連単オッズを取得。

    Returns:
        {"1-2-3": 12.5, "1-2-4": 18.0, ...}  全120通り
    """
    hd = _hd(race_date)
    soup = _get("odds3t", {"hd": hd, "jcd": f"{stadium_id:02d}", "rno": str(race_no)})
    odds_map: dict[str, float] = {}

    # ---- パターン1: data-combination 属性があるセル ----
    for td in soup.find_all("td", attrs={"data-combination": True}):
        combo = td["data-combination"]  # 例: "1-2-3"
        val = _parse_float(td.get_text(strip=True))
        if val and val > 0:
            odds_map[combo] = val

    if odds_map:
        logger.info("odds via data-combination: %d entries", len(odds_map))
        return odds_map

    # ---- パターン2: class="oddsPoint" セルから位置ベースでコンビネーション推定 ----
    # boatrace.jp の odds3t ページは td.oddsPoint が 1着→2着→3着 の順に
    # ちょうど 120 セル並ぶ。高オッズは "1467" のように整数形式で表示される。
    odds_cells = [td for td in soup.find_all("td") if "oddsPoint" in (td.get("class") or [])]
    float_values: list[float] = []
    for td in odds_cells:
        v = _parse_float(td.get_text(strip=True))
        if v is not None and v > 0:
            float_values.append(v)

    if len(float_values) == 120:
        idx = 0
        for first in range(1, 7):
            for second in range(1, 7):
                if first == second:
                    continue
                for third in range(1, 7):
                    if third == first or third == second:
                        continue
                    odds_map[f"{first}-{second}-{third}"] = float_values[idx]
                    idx += 1
        logger.info("odds via oddsPoint class: %d entries", len(odds_map))
    else:
        logger.warning(
            "Could not parse odds table: expected 120 oddsPoint cells, got %d",
            len(float_values),
        )

    return odds_map


# ---------------------------------------------------------------------------
# レース結果 (着順取得)
# ---------------------------------------------------------------------------

def fetch_race_result(stadium_id: int, race_date: str, race_no: int) -> dict[int, int]:
    """
    レース結果を取得。

    Returns:
        {boat_no: finish_position}  例: {1: 1, 3: 2, 5: 3, 2: 4, 4: 5, 6: 6}
    """
    hd = _hd(race_date)
    soup = _get("raceresult", {"hd": hd, "jcd": f"{stadium_id:02d}", "rno": str(race_no)})
    result: dict[int, int] = {}

    for tbody in soup.select(".table1 tbody, table tbody"):
        for i, tr in enumerate(tbody.find_all("tr"), start=1):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            try:
                # 着順テーブル: 0列=着順, 1列=艇番
                finish_pos = int(cells[0].get_text(strip=True))
                boat_no    = int(cells[1].get_text(strip=True))
                if 1 <= boat_no <= 6 and 1 <= finish_pos <= 6:
                    result[boat_no] = finish_pos
            except (ValueError, AttributeError, IndexError):
                continue
        if result:
            break

    logger.debug("raceresult stadium=%02d rno=%d: %s", stadium_id, race_no, result)
    return result
