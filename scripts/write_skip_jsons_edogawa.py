"""Day 6 江戸川 (03) 全 12 races skip JSON 一括書き出し."""
from __future__ import annotations
import json
from pathlib import Path

DATE = "2026-02-09"
STADIUM = "03"
OUT_DIR = Path(f"artifacts/predictions/{DATE}")
OUT_DIR.mkdir(parents=True, exist_ok=True)

skip_data = {
    "01": {
        "analysis": "1号艇単勝1.6x大本命 + 3,4号艇単勝4.0-5.3x。本命1-3-4 12.8x で EV~1.0 ボーダー、conservative skip。",
        "primary_axis": [1, 3],
        "skip_reason": "1号艇単勝1.6x大本命凝縮、本命1-3-4 12.8x EV~1.0 ボーダー、過去日下で確信度低く skip。",
    },
    "02": {
        "analysis": "1号艇2.4x + 2,3,4号艇単勝3.0-4.0x、6号艇欠場の5艇展開。本命1-3-2 12.3x EV~1.0 ボーダー、人気分散構図。",
        "primary_axis": [1, 3],
        "skip_reason": "5艇展開で人気分散 (1-4号艇単勝2.4-4.0x)、本命1-3-2 12.3x EV~1.0 ボーダー、skip。",
    },
    "03": {
        "analysis": "1号艇単勝1.7x大本命 + 4号艇3.6x + 2号艇4.4x。本命1-2-4 10.3x で EV~1.03 ボーダー、買い目散在構図。",
        "primary_axis": [1, 4],
        "skip_reason": "1号艇1.7x大本命、本命1-2-4 10.3x EV~1.03 ボーダー、確信度低く skip。",
    },
    "04": {
        "analysis": "2号艇単勝1.4x圧倒大本命 (江戸川1コース勝率48%下では2号艇単勝1.4xは異例強さ)。本命2-1-5 8.9x で EV<0.5 凝縮、買い目妙味なし。",
        "primary_axis": [2],
        "skip_reason": "2号艇単勝1.4x圧倒、本命2-1-5 8.9x で EV<0.5、買い目妙味なし。",
    },
    "05": {
        "analysis": "1号艇単勝2.5x + 3,4,5号艇拮抗 (3.8-4.0x)。本命1-3-6 14.1x で EV~0.99 ボーダー、人気分散構図。",
        "primary_axis": [1, 3],
        "skip_reason": "1号艇2.5x大本命だが本命1-3-6 14.1x EV~0.99 ボーダー、3-5号艇拮抗で skip。",
    },
    "06": {
        "analysis": "1号艇塩田B1 53歳/当地直近1走 ST 0.330 機能不全 + 5号艇川崎A1 全国2連42.86%/当地2連39.62%/ST 0.134 + 6号艇西舘A2/当地直近6走1着3。4-5-X系まくり構図だが本命4-5-6 19.2x EV~0.96 ボーダー、市場完全織込済。",
        "primary_axis": [5, 4],
        "skip_reason": "1号艇機能不全+5号艇A1まくり構図だが本命4-5-6 19.2x EV~0.96 ボーダー、市場完全織込済で skip。",
    },
    "07": {
        "analysis": "1号艇3.6x + 3号艇単勝2.3x大本命 (江戸川で珍しい3号艇優勢構図)。本命1-3-4 11.0x で EV~0.99 ボーダー、人気散在。",
        "primary_axis": [3, 1],
        "skip_reason": "3号艇単勝2.3x大本命+1号艇3.6x、本命1-3-4 11.0x EV~0.99 ボーダー、確信度低く skip。",
    },
    "08": {
        "analysis": "1号艇単勝1.9x + 3号艇単勝1.9x 二強凝縮 (江戸川で珍しい)。本命1-3-5 8.8x で EV<0.5、買い目妙味なし。",
        "primary_axis": [1, 3],
        "skip_reason": "1,3号艇 単勝1.9x 二強凝縮、本命1-3-5 8.8x で EV<0.5、買い目妙味なし。",
    },
    "09": {
        "analysis": "1号艇単勝1.0x絶対本命、6号艇欠場の5艇展開。本命1-5-2 10.5x で EV~1.05 ボーダー、conservative skip。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.0x絶対本命、本命1-5-2 10.5x EV~1.05 ボーダー、skip。",
    },
    "10": {
        "analysis": "1号艇単勝1.0x絶対本命。本命1-2-5 10.7x で EV~1.07 ボーダー、3着候補2-3-5分散。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.0x絶対本命、本命1-2-5 10.7x EV~1.07 ボーダー、skip。",
    },
    "11": {
        "analysis": "1号艇1.9x + 4号艇単勝2.3x 二強構図、6号艇欠場。本命1-3-5 12.7x で EV~0.99 ボーダー、3-5号艇3着候補拮抗。",
        "primary_axis": [1, 4],
        "skip_reason": "1号艇1.9x + 4号艇2.3x 二強凝縮、本命1-3-5 12.7x EV~0.99 ボーダー、skip。",
    },
    "12": {
        "analysis": "1号艇単勝1.0x絶対本命 + 4号艇まくり脅威 (単勝6.7x)。本命1-2-4 6.9x で EV<0.5 凝縮、買い目妙味なし。",
        "primary_axis": [1],
        "skip_reason": "1号艇単勝1.0x絶対本命、本命1-2-4 6.9x で EV<0.5、買い目妙味なし。",
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
