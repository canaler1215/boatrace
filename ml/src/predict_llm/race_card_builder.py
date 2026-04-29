"""レースカード Markdown ジェネレータ.

program_parser.Race + history_summarizer.RacerSummary から、
Claude (LLM) が予想する際に読む Markdown を生成する.
P2 (`/predict`) で直前情報 (展示・オッズ・気象) を追記するためのプレースホルダ
セクションを末尾に持つ.
"""
from __future__ import annotations

from features.stadium_features import (
    DEFAULT_COURSE_WIN_RATE,
    DEFAULT_IN_WIN_RATE,
    STADIUM_COURSE_WIN_RATE,
    STADIUM_IN_WIN_RATE,
)

from predict_llm.history_summarizer import RacerSummary, RecentRun
from predict_llm.program_parser import Boat, Race
from predict_llm.stadium_resolver import WATER_TYPE_LABEL, features_of, name_of

DEFAULT_RECENT_NATIONAL_N = 10
DEFAULT_RECENT_LOCAL_N = 6


# ---------------------------------------------------------------------------
# 部品
# ---------------------------------------------------------------------------


def _fmt_st(st: float | None) -> str:
    return f"{st:.3f}" if st is not None else "N/A"


def _fmt_finish(f: int | None) -> str:
    return str(f) if isinstance(f, int) else "-"


def _stadium_short(stadium_id: int) -> str:
    """場 ID → 短縮表示 (Markdown 表内用). 不明場は "??"."""
    try:
        return name_of(stadium_id)
    except Exception:
        return "??"


def _race_meta_section(race: Race) -> str:
    lines = [
        "## レース情報",
        f"- レース名: {race.race_name or '不明'}",
        f"- 距離: {race.race_distance_m}m" if race.race_distance_m else "- 距離: 不明",
        f"- 締切時刻: {race.deadline or '不明'}",
    ]
    return "\n".join(lines)


def _boat_header(boat: Boat) -> str:
    return (
        f"### {boat.boat_no}号艇 {boat.racer_name} (#{boat.racer_id})\n"
        f"- {boat.racer_grade}級 / {boat.racer_age}歳 / {boat.racer_branch} / {boat.racer_weight}kg\n"
        f"- 全国: 勝率 {boat.win_rate_national:.2f} / 2連率 {boat.place_rate_national:.2f}%\n"
        f"- 当地: 勝率 {boat.win_rate_local:.2f} / 2連率 {boat.place_rate_local:.2f}%\n"
        f"- モーター {boat.motor_no}号: 2連率 {boat.motor_2rate:.2f}%\n"
        f"- ボート {boat.boat_no_unit}号: 2連率 {boat.boat_2rate:.2f}%"
    )


def _summary_oneliner(summary: RacerSummary, label: str) -> str:
    if summary.n_total == 0:
        return f"- {label}: 直近データなし"
    st_part = f"平均ST {_fmt_st(summary.avg_st)}" if summary.avg_st is not None else "平均ST N/A"
    return (
        f"- {label} (直近{summary.n_total}走): "
        f"1着{summary.win_count} / 2連{summary.place_count} / 3連{summary.show_count} / {st_part}"
    )


def _recent_runs_table(runs: list[RecentRun], header_label: str) -> str:
    if not runs:
        return f"#### {header_label}\n(データなし)"
    lines = [f"#### {header_label}"]
    lines.append("| 日付 | 場 | R | 着 | 艇 | ST |")
    lines.append("|---|---|---|---|---|---|")
    for r in runs:
        date_md = r.race_date[5:]  # MM-DD
        lines.append(
            f"| {date_md} | {_stadium_short(r.stadium_id)} | {r.race_no} | "
            f"{_fmt_finish(r.finish_position)} | {r.boat_no} | {_fmt_st(r.start_timing)} |"
        )
    return "\n".join(lines)


