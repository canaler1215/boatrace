"""Day 6 桐生 (01) R02-R12 一括 skip JSON 書き出し."""
from __future__ import annotations
import json
from pathlib import Path

DATE = "2026-02-09"
STADIUM = "01"
OUT_DIR = Path(f"artifacts/predictions/{DATE}")
OUT_DIR.mkdir(parents=True, exist_ok=True)

skip_data = {
    "02": {
        "analysis": "1号艇単勝1.9x + 3号艇単勝1.8x の二強。本命1-2-3 / 1-3-2 = 7.0x で EV<0.5、本命凝縮型で買い目妙味なし。",
        "primary_axis": [1, 3],
        "skip_reason": "1号艇単勝1.9x + 3号艇1.8x 二強凝縮、本命1-2-3 7.0x で EV<0.5、全買い目EV<1.0。",
    },
    "03": {
        "analysis": "1号艇単勝1.5x大本命 + 2,3,4号艇拮抗。本命1-2-3 8.1x で EV<0.5。三番手以下の3着候補分散も妙味なし。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.5x大本命凝縮、本命1-2-3 8.1x で EV<0.5、買い目妙味なし。",
    },
    "04": {
        "analysis": "1号艇単勝1.4x圧倒大本命。3,4号艇まくり脅威も4号艇単勝4.7xで完全織込済。本命1-3-2 / 1-3-4 = 6.3-6.4x で EV<0.5。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.4x圧倒、本命1-3-2 6.3x で EV<0.5、買い目妙味なし。",
    },
    "05": {
        "analysis": "1号艇単勝1.7x + 3号艇単勝2.7x 二強。本命1-3-2 7.4x で EV<0.5。3-1-X系も 12.9-17x で EV<1.0。",
        "primary_axis": [1, 3],
        "skip_reason": "1号艇1.7x + 3号艇2.7x 二強凝縮、本命1-3-2 7.4x で EV<0.5、買い目妙味なし。",
    },
    "06": {
        "analysis": "1号艇単勝1.1x圧倒大本命。本命1-3-2 7.0x で EV<0.5。3着候補分散も最高1-3-6 17.2xで EV~0.85。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.1x絶対本命、本命1-3-2 7.0x で EV<0.5、買い目妙味なし。",
    },
    "07": {
        "analysis": "1号艇単勝1.3x + 3号艇単勝3.1x 二強。本命1-3-4 4.9x で EV<0.5。3着候補分散も全EV<1.0。",
        "primary_axis": [1, 3],
        "skip_reason": "1号艇1.3x + 3号艇3.1x 二強凝縮、本命1-3-4 4.9x で EV<0.5、買い目妙味なし。",
    },
    "08": {
        "analysis": "1号艇単勝1.0x絶対本命 + 4号艇単勝12.7xまくり微脅威。本命1-4-5 10.6x で EV~1.06 ボーダー、conservative skip 推奨 (S2 教訓)。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.0x絶対本命、本命1-4-5 10.6x EV~1.06 ボーダー、過去日下では skip 妥当。",
    },
    "09": {
        "analysis": "1号艇単勝1.3x大本命 + 2号艇単勝4.7x二番手。本命1-2-4 6.2x で EV<0.5。三番手以下の3着候補分散も EV<1.0。",
        "primary_axis": [1, 2],
        "skip_reason": "1号艇単勝1.3x大本命、本命1-2-4 6.2x で EV<0.5、買い目妙味なし。",
    },
    "10": {
        "analysis": "1号艇単勝1.4x大本命 + 2,3号艇拮抗。本命1-3-2 6.1x で EV<0.5。3着候補分散も 30x で EV~1.0 ボーダー。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.4x大本命、本命1-3-2 6.1x で EV<0.5、買い目妙味なし。",
    },
    "11": {
        "analysis": "1号艇3.2x + 2号艇3.1x + 3号艇3.0x 三角拮抗、人気分散構図。本命2-3-5 15.5x ですら EV~1.0 ボーダー、確信度低く skip 妥当。",
        "primary_axis": [2, 3],
        "skip_reason": "三角拮抗 (1,2,3号艇 単勝3.0-3.2x) で人気分散、買い目散在、確信度低く skip。",
    },
    "12": {
        "analysis": "1号艇単勝2.1x + 4号艇単勝3.0x まくり脅威、二強拮抗。本命1-2-4 13.7x で EV~1.04 ボーダー、conservative skip。",
        "primary_axis": [1, 4],
        "skip_reason": "1号艇2.1x + 4号艇3.0x 二強拮抗、本命1-2-4 13.7x EV~1.04 ボーダー、過去日下で確信度低く skip。",
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
