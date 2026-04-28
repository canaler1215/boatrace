"""Write skip JSONs for 若松 (20) 2026-02-18 R01-R12."""
import json
from pathlib import Path

OUT = Path("artifacts/predictions/2026-02-18")
OUT.mkdir(parents=True, exist_ok=True)

PREDICTED_AT = "2026-04-28T14:05:00+09:00"
MODEL = "claude-opus-4-7"

races = {
    "01": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.1x圧倒大本命+3号艇単勝4.7x二番手+本命1-3-4 7.7x凝縮型。本命3連単7.7-12.6xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.1x圧倒大本命、3号艇単勝4.7x二番手、本命3連単 1-3-4 7.7x / 1-3-2 8.3x / 1-2-3 8.9x 凝縮、EV<1.0。"},
    "02": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.5x大本命+2号艇単勝3.3x二番手+本命1-2-3 8.6x凝縮型。本命3連単8.6-13.2xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.5x大本命、2号艇単勝3.3x二番手、本命3連単 1-2-3 8.6x / 1-2-5 12.6x / 1-3-2 12.7x 凝縮、EV<1.0。"},
    "03": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.2x圧倒大本命+3号艇単勝5.5x二番手+本命1-3-5 8.0x凝縮型。本命3連単8.0-12.4xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.2x圧倒大本命、3号艇単勝5.5x二番手、本命3連単 1-3-5 8.0x / 1-3-4 8.5x / 1-3-2 9.5x 凝縮、EV<1.0。"},
    "04": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-2-4 8.7x凝縮型。本命3連単8.7-15.1xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、2号艇単勝8.4x二番手、本命3連単 1-2-4 8.7x / 1-2-3 10.8x / 1-2-5 11.5x 凝縮、EV<1.0。"},
    "05": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.3x大本命+3号艇単勝3.8x二番手+本命1-3-4 8.3x凝縮型。本命3連単8.3-13.6xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.3x大本命、3号艇単勝3.8x二番手、本命3連単 1-3-4 8.3x / 1-3-5 11.5x / 1-3-6 11.8x 凝縮、EV<1.0。"},
    "06": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.2x圧倒大本命+本命1-2-3 6.7x超凝縮型。本命3連単6.7-10.9xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.2x圧倒大本命、2号艇単勝5.5x二番手、本命3連単 1-2-3 6.7x / 1-3-2 8.0x / 1-2-4 8.9x 超凝縮、EV<1.0。"},
    "07": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.4x大本命+2号艇単勝4.0x二番手+本命1-2-4 7.0x超凝縮型。本命3連単7.0-12.4xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.4x大本命、2号艇単勝4.0x二番手、本命3連単 1-2-4 7.0x / 1-2-5 7.9x / 1-2-3 9.7x 超凝縮、EV<1.0。"},
    "08": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-2-4 7.6x凝縮型。本命3連単7.6-13.2xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、2号艇単勝7.0x二番手、本命3連単 1-2-4 7.6x / 1-2-3 8.7x / 1-4-2 10.9x 凝縮、EV<1.0。"},
    "09": {"primary_axis": [1, 4], "skip_reason": "1号艇単勝1.1x圧倒大本命+4号艇単勝5.1x二番手+本命1-4-2 7.8x凝縮型。本命3連単7.8-10.6xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.1x圧倒大本命、4号艇単勝5.1x二番手、本命3連単 1-4-2 7.8x / 1-2-4 7.9x / 1-4-6 9.4x 凝縮、EV<1.0。"},
    "10": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.8x大本命+2号艇単勝3.4x/4号艇単勝3.8x拮抗+本命1-2-5 9.5x凝縮型。本命3連単9.5-16.0xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.8x大本命、2=3.4x/4=3.8x拮抗、本命3連単 1-2-5 9.5x / 1-2-3 9.6x / 1-3-5 11.9x 凝縮、EV<1.0。"},
    "11": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.1x圧倒大本命+2号艇単勝7.7x/4号艇単勝7.2x拮抗+本命1-2-4 6.9x超凝縮型。本命3連単6.9-15.5xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.1x圧倒大本命、2=7.7x/4=7.2x拮抗、本命3連単 1-2-4 6.9x / 1-4-2 8.7x / 1-2-3 9.8x 超凝縮、EV<1.0。"},
    "12": {"primary_axis": [1, 4], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-3-4 7.2x凝縮型。本命3連単7.2-12.5xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、4号艇単勝8.1x二番手、本命3連単 1-3-4 7.2x / 1-4-3 8.3x / 1-2-4 9.6x 凝縮、EV<1.0。"},
}

for r, info in races.items():
    rec = {
        "race_id": f"2026-02-18_20_{r}",
        "predicted_at": PREDICTED_AT,
        "model": MODEL,
        "analysis": info["analysis"],
        "primary_axis": info["primary_axis"],
        "verdict": "skip",
        "skip_reason": info["skip_reason"],
        "bets": [],
    }
    p = OUT / f"20_{r}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {p}")

print("done: 12 skip JSONs for 若松 2026-02-18")
