"""相互作用分析 + near-miss の詳細 + 月別フィルタ ROI"""
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
        with open(EVAL_DIR / f"{d}.json", encoding="utf-8") as f:
            data = json.load(f)
        for r in data["races"]:
            races.append({
                "date": d, "race_id": r["race_id"], "race_no": r["race_no"],
                "status": r["status"], "primary_axis": r.get("primary_axis"),
                "actual_combination": r.get("actual_combination"),
                "n_bets": len(r.get("bets", [])),
                "total_stake": r.get("total_stake", 0),
                "total_payout": r.get("total_payout", 0.0),
            })
            for idx, b in enumerate(r.get("bets", [])):
                bets.append({
                    "date": d, "race_id": r["race_id"], "race_no": r["race_no"],
                    "month": d[:7], "pick_pos": idx + 1,
                    "trifecta": b["trifecta"],
                    "stake": b["stake"], "current_odds": b.get("current_odds"),
                    "actual_odds": b.get("actual_odds"),
                    "confidence": b.get("confidence"),
                    "expected_prob": b.get("expected_prob"),
                    "is_hit": b.get("is_hit", False),
                    "payout": b.get("payout", 0.0),
                    "actual_combination": r.get("actual_combination"),
                })
    return bets, races


def fmt_pct(x):
    return f"{x*100:+.1f}%"


def roi(s, p):
    return (p - s) / s if s > 0 else 0.0


def report(bets, label):
    n = len(bets)
    if n == 0:
        return
    h = sum(1 for b in bets if b["is_hit"])
    s = sum(b["stake"] for b in bets)
    p = sum(b["payout"] for b in bets)
    print(f"  {label:<60} n={n:>3}, hit%={h/n*100:>5.2f}%, ROI={fmt_pct(roi(s,p)):>8}, stake={s}, payout={p:.0f}")