def _stadium_features_section(stadium_id: int) -> str:
    in_rate = STADIUM_IN_WIN_RATE.get(stadium_id, DEFAULT_IN_WIN_RATE)
    course_table = STADIUM_COURSE_WIN_RATE.get(stadium_id) or DEFAULT_COURSE_WIN_RATE
    feats = features_of(stadium_id)
    water_type_jp = WATER_TYPE_LABEL.get(str(feats.get("water_type")), "?")
    night_label = "ナイター開催" if feats.get("is_night") else "デイ開催"
    elev_m = int(feats.get("elevation_m") or 0)
    elev_label = f"標高 {elev_m}m" if elev_m > 0 else "標高 海抜近傍"
    lines = [
        "## 場特性",
        f"- {_stadium_short(stadium_id)} 1コース勝率 (in_win_rate): {in_rate * 100:.1f}%",
        f"- 水質: {water_type_jp} / {night_label} / {elev_label}",
        "- コース別 1着率:",
    ]
    for course in range(1, 7):
        rate = course_table.get(course, 0.0)
        lines.append(f"  - {course}コース: {rate * 100:.1f}%")
    return "\n".join(lines)


_PLACEHOLDER = """## ▼ 直前情報 (/predict 実行時に追記)
- 風向 / 風速 / 波高 / 気温 / 水温
- 展示タイム (6 艇)
- スタート展示の進入コース・ST
- オッズ (3連単 上位 20 / 単勝 6 艇)
"""


# ---------------------------------------------------------------------------
# レースカード本体
# ---------------------------------------------------------------------------


def build_race_card(
    race: Race,
    grouped_history,
    recent_n_national: int = DEFAULT_RECENT_NATIONAL_N,
    recent_n_local: int = DEFAULT_RECENT_LOCAL_N,
) -> str:
    """1 レース分の Markdown レースカードを生成する.

    Parameters
    ----------
    race : program_parser.Race
    grouped_history : history_summarizer.group_by_racer() の戻り値
        (race の全 racer_id を含む dict[int, list[RecentRun]])
    """
    from predict_llm.history_summarizer import summarize  # 局所 import で循環回避

    title = f"# {race.race_date} {_stadium_short(race.stadium_id)} {race.race_no}R"
    sections: list[str] = [title, "", _race_meta_section(race), "", "## 出走表", ""]

    for boat in sorted(race.boats, key=lambda b: b.boat_no):
        sections.append(_boat_header(boat))

        # 全国 / 当地サマリ 1 行
        s_nat = summarize(grouped_history, boat.racer_id, n=recent_n_national)
        s_loc = summarize(
            grouped_history, boat.racer_id, n=recent_n_local, stadium_id=race.stadium_id
        )
        sections.append(_summary_oneliner(s_nat, "全国成績"))
        sections.append(
            _summary_oneliner(s_loc, f"当地成績 ({_stadium_short(race.stadium_id)})")
        )
        sections.append("")
        sections.append(
            _recent_runs_table(s_nat.runs, f"直近{recent_n_national}走 (全国)")
        )
        sections.append("")
        sections.append(
            _recent_runs_table(
                s_loc.runs, f"直近{recent_n_local}走 (当地: {_stadium_short(race.stadium_id)})"
            )
        )
        sections.append("")

    sections.append(_stadium_features_section(race.stadium_id))
    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append(_PLACEHOLDER)

    return "\n".join(sections).rstrip() + "\n"


# ---------------------------------------------------------------------------
# index.md 生成
# ---------------------------------------------------------------------------


def build_index(
    date: str,
    races_by_stadium: dict[int, list[Race]],
) -> str:
    """その日のレース一覧 index.md を生成する.

    Parameters
    ----------
    races_by_stadium : 場 ID → そのレース一覧 (race_no 順想定)
    """
    lines = [f"# {date} レースカード index", ""]
    total_races = sum(len(rs) for rs in races_by_stadium.values())
    lines.append(f"対象会場: {len(races_by_stadium)} 場 / 合計 {total_races} レース")
    lines.append("")

    for sid in sorted(races_by_stadium.keys()):
        rs = sorted(races_by_stadium[sid], key=lambda r: r.race_no)
        if not rs:
            continue
        lines.append(f"## {sid:02d} {_stadium_short(sid)} ({len(rs)}R)")
        for r in rs:
            fname = f"{sid:02d}_{r.race_no:02d}.md"
            deadline = f" / 締切 {r.deadline}" if r.deadline else ""
            name = f" / {r.race_name}" if r.race_name else ""
            lines.append(f"- [{r.race_no}R]({fname}){name}{deadline}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
