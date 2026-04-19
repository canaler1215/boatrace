"""
boatrace.jp からレース情報・出走表・直前情報・オッズを取得する

boatrace.jp エンドポイント (HTML スクレイピング):
  /owpc/pc/race/index      - 開催場一覧
  /owpc/pc/race/racelist   - 競艇場のレース一覧  ?hd=YYYYMMDD&jcd=XX
  /owpc/pc/race/racerslist - 出走表              ?hd=YYYYMMDD&jcd=XX&rno=N
  /owpc/pc/race/beforeinfo - 直前情報(展示・ST)   ?hd=YYYYMMDD&jcd=XX&rno=N
  /owpc/pc/race/odds3t     - 3連単オッズ         ?hd=YYYYMMDD&jcd=XX&rno=N
  /owpc/pc/race/odds3f     - 3連複オッズ         ?hd=YYYYMMDD&jcd=XX&rno=N
  /owpc/pc/race/raceresult - レース結果          ?hd=YYYYMMDD&jcd=XX&rno=N

注: HTML 構造は boatrace.jp のサイトリニューアルにより変わる場合がある。
    CSS セレクタは実際の HTML を確認して適宜調整すること。
"""
import itertools
import logging
import re
import threading
import time
import unicodedata
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
            href = a["href"]
            # パラメーター順序に依存しない検索 (例: ?rno=1&jcd=01&hd=20260412)
            if "racelist" in href and hd in href:
                m = re.search(r"jcd=(\d{2})", href)
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
    # 旧: racelist?hd=YYYYMMDD&jcd=XX → 新: raceindex?jcd=XX&hd=YYYYMMDD
    soup = _get("raceindex", {"jcd": f"{jcd:02d}", "hd": hd})
    races: list[dict[str, Any]] = []

    # raceresult リンクが存在するレース番号 = 終了済み
    finished_rnos: set[int] = set()
    for a in soup.find_all("a", href=re.compile(r"raceresult")):
        m = re.search(r"rno=(\d+)", a["href"])
        if m:
            finished_rnos.add(int(m.group(1)))

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
            "status": "finished" if race_no in finished_rnos else "scheduled",
        })

    logger.debug("venue %02d: %d races (%d finished)", jcd, len(races), len(finished_rnos))
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
    # 旧: racerslist?hd=...&jcd=...&rno=... → 新: racelist?rno=...&jcd=...&hd=...
    soup = _get("racelist", {"rno": str(race_no), "jcd": f"{stadium_id:02d}", "hd": hd})
    race_id = make_race_id(stadium_id, race_date, race_no)
    entries: list[dict[str, Any]] = []

    # 出走表テーブルはページ内2番目のテーブル (index 1)
    # 艇番セル: class="is-boatColor1"〜"is-boatColor6" (全角数字)
    # tds[2]: 登録番号/級別/氏名 (4桁番号を含む)
    # tds[4]: 全国勝率/2連率/3連率 (改行区切り)
    # tds[6]: モーターNo/2連率/3連率 (改行区切り)
    # tds[7]: ボートNo/2連率/3連率 (改行区切り)
    tables = soup.find_all("table")
    if len(tables) < 2:
        logger.debug("race_id=%s no entry table found", race_id)
        return entries

    for tr in tables[1].find_all("tr"):
        boat_td = tr.find("td", class_=re.compile(r"is-boatColor\d"))
        if not boat_td:
            continue
        tds = tr.find_all("td")
        try:
            boat_no = int(unicodedata.normalize("NFKC", boat_td.get_text(strip=True)))
            if boat_no < 1 or boat_no > 6:
                continue

            # 登録番号・級別・氏名 (tds[2] に3要素が含まれる)
            racer_id = None
            racer_name = None
            racer_grade = None
            if len(tds) > 2:
                td2_lines = [
                    unicodedata.normalize("NFKC", l.strip())
                    for l in tds[2].get_text(separator="\n").split("\n")
                    if l.strip()
                ]
                for line in td2_lines:
                    if racer_id is None and re.match(r"^\d{4}$", line):
                        racer_id = int(line)
                    elif racer_grade is None and re.match(r"^[AB][12]$", line):
                        racer_grade = line
                    elif racer_name is None and re.search(r"[\u3040-\u9FFF]", line):
                        racer_name = line

            def _col_lines(idx: int) -> list[str]:
                if len(tds) <= idx:
                    return []
                return [l.strip() for l in tds[idx].get_text(separator="\n").split("\n") if l.strip()]

            # 全国勝率 (tds[4] 1行目)
            lines4 = _col_lines(4)
            win_rate = _parse_float(lines4[0]) if lines4 else None  # noqa: F841

            # モーター2連率 (tds[6] 2行目)
            lines6 = _col_lines(6)
            motor_win_rate = _parse_float(lines6[1]) if len(lines6) > 1 else None

            # ボート2連率 (tds[7] 2行目)
            lines7 = _col_lines(7)
            boat_win_rate = _parse_float(lines7[1]) if len(lines7) > 1 else None

            entries.append({
                "race_id": race_id,
                "boat_no": boat_no,
                "racer_id": racer_id,
                "racer_name": racer_name,
                "racer_grade": racer_grade,
                "motor_win_rate": motor_win_rate,
                "boat_win_rate": boat_win_rate,
                "exhibition_time": None,   # beforeinfo で更新
                "start_timing": None,       # beforeinfo で更新
                "finish_position": None,
            })
        except (ValueError, AttributeError, IndexError):
            continue

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
    soup = _get("beforeinfo", {"rno": str(race_no), "jcd": f"{stadium_id:02d}", "hd": hd})
    result: dict[int, dict[str, Any]] = {}

    # 直前情報テーブルはページ内2番目のテーブル (index 1)
    # 各艇は4行1グループ:
    #   行0: td[0]=艇番(1-6), td[4]=展示タイム, ...
    #   行1: 進入コース
    #   行2: td[0]=ST値, td[1]='ST'
    #   行3: 着順
    tables = soup.find_all("table")
    if len(tables) < 2:
        return result

    current_boat: int | None = None
    for tr in tables[1].find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        first = tds[0].get_text(strip=True)
        try:
            boat_no = int(first)
            if 1 <= boat_no <= 6:
                current_boat = boat_no
                exhibition_time = _parse_float(tds[4].get_text(strip=True)) if len(tds) > 4 else None
                result[boat_no] = {"exhibition_time": exhibition_time, "start_timing": None}
                continue
        except ValueError:
            pass

        # ST行: td[1] == 'ST'
        if current_boat is not None and len(tds) >= 2 and tds[1].get_text(strip=True) == "ST":
            st_val = _parse_float(first)
            if st_val is not None:
                result[current_boat]["start_timing"] = st_val
            current_boat = None

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


