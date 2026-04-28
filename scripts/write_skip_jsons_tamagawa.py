"""Day 6 多摩川 (05) 全 12 races skip JSON 一括書き出し."""
from __future__ import annotations
import json
from pathlib import Path

DATE = "2026-02-09"
STADIUM = "05"
OUT_DIR = Path(f"artifacts/predictions/{DATE}")
OUT_DIR.mkdir(parents=True, exist_ok=True)

skip_data = {
    "01": {
        "analysis": "1号艇単勝1.6x大本命 + 2号艇3.5x。本命1-2-4 9.7x で EV<0.5 凝縮、買い目妙味なし。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.6x大本命凝縮、本命1-2-4 9.7x で EV<0.5、買い目妙味なし。",
    },
    "02": {
        "analysis": "1号艇単勝1.2x圧倒大本命。本命1-2-3 9.5x で EV<0.5 凝縮、買い目妙味なし。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.2x圧倒、本命1-2-3 9.5x で EV<0.5、買い目妙味なし。",
    },
    "03": {
        "analysis": "1号艇加藤A1 当地直近4走 5,5,6,6 機能不全、3号艇砂長A1 当地ST 0.102/モーター50%/直近4走1着2 異常超好調まくり構図。市場は単勝1.9xで完全織込済、本命3-4-5 12.5x EV~0.88。Day 4-5 同パターン累積 0/9、厳格化で skip。",
        "primary_axis": [3],
        "skip_reason": "3号艇A1異常好調まくり構図だが市場完全織込済 (単勝1.9x)、Day 4-5 教訓厳格化で本命3-4-5 12.5x EV~0.88 skip。",
    },
    "04": {
        "analysis": "1号艇単勝1.9x + 3,4,5号艇拮抗 (3.4-6.0x)。本命1-3-4 11.7x で EV~1.05 ボーダー、人気拮抗構図で skip。",
        "primary_axis": [1, 3],
        "skip_reason": "1号艇1.9x大本命だが3,4,5号艇拮抗、本命1-3-4 11.7x EV~1.05 ボーダー、確信度低く skip。",
    },
    "05": {
        "analysis": "1号艇単勝1.3x大本命 + 2号艇5.1x。本命1-2-4 9.0x で EV<0.5 凝縮、買い目妙味なし。",
        "primary_axis": [1, 2],
        "skip_reason": "1号艇単勝1.3x大本命、本命1-2-4 9.0x で EV<0.5、買い目妙味なし。",
    },
    "06": {
        "analysis": "1号艇単勝1.1x圧倒大本命。本命1-2-4 10.4x で EV<1.0 凝縮、買い目妙味なし。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.1x圧倒、本命1-2-4 10.4x で EV<1.0、買い目妙味なし。",
    },
    "07": {
        "analysis": "1号艇2.5x + 2号艇単勝2.1x大本命 + 5号艇3.6x、二強+5号艇まくり脅威。本命1-2-5 9.9x で EV<0.5 凝縮。",
        "primary_axis": [2, 1],
        "skip_reason": "2号艇単勝2.1x大本命+1号艇2.5x、本命1-2-5 9.9x で EV<0.5、買い目妙味なし。",
    },
    "08": {
        "analysis": "1号艇単勝1.3x大本命 + 3号艇6.3x + 5号艇5.4x。本命1-3-5 8.2x で EV<0.5 凝縮。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.3x大本命、本命1-3-5 8.2x で EV<0.5、買い目妙味なし。",
    },
    "09": {
        "analysis": "1号艇単勝1.4x大本命 + 2号艇4.9x。本命1-2-4 8.2x で EV<0.5 凝縮。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.4x大本命、本命1-2-4 8.2x で EV<0.5、買い目妙味なし。",
    },
    "10": {
        "analysis": "1号艇単勝1.1x圧倒大本命 + 6号艇単勝10.9x (多摩川6コース勝率3%下では微過小評価)。本命1-2-6 7.2x で EV<0.5 凝縮、6-X-X系も EV<1.0。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.1x圧倒、本命1-2-6 7.2x で EV<0.5、買い目妙味なし。",
    },
    "11": {
        "analysis": "1号艇単勝1.5x大本命 + 4号艇5.5x まくり微脅威。本命1-2-4 8.9x で EV<0.5 凝縮、買い目妙味なし。",
        "primary_axis": [1, 4],
        "skip_reason": "1号艇単勝1.5x大本命、本命1-2-4 8.9x で EV<0.5、買い目妙味なし。",
    },
    "12": {
        "analysis": "1号艇単勝1.0x絶対本命。本命1-2-4 7.8x で EV<0.5 凝縮、買い目妙味なし。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.0x絶対本命、本命1-2-4 7.8x で EV<0.5、買い目妙味なし。",
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
