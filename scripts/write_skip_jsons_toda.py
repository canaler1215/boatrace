"""Day 6 戸田 (02) 全 12 races skip JSON 一括書き出し."""
from __future__ import annotations
import json
from pathlib import Path

DATE = "2026-02-09"
STADIUM = "02"
OUT_DIR = Path(f"artifacts/predictions/{DATE}")
OUT_DIR.mkdir(parents=True, exist_ok=True)

skip_data = {
    "01": {
        "analysis": "1号艇単勝1.3x大本命 + 4号艇単勝7.0xまくり微脅威。本命1-2-4 14.6x で EV~1.0 ボーダー、conservative skip。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.3x大本命凝縮、本命1-2-4 14.6x EV~1.0 ボーダー、過去日下で確信度低く skip。",
    },
    "02": {
        "analysis": "2号艇単勝2.3x大本命 + 1号艇3.4x + 5号艇3.1x、三角拮抗構図。本命2-3-5 10.9x ですら EV~1.0 ボーダーで人気分散、買い目散在。",
        "primary_axis": [2, 5],
        "skip_reason": "三角拮抗 (1,2,5号艇) で人気分散、本命2-3-5 10.9x EV~1.0 ボーダー、確信度低く skip。",
    },
    "03": {
        "analysis": "1号艇池千夏B1 54歳/当地2連0.00 機能不全、3号艇津久井A2 全国2連35.9%/当地2連37.21%/当地直近6走1着3で異常好調。3号艇単勝1.6x大本命凝縮、本命3-2-6 10.9x で EV~0.72。3-X-X系全 EV<1.0。",
        "primary_axis": [3],
        "skip_reason": "3号艇A1まくり構図だが市場完全織込済 (単勝1.6x)、本命3-2-6 10.9x で EV<1.0、買い目妙味なし。",
    },
    "04": {
        "analysis": "1号艇西村美智B2/全国2連50.94%(高勝率) + 6号艇A2/当地直近5走1着4の異常好調 (戸田6コース勝率3.6%下では破格)。市場は単勝4.8xで完全織込済、本命1-2-6 10.9x EV~1.09 / 6-1-2 43.9x EV~1.1 ボーダー。Day 5 唐津R12 37.5x miss 教訓を厳格化、80-110x 基準未達で skip。",
        "primary_axis": [1, 6],
        "skip_reason": "6号艇A2異常好調も単勝4.8xで完全織込済、6-1-2 43.9x は Day 5 不発基準と同水準で確信度低く skip。",
    },
    "05": {
        "analysis": "1号艇単勝2.5x + 2号艇4.1x + 3号艇3.0x + 4号艇3.1x、四角拮抗。本命1-4-6 9.7x ですら EV~0.97 ボーダー、人気分散構図。",
        "primary_axis": [1, 4],
        "skip_reason": "四角拮抗 (1,2,3,4号艇単勝2.5-4.1x) で人気分散、本命1-4-6 9.7x EV<1.0 で skip。",
    },
    "06": {
        "analysis": "2号艇単勝2.5x大本命 (戸田1コース勝率44%でも1号艇単勝4.0xで2号艇優勢の異例構図)、本命2-5-6 16.3x で EV~0.81。人気2-5/2-3拮抗で散在型。",
        "primary_axis": [2, 5],
        "skip_reason": "2号艇単勝2.5x大本命だが本命2-5-6 16.3x で EV<1.0、買い目散在で skip。",
    },
    "07": {
        "analysis": "1号艇単勝1.7x + 4号艇単勝1.7x、二強。本命1-4-5 6.2x で EV<0.5 凝縮型、買い目妙味なし。",
        "primary_axis": [1, 4],
        "skip_reason": "1号艇1.7x + 4号艇1.7x 二強凝縮、本命1-4-5 6.2x で EV<0.5、買い目妙味なし。",
    },
    "08": {
        "analysis": "1号艇単勝1.5x大本命 + 2号艇3.5x。本命1-2-5 7.1x で EV<0.5。3着候補分散も全 EV<1.0。",
        "primary_axis": [1, 2],
        "skip_reason": "1号艇単勝1.5x大本命、本命1-2-5 7.1x で EV<0.5、買い目妙味なし。",
    },
    "09": {
        "analysis": "1号艇単勝1.3x圧倒大本命 + 2号艇3.3x。本命1-2-4 6.1x で EV<0.5。3着候補分散も全 EV<1.0。",
        "primary_axis": [1, 2],
        "skip_reason": "1号艇単勝1.3x圧倒大本命、本命1-2-4 6.1x で EV<0.5、買い目妙味なし。",
    },
    "10": {
        "analysis": "1号艇単勝1.5x大本命 + 6号艇単勝11.7x (戸田6コース勝率3.6%下で過小評価)。本命1-2-6 17.6x EV~1.06 ボーダー、6-X-X系も 30x台で EV~1.0 ボーダー、conservative skip。",
        "primary_axis": [1, 6],
        "skip_reason": "1号艇1.5x大本命、6号艇単勝11.7x過小評価も本命1-2-6 17.6x EV~1.06 ボーダー、skip。",
    },
    "11": {
        "analysis": "1号艇単勝1.7x大本命 + 2,3号艇拮抗。本命1-2-3 5.1x で EV<0.5 凝縮型。3着候補分散も全 EV<1.0。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.7x大本命、本命1-2-3 5.1x で EV<0.5、買い目妙味なし。",
    },
    "12": {
        "analysis": "1号艇単勝1.6x大本命 + 2号艇3.1x。本命1-2-3 8.2x で EV<0.5 凝縮型。3着候補分散も全 EV<1.0。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.6x大本命、本命1-2-3 8.2x で EV<0.5、買い目妙味なし。",
    },
}

for r, data in skip_data.items():
    obj = {
        "race_id": f"{DATE}_{STADIUM}_{r}",
        "predicted_at": "2026-04-28T12:00:00+09:00",
        "model": "claude-opus-4-7",
        "analysis": data["analysis"],
        "primary_axis": data["primary_axis"],
        "verdict": "skip",
        "skip_reason": data["skip_reason"],
        "bets": [],
    }
    out_path = OUT_DIR / f"{STADIUM}_{r}.json"
    out_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")

print(f"done: {len(skip_data)} skip JSONs for stadium {STADIUM}")
