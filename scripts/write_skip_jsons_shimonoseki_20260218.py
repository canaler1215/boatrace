"""Write skip JSONs for 下関 (19) 2026-02-18 R01-R12."""
import json
from pathlib import Path

OUT = Path("artifacts/predictions/2026-02-18")
OUT.mkdir(parents=True, exist_ok=True)

PREDICTED_AT = "2026-04-28T13:50:00+09:00"
MODEL = "claude-opus-4-7"

races = {
    "01": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.4x大本命+3号艇単勝3.6x二番手+本命1-2-3 8.1x凝縮型。本命3連単8.1-16.5xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.4x大本命、3号艇単勝3.6x二番手、本命3連単 1-2-3 8.1x / 1-3-2 9.8x / 1-2-6 12.3x 凝縮、EV<1.0。"},
    "02": {"primary_axis": [1, 6], "skip_reason": "6号艇単勝3.5x大本命二番手 まくり構図+1号艇単勝1.2x圧倒大本命の異例構図だが、本命 1-6-3 11.0x EV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝1.2x圧倒大本命、6号艇単勝3.5x大本命二番手 まくり構図、本命3連単 1-6-3 11.0x / 1-3-6 12.0x / 1-6-2 17.5x、市場完全織込済 EV<1.0。"},
    "03": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.1x圧倒大本命+本命1-2-3 4.3x超超凝縮型。本命3連単4.3-13.3xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.1x圧倒大本命、本命3連単 1-2-3 4.3x / 1-3-2 6.0x / 2-1-3 12.5x 超超凝縮、EV<1.0。"},
    "04": {"primary_axis": [4, 1], "skip_reason": "4号艇単勝1.7x圧倒大本命 まくり構図+1号艇単勝1.8x の異例構図だが、本命 1-4-5 7.5x EV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝1.8x、4号艇単勝1.7x圧倒大本命 まくり構図、本命3連単 1-4-5 7.5x / 1-4-3 8.5x / 4-1-5 8.9x 超凝縮、市場完全織込済 EV<1.0。"},
    "05": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.3x大本命+2号艇単勝3.8x二番手+4号艇単勝4.5x拮抗+本命1-2-4 3.9x超超凝縮型。本命3連単3.9-10.9xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.3x大本命、2=3.8x/4=4.5x拮抗、本命3連単 1-2-4 3.9x / 1-4-2 5.6x / 2-1-4 10.9x 超超凝縮、EV<1.0。"},
    "06": {"primary_axis": [1, 4], "skip_reason": "6号艇欠場5艇戦+1号艇単勝1.6x大本命+本命1-4-5 16.5x凝縮型。本命3連単16.5-25.2xでEV<1.0。skip。",
        "analysis": "6号艇欠場5艇戦、1号艇単勝1.6x大本命、4号艇単勝4.2x二番手、本命3連単 1-4-5 16.5x / 1-2-5 17.6x / 1-2-4 19.5x 凝縮、EV<1.0。"},
    "07": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-2-3 8.5x凝縮型。本命3連単8.5-14.7xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、本命3連単 1-2-3 8.5x / 1-3-2 9.9x / 1-2-4 13.3x 凝縮、EV<1.0。"},
    "08": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.2x圧倒大本命+2号艇単勝4.0x/3号艇単勝4.9x拮抗+本命1-2-3 2.8x超超超凝縮型。本命3連単2.8-5.6xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.2x圧倒大本命、2=4.0x/3=4.9x拮抗、本命3連単 1-2-3 2.8x / 2-1-3 5.4x / 1-3-2 5.6x 超超超凝縮、EV<1.0。"},
    "09": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-2-3 4.4x超凝縮型。本命3連単4.4-9.9xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、本命3連単 1-2-3 4.4x / 1-3-2 6.0x / 1-2-4 8.4x 超凝縮、EV<1.0。"},
    "10": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.6x大本命+3号艇単勝2.2x大本命二番手 まくり構図+本命1-3-2 5.3x超凝縮型。本命3連単5.3-14.7xでEV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝1.6x大本命、3号艇単勝2.2x大本命二番手 まくり構図、本命3連単 1-3-2 5.3x / 1-3-5 6.0x / 1-2-3 8.7x 超凝縮、市場完全織込済 EV<1.0。"},
    "11": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.7x+2号艇単勝2.6x大本命+3号艇単勝3.6x二番手 拮抗構図+本命1-3-2 10.0x凝縮型。本命3連単10.0-22.4xでEV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝1.7x、2号艇単勝2.6x大本命、3号艇単勝3.6x二番手 拮抗、本命3連単 1-3-2 10.0x / 1-2-3 10.1x / 1-3-4 15.6x、市場完全織込済 EV<1.0。"},
    "12": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.3x大本命+本命1-3-4 6.7x凝縮型。本命3連単6.7-11.6xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.3x大本命、4=5.0x/3=5.6x拮抗、本命3連単 1-3-4 6.7x / 1-3-2 9.4x / 1-2-4 10.1x 凝縮、EV<1.0。"},
}

for r, info in races.items():
    rec = {
        "race_id": f"2026-02-18_19_{r}",
        "predicted_at": PREDICTED_AT,
        "model": MODEL,
        "analysis": info["analysis"],
        "primary_axis": info["primary_axis"],
        "verdict": "skip",
        "skip_reason": info["skip_reason"],
        "bets": [],
    }
    p = OUT / f"19_{r}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {p}")

print("done: 12 skip JSONs for 下関 2026-02-18")
