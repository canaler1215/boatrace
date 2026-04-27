"""P4-α 深掘り分析 (一時スクリプト、後で削除可)

全 12 日の eval JSON を読み込み:
- bet 単位のフラットテーブル
- race 単位のフラットテーブル
- 多軸 ROI 集計（bet 位置 / odds 帯 / confidence / primary_axis 命中率）
- 「near-miss」分析（actual_combination の艇集合が picks に含まれるが順序違い）
- カウンターファクトフィルタ（後付け禁止だが「もし」を計算）
"""
import json
import sys
from pathlib import Path
from collections import defaultdict

EVAL_DIR = Path("artifacts/eval")

DATES = [
    "2025-09-06", "2025-09-21", "2025-09-26",
    "2025-10-07", "2025-10-22", "2025-10-30",
    "2025-11-01", "2025-11-15", "2025-11-29",
    "2025-12-01", "2025-12-15", "2025-12-29",
]


def load_all():
    bets = []
    races = []
    for d in DATES:
        path = EVAL_DIR / f"{d}.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for r in data["races"]:
            race_row = {
                "date": d,
                "race_id": r["race_id"],
                "race_no": r["race_no"],
                "status": r["status"],
                "verdict": r["verdict"],
                "primary_axis": r.get("primary_axis"),
                "actual_combination": r.get("actual_combination"),
                "n_bets": len(r.get("bets", [])),
                "total_stake": r.get("total_stake", 0),
                "total_payout": r.get("total_payout", 0.0),
                "is_hit_race": r.get("total_payout", 0.0) > 0,
            }
            races.append(race_row)
            for idx, b in enumerate(r.get("bets", [])):
                bet_row = {
                    "date": d,
                    "race_id": r["race_id"],
                    "race_no": r["race_no"],
                    "pick_pos": idx + 1,  # 1-indexed bet position within race
                    "trifecta": b["trifecta"],
                    "stake": b["stake"],
                    "current_odds": b.get("current_odds"),
                    "actual_odds": b.get("actual_odds"),
                    "confidence": b.get("confidence"),
                    "expected_prob": b.get("expected_prob"),
                    "is_hit": b.get("is_hit", False),
                    "payout": b.get("payout", 0.0),
                    "actual_combination": r.get("actual_combination"),
                    "primary_axis": r.get("primary_axis"),
                }
                bets.append(bet_row)
    return bets, races


def fmt_pct(x):
    return f"{x*100:+.1f}%"


def roi(stake, payout):
    return (payout - stake) / stake if stake > 0 else 0.0


def agg(bets, key_fn, label):
    """key_fn: (bet)->key."""
    buckets = defaultdict(lambda: {"n": 0, "hits": 0, "stake": 0, "payout": 0.0})
    for b in bets:
        k = key_fn(b)
        if k is None:
            continue
        buckets[k]["n"] += 1
        buckets[k]["hits"] += 1 if b["is_hit"] else 0
        buckets[k]["stake"] += b["stake"]
        buckets[k]["payout"] += b["payout"]
    print(f"\n=== {label} ===")
    print(f"{'key':<24}{'n':>6}{'hits':>6}{'hit%':>8}{'ROI':>10}{'stake':>10}{'payout':>10}")
    for k in sorted(buckets.keys()):
        v = buckets[k]
        h = v["hits"] / v["n"] if v["n"] else 0
        r = roi(v["stake"], v["payout"])
        print(f"{str(k):<24}{v['n']:>6}{v['hits']:>6}{h*100:>7.2f}%{fmt_pct(r):>10}{v['stake']:>10}{v['payout']:>10.0f}")
    return buckets


def odds_band(o):
    if o is None:
        return None
    if o < 5: return "1. <5x"
    if o < 10: return "2. 5-10x"
    if o < 15: return "3. 10-15x"
    if o < 20: return "4. 15-20x"
    if o < 30: return "5. 20-30x"
    if o < 50: return "6. 30-50x"
    return "7. >=50x"


