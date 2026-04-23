"""
ベット候補データを通知向けに整形するヘルパー。

Discord Embed / メール本文など複数のチャンネルで共有する整形ロジックを集約する。
"""
from __future__ import annotations

from typing import Iterable


# boatrace.jp の stadium_id → 場名（1始まり、24場）
STADIUM_NAMES: dict[int, str] = {
    1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖",
    7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
    13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山",
    19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村",
}


def format_stadium(stadium_id: int | None) -> str:
    if stadium_id is None:
        return "?"
    return STADIUM_NAMES.get(int(stadium_id), f"場{stadium_id}")


def format_candidate_line(candidate: dict) -> str:
    """
    1 件のベット候補を 1 行の短いテキストに整形する。

    例: "桐生 12R 1-2-3 prob=8.5% EV=2.30 odds=27.1x"
    """
    stadium = format_stadium(candidate.get("stadium_id"))
    race_no = candidate.get("race_no", "?")
    combo = candidate.get("combination", "?")
    prob = candidate.get("win_probability")
    ev = candidate.get("expected_value")
    odds = candidate.get("odds")

    prob_s = f"{prob * 100:.1f}%" if isinstance(prob, (int, float)) else "?"
    ev_s = f"{ev:.2f}" if isinstance(ev, (int, float)) else "?"
    odds_s = f"{odds:.1f}x" if isinstance(odds, (int, float)) else "?"

    return f"{stadium} {race_no}R {combo} prob={prob_s} EV={ev_s} odds={odds_s}"


def format_candidates_text(candidates: Iterable[dict]) -> str:
    """候補一覧をプレーンテキスト（メール・デバッグ用）に整形する。"""
    items = list(candidates)
    lines = [f"{len(items)}件のベット候補"]
    lines.extend(format_candidate_line(c) for c in items)
    return "\n".join(lines)