def main():
    bets, races = load_all()

    # 1. pick_pos × confidence interaction
    print("=== A. pick_pos × confidence_band ===")
    for pos in range(1, 6):
        sub = [b for b in bets if b["pick_pos"] == pos]
        for cmin, cmax, lbl in [(0.0, 0.5, "<0.5"), (0.5, 0.6, "0.5-0.6"), (0.6, 1.0, ">=0.6")]:
            ss = [b for b in sub if cmin <= (b["confidence"] or 0) < cmax]
            report(ss, f"pos={pos}, conf={lbl}")

    # 2. pick_pos × EV interaction
    print("\n=== B. pick_pos × EV ===")
    for pos in range(1, 6):
        sub = [b for b in bets if b["pick_pos"] == pos]
        for emin, emax, lbl in [(0, 1.0, "<1.0"), (1.0, 1.3, "1.0-1.3"), (1.3, 99, ">=1.3")]:
            ss = [b for b in sub if b["current_odds"] and b["expected_prob"] and emin <= b["current_odds"]*b["expected_prob"] < emax]
            report(ss, f"pos={pos}, EV={lbl}")

    # 3. EV × actual_odds interaction
    print("\n=== C. EV × actual_odds ===")
    for emin, emax, lbl in [(0, 1.0, "EV<1.0"), (1.0, 1.3, "EV 1.0-1.3"), (1.3, 99, "EV>=1.3")]:
        sub = [b for b in bets if b["current_odds"] and b["expected_prob"] and emin <= b["current_odds"]*b["expected_prob"] < emax]
        for omin, omax, olbl in [(0, 10, "odds<10"), (10, 30, "odds 10-30"), (30, 9999, "odds>=30")]:
            ss = [b for b in sub if b["actual_odds"] and omin <= b["actual_odds"] < omax]
            report(ss, f"{lbl}, {olbl}")

    # 4. Smart filter month-by-month consistency check
    print("\n=== D. Filter ROI by month (consistency check) ===")
    filters = [
        ("baseline (all)", lambda b: True),
        ("pick_pos == 1", lambda b: b["pick_pos"] == 1),
        ("pick_pos <= 3", lambda b: b["pick_pos"] <= 3),
        ("EV >= 1.3", lambda b: b["current_odds"] and b["expected_prob"] and b["current_odds"]*b["expected_prob"] >= 1.3),
        ("conf 0.5-0.6", lambda b: 0.5 <= (b["confidence"] or 0) < 0.6),
        ("conf>=0.5 + EV>=1.2", lambda b: (b["confidence"] or 0) >= 0.5 and b["current_odds"] and b["expected_prob"] and b["current_odds"]*b["expected_prob"] >= 1.2),
        ("pick_pos<=3 + EV>=1.2", lambda b: b["pick_pos"] <= 3 and b["current_odds"] and b["expected_prob"] and b["current_odds"]*b["expected_prob"] >= 1.2),
        ("pick_pos<=3 + conf>=0.5", lambda b: b["pick_pos"] <= 3 and (b["confidence"] or 0) >= 0.5),
    ]
    months = ["2025-09", "2025-10", "2025-11", "2025-12"]
    print(f"  {'filter':<35}", end="")
    for m in months:
        print(f"{m:>12}", end="")
    print(f"{'TOTAL':>14}")
    for label, fn in filters:
        print(f"  {label:<35}", end="")
        total_n, total_s, total_p = 0, 0, 0.0
        for m in months:
            ss = [b for b in bets if b["month"] == m and fn(b)]
            n = len(ss); s = sum(b["stake"] for b in ss); p = sum(b["payout"] for b in ss)
            total_n += n; total_s += s; total_p += p
            r = roi(s, p) if s else 0
            print(f"  {n:>3}/{fmt_pct(r):>7}", end="")
        r = roi(total_s, total_p) if total_s else 0
        print(f"  {total_n:>3}/{fmt_pct(r):>7}")

    # 5. Near-miss potential: how much would "box bet on top-3 picks" recover?
    # ピックの3艇集合のうち最頻 1 集合に着目し、その6順列をすべて買ったらどうなる?
    print("\n=== E. Near-miss recovery: box-bet alternative analysis ===")
    print("  本分析: actual の 3 艇集合 = 何らかの pick の 3 艇集合 と一致するレースで、")
    print("  「その3艇のbox = 6順列買い」をしていたら回収できたか?")
    near_miss_box_payout = 0
    near_miss_n = 0
    for r in races:
        if r["status"] != "settled" or not r["actual_combination"]:
            continue
        actual = r["actual_combination"]
        actual_set = set(actual.split("-"))
        rbets = [b for b in bets if b["race_id"] == r["race_id"]]
        # actual と一致する 3 艇集合を持つ pick が存在し、かつ exact_hit でない
        exact = any(b["trifecta"] == actual for b in rbets)
        if exact:
            continue
        match = next((b for b in rbets if set(b["trifecta"].split("-")) == actual_set), None)
        if match:
            near_miss_n += 1
            # この時 actual_odds をそのまま採用 (box買いだと当該1点の payout を使う)
            # 実態的には box 買い = 6 点購入 (600円 stake)、的中1点 → payout = 当該 actual_odds × stake
            near_miss_box_payout += (match["actual_odds"] or 0) * 100
    # 仮想: 各レースで「top1 pick の 3 艇集合」を box (6 点) 買いするとしたら?
    sim_n_bets = 0
    sim_stake = 0
    sim_payout = 0
    sim_hits = 0
    for r in races:
        if r["status"] != "settled" or not r["actual_combination"]:
            continue
        actual = r["actual_combination"]
        rbets = [b for b in bets if b["race_id"] == r["race_id"]]
        if not rbets:
            continue
        # top1 pick = pick_pos==1
        top1 = next((b for b in rbets if b["pick_pos"] == 1), None)
        if not top1:
            continue
        boats_set = set(top1["trifecta"].split("-"))
        # 6 順列を仮想購入、stake 1 点 100 円
        sim_n_bets += 6
        sim_stake += 600
        if set(actual.split("-")) == boats_set:
            sim_hits += 1
            # 仮想 payout = actual_odds × stake (1 点ヒット)
            # actual_odds は eval JSON にある場合と無い場合があるので、
            # match した bet の actual_odds を使う
            match = next((b for b in rbets if b["trifecta"] == actual), None)
            if match:
                sim_payout += (match["actual_odds"] or 0) * 100
            else:
                # actual の組合せを持つ bet が無い → 順序違いの場合は、
                # 同じ集合の bet の actual_odds は組合せごとに違うので近似困難
                # 平均値（=同集合の bet の actual_odds 平均）を使う
                same_set = [b for b in rbets if set(b["trifecta"].split("-")) == boats_set and b["actual_odds"]]
                if same_set:
                    avg_odds = sum(b["actual_odds"] for b in same_set) / len(same_set)
                    sim_payout += avg_odds * 100
    print(f"  実 near-miss races: {near_miss_n}")
    print(f"  仮想シミュレーション: top1 pick の 3 艇 box 買い (6 点 600 円 / レース)")
    print(f"  bet数={sim_n_bets}, hits={sim_hits}, stake={sim_stake}, payout={sim_payout:.0f}")
    print(f"  仮想 ROI={fmt_pct(roi(sim_stake, sim_payout))}, hit_rate/race={sim_hits / 133*100:.2f}%")

    # 6. 仮想 top1 box vs actual baseline
    print("\n=== F. 仮想戦略比較 (133 settled races, 11 race/day × 12 day - skips) ===")
    print(f"  実績: 5 picks × 133 races (推定 595 bets / 5 picks/race), bet数=596, ROI=-2.8%")
    print(f"  仮想 (top1 box, 6 picks): 上記の通り")

    # 7. picks の primary_axis 一致 vs 不一致 (どのレースで Claude の axis が当たっているか)
    print("\n=== G. primary_axis correctness vs ROI ===")
    axis_correct = []
    axis_wrong = []
    for r in races:
        if r["status"] != "settled" or not r["actual_combination"] or not r["primary_axis"]:
            continue
        actual_top2 = set(r["actual_combination"].split("-")[:2])
        ax_set = set(str(x) for x in r["primary_axis"])
        rbets = [b for b in bets if b["race_id"] == r["race_id"]]
        if actual_top2 == ax_set:
            axis_correct.extend(rbets)
        else:
            axis_wrong.extend(rbets)
    report(axis_correct, "primary_axis correct (1-2着集合一致)")
    report(axis_wrong, "primary_axis wrong")

    # 8. axis 1着艇正解 (1着のみ) vs 全外し
    print("\n=== H. axis の 1着艇のみ正解の場合 ===")
    axis_1st_only = []
    axis_full_wrong = []
    for r in races:
        if r["status"] != "settled" or not r["actual_combination"] or not r["primary_axis"]:
            continue
        actual_winner = r["actual_combination"].split("-")[0]
        ax = [str(x) for x in r["primary_axis"]]
        rbets = [b for b in bets if b["race_id"] == r["race_id"]]
        if actual_winner == ax[0]:
            axis_1st_only.extend(rbets)
        elif actual_winner not in ax:
            axis_full_wrong.extend(rbets)
    report(axis_1st_only, "axis 1番手 = actual 1着")
    report(axis_full_wrong, "actual 1着 が axis に無し")


if __name__ == "__main__":
    main()
