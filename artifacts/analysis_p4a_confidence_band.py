"""
P4-α confidence-band ROI 再集計 (事前登録された決定ルール)

入力: P4-α 12 日分の eval JSON (Kiryu only, 2025-09 〜 2025-12)
出力: confidence 帯別 ROI + bootstrap 95% CI

採用基準 (3 条件全てを満たす帯):
  1. n_bets >= 100
  2. ROI >= +10%
  3. bootstrap 95% CI 下限 >= 0
"""

import json
import random
from pathlib import Path
from statistics import median

EVAL_DIR = Path("artifacts/eval")
P4A_DAYS = [
    "2025-09-06", "2025-09-21", "2025-09-26",
    "2025-10-07", "2025-10-22", "2025-10-30",
    "2025-11-01", "2025-11-15", "2025-11-29",
    "2025-12-01", "2025-12-15", "2025-12-29",
]

BANDS = [
    ("0.0-0.3", 0.0, 0.3),
    ("0.3-0.5", 0.3, 0.5),
    ("0.5-0.7", 0.5, 0.7),
    ("0.7-1.0", 0.7, 1.000001),
]

BOOTSTRAP_N = 2000
SEED = 42


def load_bets():
    """全 P4-α bet を flatten (settled + verdict=bet のみ)"""
    bets = []
    for day in P4A_DAYS:
        path = EVAL_DIR / f"{day}.json"
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        for race in data["races"]:
            if race.get("status") != "settled":
                continue
            if race.get("verdict") != "bet":
                continue
            for bet in race.get("bets", []) or []:
                bets.append({
                    "date": day,
                    "stake": bet["stake"],
                    "payout": bet["payout"],
                    "is_hit": bet["is_hit"],
                    "confidence": bet["confidence"],
                })
    return bets


def filter_band(bets, lo, hi):
    return [b for b in bets if lo <= b["confidence"] < hi]


def roi(bets):
    s = sum(b["stake"] for b in bets)
    if s == 0:
        return None
    p = sum(b["payout"] for b in bets)
    return p / s - 1


def bootstrap_ci(bets, n=BOOTSTRAP_N, seed=SEED):
    if not bets:
        return None, None
    rng = random.Random(seed)
    rois = []
    n_b = len(bets)
    for _ in range(n):
        sample = [bets[rng.randrange(n_b)] for _ in range(n_b)]
        s = sum(b["stake"] for b in sample)
        p = sum(b["payout"] for b in sample)
        rois.append(p / s - 1 if s > 0 else 0.0)
    rois.sort()
    return rois[int(0.025 * n)], rois[int(0.975 * n)]


def main():
    bets = load_bets()
    overall_roi = roi(bets)
    overall_hits = sum(1 for b in bets if b["is_hit"])

    print(f"P4-α total: n_bets={len(bets)}, n_hits={overall_hits}, ROI={overall_roi*100:.2f}%")
    print()
    print(f"{'band':<10} {'n_bets':>7} {'n_hits':>7} {'hit_rate':>9} {'ROI':>9} {'CI_lo':>9} {'CI_hi':>9} {'pass':>5}")
    print("-" * 75)

    results = []
    for band_name, lo, hi in BANDS:
        sub = filter_band(bets, lo, hi)
        n_bets = len(sub)
        n_hits = sum(1 for b in sub if b["is_hit"])
        hit_rate = n_hits / n_bets if n_bets else None
        r = roi(sub)
        ci_lo, ci_hi = bootstrap_ci(sub) if n_bets else (None, None)

        passes = (
            n_bets >= 100
            and r is not None
            and r >= 0.10
            and ci_lo is not None
            and ci_lo >= 0.0
        )

        results.append({
            "band": band_name,
            "n_bets": n_bets,
            "n_hits": n_hits,
            "hit_rate_per_bet": hit_rate,
            "roi": r,
            "ci_lower": ci_lo,
            "ci_upper": ci_hi,
            "passes_criteria": passes,
        })

        def fmt(x, suffix=""):
            return "n/a" if x is None else f"{x*100:.2f}{suffix}"

        print(
            f"{band_name:<10} {n_bets:>7d} {n_hits:>7d} "
            f"{fmt(hit_rate,'%'):>9} {fmt(r,'%'):>9} {fmt(ci_lo,'%'):>9} {fmt(ci_hi,'%'):>9} "
            f"{'YES' if passes else 'no':>5}"
        )

    print()
    n_pass = sum(1 for r in results if r["passes_criteria"])
    if n_pass == 0:
        print("[VERDICT] 0 / 4 bands pass. -> commit to (P-v) hybrid, full close.")
    else:
        passed = [r["band"] for r in results if r["passes_criteria"]]
        print(f"[VERDICT] {n_pass} / 4 bands pass: {passed}. -> proceed to (C) deviation analysis on these bands.")

    out_path = EVAL_DIR / "p4a_confidence_band_reaggregation.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({
            "input_days": P4A_DAYS,
            "n_days": len(P4A_DAYS),
            "n_bets_total": len(bets),
            "n_hits_total": overall_hits,
            "roi_total": overall_roi,
            "bands": results,
            "criteria": {
                "min_n_bets": 100,
                "min_roi": 0.10,
                "min_ci_lower": 0.0,
            },
            "n_bands_passing": n_pass,
            "bootstrap_n": BOOTSTRAP_N,
            "seed": SEED,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
