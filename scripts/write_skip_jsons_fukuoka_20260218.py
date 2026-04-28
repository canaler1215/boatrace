"""Write skip JSONs for 福岡 (22) 2026-02-18 R01-R12."""
import json
from pathlib import Path

OUT = Path("artifacts/predictions/2026-02-18")
OUT.mkdir(parents=True, exist_ok=True)

PREDICTED_AT = "2026-04-28T14:20:00+09:00"
MODEL = "claude-opus-4-7"

races = {
    "01": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.2x圧倒大本命+3号艇単勝2.8x二番手+本命1-3-4 5.4x超凝縮型。本命3連単5.4-9.0xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.2x圧倒大本命、3号艇単勝2.8x二番手、本命3連単 1-3-4 5.4x / 1-3-5 5.5x / 1-3-2 9.0x 超凝縮、EV<1.0。"},
    "02": {"primary_axis": [4, 2], "skip_reason": "4号艇単勝1.8x圧倒大本命 まくり構図+2号艇単勝2.7x大本命二番手 (4-2拮抗) の異例構図だが、本命 2-4-3 11.1x EV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝5.3x 1コース機能不全、4号艇単勝1.8x圧倒大本命 まくり構図、2号艇単勝2.7x大本命二番手、本命3連単 2-4-3 11.1x / 4-2-6 12.0x / 2-4-6 12.4x、市場完全織込済 EV<1.0。"},
    "03": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-3-5 7.3x凝縮型。本命3連単7.3-13.2xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、3号艇単勝6.1x二番手、本命3連単 1-3-5 7.3x / 3-1-5 9.1x / 1-3-4 10.3x 凝縮、EV<1.0。"},
    "04": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.4x大本命+2号艇単勝4.0x/3号艇単勝4.9x拮抗+本命1-2-3 7.6x凝縮型。本命3連単7.6-12.0xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.4x大本命、2=4.0x/3=4.9x拮抗、本命3連単 1-2-3 7.6x / 2-1-3 10.9x / 1-3-2 11.5x 凝縮、EV<1.0。"},
    "05": {"primary_axis": [2, 1], "skip_reason": "2号艇単勝1.8x大本命 まくり差し構図+1号艇単勝2.2x の異例構図だが、本命 1-2-4 7.1x EV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝2.2x、2号艇単勝1.8x大本命 まくり差し構図、4号艇単勝5.3x二番手、本命3連単 1-2-4 7.1x / 2-1-4 8.9x / 1-2-5 13.8x、市場完全織込済 EV<1.0。"},
    "06": {"primary_axis": [4, 1], "skip_reason": "4号艇単勝2.8x大本命二番手 まくり構図+1号艇単勝2.1x の異例構図だが、本命 1-2-4 7.3x EV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝2.1x、4号艇単勝2.8x大本命二番手 まくり構図、2号艇単勝4.7x拮抗、本命3連単 1-2-4 7.3x / 1-4-2 8.5x / 1-4-3 11.6x、市場完全織込済 EV<1.0。"},
    "07": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝2.9x+2号艇単勝3.5x/3号艇単勝3.7x大本命+6号艇単勝4.4x二番手 多角拮抗構図。本命 1-3-6 15.7x EV<1.0+市場完全織込済 (Day 5/6/7 教訓 skip 厳格化)。",
        "analysis": "1号艇単勝2.9x、2-3-6号艇 (3.5-4.4x) 多角拮抗、本命3連単 1-3-6 15.7x / 1-6-3 18.5x / 3-6-1 21.7x、市場完全織込済 EV<1.0。"},
    "08": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-3-4 6.2x凝縮型。本命3連単6.2-12.7xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、3号艇単勝4.9x二番手、本命3連単 1-3-4 6.2x / 1-3-5 9.1x / 1-4-3 12.7x 凝縮、EV<1.0。"},
    "09": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-2-4 5.8x超凝縮型。本命3連単5.8-11.6xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命 (全本命 1-X-X系)、本命3連単 1-2-4 5.8x / 1-2-3 7.1x / 1-3-2 11.1x 超凝縮、EV<1.0。"},
    "10": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-2-4 7.0x凝縮型。本命3連単7.0-10.2xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、2号艇単勝7.4x二番手、本命3連単 1-2-4 7.0x / 1-4-2 9.7x / 1-2-5 10.1x 凝縮、EV<1.0。"},
    "11": {"primary_axis": [1, 2], "skip_reason": "1号艇単勝1.2x圧倒大本命+本命1-2-4 8.0x凝縮型。本命3連単8.0-12.7xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.2x圧倒大本命、2=6.8x/4=7.1x/5=7.9x拮抗、本命3連単 1-2-4 8.0x / 1-2-5 10.0x / 1-2-3 10.9x 凝縮、EV<1.0。"},
    "12": {"primary_axis": [1, 3], "skip_reason": "1号艇単勝1.0x超圧倒大本命+本命1-3-4 7.0x凝縮型。本命3連単7.0-13.6xでEV<1.0。skip。",
        "analysis": "1号艇単勝1.0x超圧倒大本命、3号艇単勝5.8x二番手、本命3連単 1-3-4 7.0x / 1-3-2 11.0x / 1-4-3 11.0x 凝縮、EV<1.0。"},
}

for r, info in races.items():
    rec = {
        "race_id": f"2026-02-18_22_{r}",
        "predicted_at": PREDICTED_AT,
        "model": MODEL,
        "analysis": info["analysis"],
        "primary_axis": info["primary_axis"],
        "verdict": "skip",
        "skip_reason": info["skip_reason"],
        "bets": [],
    }
    p = OUT / f"22_{r}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {p}")

print("done: 12 skip JSONs for 福岡 2026-02-18")