def conf_band(c):
    if c is None:
        return None
    if c < 0.4: return "1. <0.4"
    if c < 0.5: return "2. 0.4-0.5"
    if c < 0.6: return "3. 0.5-0.6"
    if c < 0.7: return "4. 0.6-0.7"
    return "5. >=0.7"


def ev_band(b):
    """EV = current_odds * expected_prob"""
    if b["current_odds"] is None or b["expected_prob"] is None:
        return None
    ev = b["current_odds"] * b["expected_prob"]
    if ev < 1.0: return "1. <1.0"
    if ev < 1.3: return "2. 1.0-1.3"
    if ev < 1.6: return "3. 1.3-1.6"
    if ev < 2.0: return "4. 1.6-2.0"
    return "5. >=2.0"


def main():
    bets, races = load_all()
    n_bets = len(bets)
    n_hits = sum(1 for b in bets if b["is_hit"])
    total_stake = sum(b["stake"] for b in bets)
    total_payout = sum(b["payout"] for b in bets)
    print(f"=== Total ===")
    print(f"races: {len(races)}, bets: {n_bets}, hits: {n_hits} ({n_hits/n_bets*100:.2f}%)")
    print(f"stake: {total_stake}, payout: {total_payout:.0f}, ROI: {fmt_pct(roi(total_stake, total_payout))}")

    # 1. Bet position (1st pick = highest confidence within race)
    agg(bets, lambda b: b["pick_pos"], "1. Bet position (1=highest conf in race)")

    # 2. Confidence band
    agg(bets, lambda b: conf_band(b["confidence"]), "2. Confidence band")

    # 3. Odds band (actual_odds)
    agg(bets, lambda b: odds_band(b["actual_odds"]), "3. Actual odds band")

    # 4. EV band (current_odds * expected_prob)
    agg(bets, lambda b: ev_band(b), "4. EV band (current_odds * expected_prob)")

    # 5. expected_prob band
    def prob_band(b):
        p = b["expected_prob"]
        if p is None: return None
        if p < 0.07: return "1. <0.07"
        if p < 0.10: return "2. 0.07-0.10"
        if p < 0.15: return "3. 0.10-0.15"
        if p < 0.20: return "4. 0.15-0.20"
        return "5. >=0.20"
    agg(bets, prob_band, "5. expected_prob band")

    # 6. Race no
    agg(bets, lambda b: f"R{b['race_no']:02d}", "6. Race number")

    # 7. Date / month
    agg(bets, lambda b: b["date"][:7], "7. Month")
    agg(bets, lambda b: b["date"], "8. Date")

    # 9. Near-miss analysis (race-level)
    print("\n=== 9. Near-miss analysis (race level) ===")
    print("actual の艇 3 隻が picks のいずれかに含まれているか?")
    nm_stats = {
        "exact_hit": 0,           # 完全的中
        "all3_in_picks": 0,       # 3 艇すべて picks のどれかに含まれる（順序違い含む）
        "actual_top2_in_picks": 0,  # 1-2 着艇が picks の (1着, 2着) として含まれる
        "axis_correct": 0,        # primary_axis と actual の 1-2 着集合が一致
        "n": 0,
    }
    near_miss_examples = []
    for r in races:
        if r["status"] != "settled":
            continue
        actual = r["actual_combination"]
        if not actual:
            continue
        nm_stats["n"] += 1
        # ピックを取り出す
        picks = [b["trifecta"] for b in bets if b["race_id"] == r["race_id"]]
        if actual in picks:
            nm_stats["exact_hit"] += 1
            continue
        actual_set = set(actual.split("-"))
        # Check if 1着艇 == どのピックの1着でもある
        actual_top2 = tuple(actual.split("-")[:2])
        if any(tuple(p.split("-")[:2]) == actual_top2 for p in picks):
            nm_stats["actual_top2_in_picks"] += 1
        # 3艇すべて picks のどれかに登場（順序違い）
        for p in picks:
            if set(p.split("-")) == actual_set:
                nm_stats["all3_in_picks"] += 1
                near_miss_examples.append({
                    "race_id": r["race_id"], "actual": actual,
                    "matching_pick": p, "stake": r["total_stake"],
                })
                break
        # primary_axis と actual の 1-2 着集合が一致
        if r["primary_axis"]:
            ax_set = set(str(x) for x in r["primary_axis"])
            if set(actual.split("-")[:2]) == ax_set:
                nm_stats["axis_correct"] += 1

    n = nm_stats["n"]
    print(f"  settled races: {n}")
    print(f"  exact_hit:           {nm_stats['exact_hit']:>3} ({nm_stats['exact_hit']/n*100:.1f}%)")
    print(f"  all3_in_picks (順序違い含む): {nm_stats['all3_in_picks']:>3} ({nm_stats['all3_in_picks']/n*100:.1f}%)")
    print(f"  top2 of actual matches some pick's top2: {nm_stats['actual_top2_in_picks']:>3} ({nm_stats['actual_top2_in_picks']/n*100:.1f}%)")
    print(f"  primary_axis == actual top2 set: {nm_stats['axis_correct']:>3} ({nm_stats['axis_correct']/n*100:.1f}%)")

    # 10. Hot races: hit-race の特徴 (高 conf? 高 EV?)
    print("\n=== 10. Hit race vs Miss race comparison ===")
    hit_bets = [b for b in bets if any(rr["race_id"] == b["race_id"] and rr["is_hit_race"] for rr in races)]
    miss_bets = [b for b in bets if not any(rr["race_id"] == b["race_id"] and rr["is_hit_race"] for rr in races)]
    def stats(bs, label):
        n = len(bs)
        if n == 0:
            print(f"  {label}: n=0")
            return
        avg_conf = sum(b["confidence"] for b in bs if b["confidence"]) / n
        avg_odds = sum(b["actual_odds"] for b in bs if b["actual_odds"]) / n
        avg_prob = sum(b["expected_prob"] for b in bs if b["expected_prob"]) / n
        avg_ev = sum(b["current_odds"] * b["expected_prob"] for b in bs if b["current_odds"] and b["expected_prob"]) / n
        print(f"  {label}: n={n}, avg conf={avg_conf:.3f}, avg odds={avg_odds:.1f}, avg prob={avg_prob:.3f}, avg EV={avg_ev:.2f}")
    stats(hit_bets, "Hit-race bets ")
    stats(miss_bets, "Miss-race bets")

    # 11. Counterfactual filters
    print("\n=== 11. Counterfactual filters (これは後付けフィルタ ≒ 禁止だが分析用) ===")
    def apply_filter(bets, fn, label):
        filtered = [b for b in bets if fn(b)]
        n = len(filtered)
        h = sum(1 for b in filtered if b["is_hit"])
        s = sum(b["stake"] for b in filtered)
        p = sum(b["payout"] for b in filtered)
        print(f"  {label:<48} n={n:>3}, hit_rate={h/n*100 if n else 0:>5.2f}%, ROI={fmt_pct(roi(s,p)):>8}, payout={p:.0f}")
        return filtered

    apply_filter(bets, lambda b: True, "no filter (baseline)")
    apply_filter(bets, lambda b: b["confidence"] >= 0.5, "confidence >= 0.5")
    apply_filter(bets, lambda b: b["confidence"] >= 0.55, "confidence >= 0.55")
    apply_filter(bets, lambda b: b["confidence"] >= 0.6, "confidence >= 0.6")
    apply_filter(bets, lambda b: b["pick_pos"] <= 3, "pick_pos <= 3 (top 3 picks only)")
    apply_filter(bets, lambda b: b["pick_pos"] <= 2, "pick_pos <= 2 (top 2 picks only)")
    apply_filter(bets, lambda b: b["pick_pos"] == 1, "pick_pos == 1 (top 1 pick only)")
    apply_filter(bets, lambda b: b["actual_odds"] and b["actual_odds"] >= 10, "odds >= 10x")
    apply_filter(bets, lambda b: b["actual_odds"] and 10 <= b["actual_odds"] < 30, "odds 10-30x (mid range)")
    apply_filter(bets, lambda b: b["actual_odds"] and b["actual_odds"] >= 20, "odds >= 20x")
    apply_filter(bets, lambda b: b["actual_odds"] and b["actual_odds"] < 10, "odds < 10x (favorites)")
    apply_filter(bets, lambda b: b["current_odds"] and b["expected_prob"] and b["current_odds"] * b["expected_prob"] >= 1.0, "EV >= 1.0")
    apply_filter(bets, lambda b: b["current_odds"] and b["expected_prob"] and b["current_odds"] * b["expected_prob"] >= 1.3, "EV >= 1.3")
    apply_filter(bets, lambda b: b["current_odds"] and b["expected_prob"] and b["current_odds"] * b["expected_prob"] >= 1.5, "EV >= 1.5")
    apply_filter(bets, lambda b: b["current_odds"] and b["expected_prob"] and b["current_odds"] * b["expected_prob"] >= 2.0, "EV >= 2.0")
    apply_filter(bets, lambda b: b["confidence"] >= 0.5 and b["actual_odds"] and b["actual_odds"] >= 10, "conf>=0.5 & odds>=10")
    apply_filter(bets, lambda b: b["confidence"] >= 0.55 and b["actual_odds"] and b["actual_odds"] >= 10, "conf>=0.55 & odds>=10")

    # 12. 1着艇別 ROI（actual_combination の1着艇）
    print("\n=== 12. By actual 1st-place lane ===")
    by_winner = defaultdict(lambda: {"n_races": 0, "n_bets": 0, "stake": 0, "payout": 0.0, "hits": 0})
    for r in races:
        if r["status"] != "settled" or not r["actual_combination"]:
            continue
        winner = r["actual_combination"].split("-")[0]
        by_winner[winner]["n_races"] += 1
        rbets = [b for b in bets if b["race_id"] == r["race_id"]]
        by_winner[winner]["n_bets"] += len(rbets)
        by_winner[winner]["stake"] += sum(b["stake"] for b in rbets)
        by_winner[winner]["payout"] += sum(b["payout"] for b in rbets)
        by_winner[winner]["hits"] += sum(1 for b in rbets if b["is_hit"])
    print(f"  {'1着艇':<6}{'races':>6}{'bets':>6}{'hits':>6}{'hit%':>8}{'ROI':>10}{'stake':>10}{'payout':>10}")
    for w in sorted(by_winner.keys()):
        v = by_winner[w]
        h = v["hits"] / v["n_bets"] if v["n_bets"] else 0
        print(f"  {w:<6}{v['n_races']:>6}{v['n_bets']:>6}{v['hits']:>6}{h*100:>7.2f}%{fmt_pct(roi(v['stake'], v['payout'])):>10}{v['stake']:>10}{v['payout']:>10.0f}")

    # 13. 1着艇 = 1号艇のレースだけ抽出して ROI
    print("\n=== 13. 1コース逃げ vs 捲り波乱 ===")
    def filter_races(pred, label):
        rids = {r["race_id"] for r in races if r["status"] == "settled" and pred(r)}
        rb = [b for b in bets if b["race_id"] in rids]
        n = len(rb)
        h = sum(1 for b in rb if b["is_hit"])
        s = sum(b["stake"] for b in rb)
        p = sum(b["payout"] for b in rb)
        print(f"  {label:<32} races={len(rids):>3}, bets={n:>3}, hits={h:>3}, hit%={h/n*100 if n else 0:>5.2f}%, ROI={fmt_pct(roi(s,p))}")
    filter_races(lambda r: r["actual_combination"] and r["actual_combination"].startswith("1-"), "1コース1着 (逃げ)")
    filter_races(lambda r: r["actual_combination"] and not r["actual_combination"].startswith("1-"), "1コース外 (捲り/差し)")
    filter_races(lambda r: r["actual_combination"] and r["actual_combination"].startswith("1-2-"), "1-2-X (本線)")
    filter_races(lambda r: r["actual_combination"] and r["actual_combination"].startswith("1-3-"), "1-3-X (中堅)")


if __name__ == "__main__":
    main()
