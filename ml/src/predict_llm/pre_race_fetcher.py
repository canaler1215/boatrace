"""直前情報 (展示・進入・気象・オッズ) を取得し、レースカード Markdown を上書きする.

設計上の注意:
  - 既存 `collector/openapi_client.py` の `fetch_before_info` / `fetch_odds` /
    `fetch_win_odds` を **そのまま流用**。書き換えない (CLAUDE.md / 厳守事項)。
  - 気象 (波高・気温・水温) は `fetch_before_info` に無いので、本モジュールで
    boatrace.jp の `beforeinfo` ページを **再フェッチ** して BeautifulSoup で抽出。
  - 過去日 (バックテスト) は boatrace.jp の `beforeinfo` ページが取れないことが
    多いため、`data/odds/odds_YYYYMM.parquet` キャッシュ + K ファイル気象
    (collector/history_downloader.parse_result_file) で代用する。

過去日モード (`mode="past"`):
  - 3 連単オッズ: parquet キャッシュ
  - 単勝オッズ:   parquet キャッシュ (無ければ "(キャッシュなし)")
  - 展示・進入:   "(過去日のため取得不能)" 表示
  - 気象:         K ファイルから天候・風向・風速のみ
  - 進入予想:     "(過去日のため枠なり仮定)" 注記のみ (実値は入れない)

当日モード (`mode="live"`):
  - 全項目 boatrace.jp から取得 (失敗フィールドは "(取得失敗)")
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from collector.history_downloader import (
    DATA_DIR as _HISTORY_DIR,
    extract_lzh,
    parse_result_file,
)
from collector.odds_downloader import (
    _cache_path as _odds_cache_path,
    _df_to_map,
    _win_cache_path,
)
from collector.openapi_client import (
    fetch_before_info,
    fetch_odds,
    fetch_win_odds,
    _get,
    _hd,
    _parse_float,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass
class BeforeWeather:
    """直前気象 (boatrace.jp の beforeinfo ページから抽出)."""

    weather: str | None = None        # "晴" / "曇" / "雨" / "雪"
    wind_direction: str | None = None  # "北西" 等
    wind_speed_m: float | None = None
    wave_height_cm: float | None = None
    air_temp_c: float | None = None
    water_temp_c: float | None = None


@dataclass
class BoatBefore:
    """1 艇分の直前情報."""

    boat_no: int
    exhibition_time: float | None = None  # 展示タイム (秒)
    start_course: int | None = None       # スタート展示の進入コース 1〜6
    start_timing: float | None = None     # スタート展示の ST


@dataclass
class PreRaceInfo:
    """1 レース分の直前情報まとめ."""

    race_id: str               # P1 と同じ "{jcd:02d}{yyyymmdd}{rno:02d}" 形式
    stadium_id: int
    race_date: str             # "YYYY-MM-DD"
    race_no: int
    mode: str                  # "live" | "past"
    weather: BeforeWeather
    boats: list[BoatBefore]    # boat_no 1〜6 (順序保証)
    trifecta_odds: dict[str, float]  # "1-2-3" → 倍率
    win_odds: dict[str, float]       # "1" → 倍率
    fetched_at: str            # ISO8601
    notes: list[str] = field(default_factory=list)  # 取得失敗 / 過去日注記など


# ---------------------------------------------------------------------------
# 当日モード: boatrace.jp スクレイプ
# ---------------------------------------------------------------------------


_RE_FLOAT = re.compile(r"-?\d+(?:\.\d+)?")


def _scrape_before_weather(stadium_id: int, race_date: str, race_no: int) -> BeforeWeather:
    """beforeinfo ページから気象 (波高・気温・水温) を抽出.

    boatrace.jp の beforeinfo ページ構造 (2025-12 時点観察):
      <div class="weather1"> 内に
        - 気温 (例 "気温18.0℃")
        - 天候アイコン (img alt または class)
        - 風速 (例 "風速 2m")
        - 風向アイコン (class="is-wind1"〜"is-wind16" 等)
        - 水温 (例 "水温18.0℃")
        - 波高 (例 "波高 1cm")
    """
    w = BeforeWeather()
    try:
        soup = _get(
            "beforeinfo",
            {"rno": str(race_no), "jcd": f"{stadium_id:02d}", "hd": _hd(race_date)},
        )
    except Exception as exc:
        logger.warning("beforeinfo weather scrape failed %s/%s/%s: %s",
                       stadium_id, race_date, race_no, exc)
        return w

    # weather1 ブロックを探す
    block = soup.find("div", class_=re.compile(r"weather1"))
    if not block:
        return w

    text = unicodedata.normalize("NFKC", block.get_text(separator=" ", strip=True))

    # 気温 / 水温 / 波高 / 風速 を文字列パターンで抽出
    m = re.search(r"気温\s*([\d.]+)", text)
    if m:
        w.air_temp_c = _parse_float(m.group(1))
    m = re.search(r"水温\s*([\d.]+)", text)
    if m:
        w.water_temp_c = _parse_float(m.group(1))
    m = re.search(r"波高\s*([\d.]+)", text)
    if m:
        w.wave_height_cm = _parse_float(m.group(1))
    m = re.search(r"風速\s*([\d.]+)", text)
    if m:
        w.wind_speed_m = _parse_float(m.group(1))

    # 天候: weather1 内の img alt = "晴"/"曇"/"雨"/"雪" を読む
    for img in block.find_all("img"):
        alt = img.get("alt", "")
        if alt in ("晴", "曇", "雨", "雪", "霧"):
            w.weather = alt
            break

    # 風向: span class="is-wind\d+" の数字 → 16方位ラベル
    for span in block.find_all("span"):
        cls = " ".join(span.get("class") or [])
        m = re.search(r"is-wind(\d+)", cls)
        if m:
            idx = int(m.group(1))
            w.wind_direction = _WIND_LABEL.get(idx)
            break

    return w


# boatrace.jp の風向アイコン番号 → 16 方位ラベル
# 観察: is-wind1 = 北、時計回りに 22.5°ずつ
_WIND_LABEL: dict[int, str] = {
    1: "北",     2: "北北東", 3: "北東",   4: "東北東",
    5: "東",     6: "東南東", 7: "南東",   8: "南南東",
    9: "南",     10: "南南西", 11: "南西",  12: "西南西",
    13: "西",    14: "西北西", 15: "北西",  16: "北北西",
}


def _scrape_start_exhibition(stadium_id: int, race_date: str, race_no: int) -> dict[int, int]:
    """スタート展示の進入コース (コース番号) を boat_no → start_course で返す.

    beforeinfo ページの「スタート展示」コーナー枠図エリアから抽出。
    取れなければ空 dict を返す (展示タイム / ST は openapi_client.fetch_before_info で
    すでに取れているのでここでは扱わない)。
    """
    out: dict[int, int] = {}
    try:
        soup = _get(
            "beforeinfo",
            {"rno": str(race_no), "jcd": f"{stadium_id:02d}", "hd": _hd(race_date)},
        )
    except Exception as exc:
        logger.warning("start_exhibition scrape failed: %s", exc)
        return out

    # スタート展示テーブル: class="table1 is-tableFixed__3rdadd" 等
    # 1コース〜6コースの順に <td class="is-boatColorN"> が並ぶレイアウト
    # この部分の構造はサイト変更で壊れやすいので、見つからなければスキップ
    for table in soup.find_all("table"):
        thead_text = ""
        thead = table.find("thead")
        if thead:
            thead_text = thead.get_text(strip=True)
        if "スタート展示" not in thead_text and "ｺｰｽ" not in thead_text and "コース" not in thead_text:
            continue
        # tbody 内の各 tr が 1 コース行
        for tr_idx, tr in enumerate(table.find_all("tr"), start=1):
            boat_td = tr.find("td", class_=re.compile(r"is-boatColor\d"))
            if not boat_td:
                continue
            try:
                boat_no = int(unicodedata.normalize("NFKC", boat_td.get_text(strip=True)))
                if 1 <= boat_no <= 6:
                    # tr_idx がコース番号 (1 行目 = 1 コース)
                    out[boat_no] = tr_idx
            except ValueError:
                continue
        if out:
            break

    return out


# ---------------------------------------------------------------------------
# 過去日モード: キャッシュ + K ファイル
# ---------------------------------------------------------------------------


def _kfile_weather(
    stadium_id: int,
    race_date: str,
    race_no: int,
    history_dir: Path | None = None,
) -> BeforeWeather:
    """K ファイルキャッシュからレース当日の気象を抜き出す.

    波高 / 気温 / 水温は K ファイルに無いので欠損のまま。
    """
    history_dir = history_dir or _HISTORY_DIR
    date = _dt.date.fromisoformat(race_date)
    yy = date.year % 100
    lzh = history_dir / f"k{yy:02d}{date.month:02d}{date.day:02d}.lzh"
    w = BeforeWeather()
    if not lzh.exists():
        logger.debug("K file not found: %s", lzh)
        return w

    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_pre_kweather_"))
    try:
        files = extract_lzh(lzh, tmpdir / lzh.stem)
        for f in files:
            for rec in parse_result_file(f):
                if (rec["stadium_id"] == stadium_id
                        and rec["race_date"] == race_date
                        and rec["race_no"] == race_no):
                    w.weather = rec.get("weather")
                    # K ファイルの wind_direction は数値 (1=北 〜 16=北北西)
                    wd = rec.get("wind_direction")
                    if isinstance(wd, int) and wd in _WIND_LABEL:
                        w.wind_direction = _WIND_LABEL[wd]
                    ws = rec.get("wind_speed")
                    if isinstance(ws, (int, float)):
                        w.wind_speed_m = float(ws)
                    return w
    except Exception as exc:
        logger.debug("K file weather extraction failed: %s", exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return w


def _load_cached_odds(year: int, month: int, race_id: str) -> dict[str, float]:
    """3 連単オッズ parquet キャッシュから 1 レース分を取り出す."""
    p = _odds_cache_path(year, month)
    if not p.exists():
        return {}
    try:
        df = pd.read_parquet(p)
        sub = df[df["race_id"] == race_id]
        if sub.empty:
            return {}
        return dict(zip(sub["combination"], sub["odds"].astype(float)))
    except Exception as exc:
        logger.warning("odds cache load failed (%s): %s", p, exc)
        return {}


def _load_cached_win_odds(year: int, month: int, race_id: str) -> dict[str, float]:
    p = _win_cache_path(year, month)
    if not p.exists():
        return {}
    try:
        df = pd.read_parquet(p)
        sub = df[df["race_id"] == race_id]
        if sub.empty:
            return {}
        return dict(zip(sub["combination"], sub["odds"].astype(float)))
    except Exception as exc:
        logger.warning("win odds cache load failed (%s): %s", p, exc)
        return {}


# ---------------------------------------------------------------------------
# 公開エントリポイント
# ---------------------------------------------------------------------------


def make_race_id(stadium_id: int, race_date: str, race_no: int) -> str:
    """openapi_client と同じ race_id 形式 ("{jcd:02d}{yyyymmdd}{rno:02d}")."""
    return f"{stadium_id:02d}{race_date.replace('-', '')}{race_no:02d}"


def _is_past(race_date: str, today: _dt.date | None = None) -> bool:
    today = today or _dt.date.today()
    return _dt.date.fromisoformat(race_date) < today


def fetch_pre_race_info(
    stadium_id: int,
    race_date: str,
    race_no: int,
    mode: str | None = None,
    today: _dt.date | None = None,
) -> PreRaceInfo:
    """直前情報を取得して PreRaceInfo を返す.

    Parameters
    ----------
    mode : "live" | "past" | None (None = 日付から自動判定: 過去日 → past)
    """
    if mode is None:
        mode = "past" if _is_past(race_date, today) else "live"
    if mode not in ("live", "past"):
        raise ValueError(f"mode must be 'live' or 'past': {mode!r}")

    race_id = make_race_id(stadium_id, race_date, race_no)
    notes: list[str] = []

    if mode == "live":
        # boatrace.jp から取得
        try:
            before = fetch_before_info(stadium_id, race_date, race_no)
        except Exception as exc:
            logger.warning("fetch_before_info failed: %s", exc)
            before = {}
            notes.append(f"展示・ST取得失敗: {exc}")

        try:
            start_courses = _scrape_start_exhibition(stadium_id, race_date, race_no)
        except Exception as exc:
            logger.warning("start_exhibition scrape failed: %s", exc)
            start_courses = {}
            notes.append(f"スタート展示進入取得失敗: {exc}")

        weather = _scrape_before_weather(stadium_id, race_date, race_no)

        try:
            trifecta = fetch_odds(stadium_id, race_date, race_no)
        except Exception as exc:
            logger.warning("fetch_odds failed: %s", exc)
            trifecta = {}
            notes.append(f"3 連単オッズ取得失敗: {exc}")

        try:
            win = fetch_win_odds(stadium_id, race_date, race_no)
        except Exception as exc:
            logger.warning("fetch_win_odds failed: %s", exc)
            win = {}
            notes.append(f"単勝オッズ取得失敗: {exc}")

        boats: list[BoatBefore] = []
        for bn in range(1, 7):
            info = before.get(bn, {})
            boats.append(
                BoatBefore(
                    boat_no=bn,
                    exhibition_time=info.get("exhibition_time"),
                    start_course=start_courses.get(bn),
                    start_timing=info.get("start_timing"),
                )
            )

    else:  # past
        # キャッシュ + K ファイル
        d = _dt.date.fromisoformat(race_date)
        trifecta = _load_cached_odds(d.year, d.month, race_id)
        if not trifecta:
            notes.append(
                f"3 連単オッズキャッシュなし: data/odds/odds_{d.year}{d.month:02d}.parquet"
            )

        win = _load_cached_win_odds(d.year, d.month, race_id)
        if not win:
            notes.append(
                f"単勝オッズキャッシュなし: data/odds/win_odds_{d.year}{d.month:02d}.parquet"
            )

        weather = _kfile_weather(stadium_id, race_date, race_no)
        if weather.weather is None and weather.wind_speed_m is None:
            notes.append("K ファイル気象データ未取得")

        notes.append("過去日のため展示タイム・スタート展示進入は取得不能")
        boats = [BoatBefore(boat_no=bn) for bn in range(1, 7)]

    return PreRaceInfo(
        race_id=race_id,
        stadium_id=stadium_id,
        race_date=race_date,
        race_no=race_no,
        mode=mode,
        weather=weather,
        boats=boats,
        trifecta_odds=trifecta,
        win_odds=win,
        fetched_at=_dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).isoformat(timespec="seconds"),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Markdown 追記
# ---------------------------------------------------------------------------


_PLACEHOLDER_HEADER = "## ▼ 直前情報 (/predict 実行時に追記)"


def _format_weather(w: BeforeWeather) -> str:
    fields = []
    if w.weather:
        fields.append(f"天候 {w.weather}")
    if w.wind_direction or w.wind_speed_m is not None:
        wd = w.wind_direction or "?"
        ws = f"{w.wind_speed_m}m" if w.wind_speed_m is not None else "?m"
        fields.append(f"風 {wd} {ws}")
    if w.wave_height_cm is not None:
        fields.append(f"波高 {w.wave_height_cm}cm")
    if w.air_temp_c is not None:
        fields.append(f"気温 {w.air_temp_c}℃")
    if w.water_temp_c is not None:
        fields.append(f"水温 {w.water_temp_c}℃")
    return " / ".join(fields) if fields else "(データなし)"


def _format_boats(boats: list[BoatBefore], mode: str) -> str:
    lines = ["| 艇 | 展示T | 進入 | 展示ST |", "|---|---|---|---|"]
    for b in boats:
        et = f"{b.exhibition_time:.2f}" if b.exhibition_time is not None else "-"
        sc = str(b.start_course) if b.start_course is not None else "-"
        st = f"{b.start_timing:.3f}" if b.start_timing is not None else "-"
        lines.append(f"| {b.boat_no} | {et} | {sc} | {st} |")
    if mode == "past":
        lines.append("")
        lines.append("(過去日ドライランのため展示・進入は欠損。進入は枠なり (boat_no = course) と仮定)")
    return "\n".join(lines)


def _format_trifecta_odds(odds: dict[str, float], top_n: int = 20) -> str:
    if not odds:
        return "(取得不能)"
    sorted_items = sorted(odds.items(), key=lambda kv: kv[1])  # 安いほうから = 人気順
    top = sorted_items[:top_n]
    lines = [f"3 連単 上位 {len(top)} (人気順):"]
    # 4 列で並べる
    chunk_size = 4
    for i in range(0, len(top), chunk_size):
        row = top[i:i + chunk_size]
        lines.append("  " + "  ".join(f"{combo} {o:.1f}x" for combo, o in row))
    lines.append(f"(全 {len(odds)} 通り中)")
    return "\n".join(lines)


def _format_win_odds(odds: dict[str, float]) -> str:
    if not odds:
        return "(取得不能)"
    lines = ["| 艇 | 単勝オッズ |", "|---|---|"]
    for bn in range(1, 7):
        v = odds.get(str(bn))
        s = f"{v:.1f}x" if v is not None else "-"
        lines.append(f"| {bn} | {s} |")
    return "\n".join(lines)


def render_pre_race_section(info: PreRaceInfo) -> str:
    """PreRaceInfo を Markdown セクション化."""
    mode_label = "当日 (live)" if info.mode == "live" else "過去日ドライラン (past)"
    parts = [
        "## ▼ 直前情報",
        f"- 取得モード: {mode_label}",
        f"- 取得時刻: {info.fetched_at}",
        f"- 気象: {_format_weather(info.weather)}",
        "",
        "### 展示 / スタート展示",
        _format_boats(info.boats, info.mode),
        "",
        "### 直前オッズ",
        _format_trifecta_odds(info.trifecta_odds),
        "",
        _format_win_odds(info.win_odds),
    ]
    if info.notes:
        parts.append("")
        parts.append("### 取得メモ")
        for n in info.notes:
            parts.append(f"- {n}")
    return "\n".join(parts) + "\n"


def append_to_race_card(card_path: Path, info: PreRaceInfo) -> None:
    """race card MD のプレースホルダ部分を実データで置き換える (上書き).

    既に直前情報が追記済みの場合 (プレースホルダが消えている場合) は冪等に
    `## ▼ 直前情報` ヘッダ以降を再生成する.
    """
    text = card_path.read_text(encoding="utf-8")

    new_section = render_pre_race_section(info)

    # ケース 1: プレースホルダが残っている → そのヘッダから末尾を置換
    if _PLACEHOLDER_HEADER in text:
        idx = text.index(_PLACEHOLDER_HEADER)
        new_text = text[:idx].rstrip() + "\n\n" + new_section
    # ケース 2: 既に追記済み (前回の "## ▼ 直前情報" がある) → そこから置換
    elif "## ▼ 直前情報" in text:
        idx = text.index("## ▼ 直前情報")
        new_text = text[:idx].rstrip() + "\n\n" + new_section
    else:
        # ケース 3: どちらも無い → 末尾に追記
        new_text = text.rstrip() + "\n\n---\n\n" + new_section

    card_path.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# JSON ダンプ (デバッグ / 検査用)
# ---------------------------------------------------------------------------


def dump_pre_race_json(info: PreRaceInfo, path: Path) -> None:
    """PreRaceInfo を JSON で保存 (デバッグ・追跡用)."""
    payload = {
        "race_id": info.race_id,
        "stadium_id": info.stadium_id,
        "race_date": info.race_date,
        "race_no": info.race_no,
        "mode": info.mode,
        "fetched_at": info.fetched_at,
        "weather": {
            "weather": info.weather.weather,
            "wind_direction": info.weather.wind_direction,
            "wind_speed_m": info.weather.wind_speed_m,
            "wave_height_cm": info.weather.wave_height_cm,
            "air_temp_c": info.weather.air_temp_c,
            "water_temp_c": info.weather.water_temp_c,
        },
        "boats": [
            {
                "boat_no": b.boat_no,
                "exhibition_time": b.exhibition_time,
                "start_course": b.start_course,
                "start_timing": b.start_timing,
            }
            for b in info.boats
        ],
        "trifecta_odds": info.trifecta_odds,
        "win_odds": info.win_odds,
        "notes": info.notes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