def fetch_trio_odds(stadium_id: int, race_date: str, race_no: int) -> dict[str, float]:
    """
    3連複オッズを取得。

    Returns:
        {"1-2-3": 8.5, "1-2-4": 12.0, ...}  全20通り（キーはソート済み艇番）
    """
    hd = _hd(race_date)
    soup = _get("odds3f", {"hd": hd, "jcd": f"{stadium_id:02d}", "rno": str(race_no)})
    odds_map: dict[str, float] = {}

    # ---- パターン1: data-combination 属性があるセル ----
    # data-combination がソートされていない場合も正規化する
    for td in soup.find_all("td", attrs={"data-combination": True}):
        raw_combo = td["data-combination"]  # 例: "1-2-3" or "3-1-2"
        parts = raw_combo.split("-")
        combo = "-".join(sorted(parts, key=lambda x: int(x)))
        val = _parse_float(td.get_text(strip=True))
        if val and val > 0:
            odds_map[combo] = val

    if odds_map:
        logger.info("trio odds via data-combination: %d entries", len(odds_map))
        return odds_map

    # ---- パターン2: class="oddsPoint" セルから位置ベースでコンビネーション推定 ----
    # odds3f ページは combinations(range(1,7), 3) の順で 20 セル並ぶ想定
    odds_cells = [td for td in soup.find_all("td") if "oddsPoint" in (td.get("class") or [])]
    float_values: list[float] = []
    for td in odds_cells:
        v = _parse_float(td.get_text(strip=True))
        if v is not None and v > 0:
            float_values.append(v)

    if len(float_values) == 20:
        for idx, combo in enumerate(itertools.combinations(range(1, 7), 3)):
            key = "-".join(map(str, combo))
            odds_map[key] = float_values[idx]
        logger.info("trio odds via oddsPoint class: %d entries", len(odds_map))
    else:
        logger.warning(
            "Could not parse trio odds table: expected 20 oddsPoint cells, got %d",
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

    # raceresult ページの着順テーブルは各着順が独立した tbody に1行ずつ格納されている
    # (tbody[1]=1着, tbody[2]=2着, ..., tbody[6]=6着)
    # そのため tbody ごとにループして 6艇分揃うまで収集する
    for tbody in soup.select(".table1 tbody, table tbody"):
        for tr in tbody.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            try:
                # 着順テーブル: 0列=着順(全角数字), 1列=艇番
                finish_pos = int(cells[0].get_text(strip=True))
                boat_no    = int(cells[1].get_text(strip=True))
                if 1 <= boat_no <= 6 and 1 <= finish_pos <= 6:
                    result[boat_no] = finish_pos
            except (ValueError, AttributeError, IndexError):
                continue
        if len(result) == 6:
            break

    logger.debug("raceresult stadium=%02d rno=%d: %s", stadium_id, race_no, result)
    return result
