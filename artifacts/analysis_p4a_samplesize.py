"""3連単の特性に対するサンプルサイズ十分性評価"""
import json
import math
from pathlib import Path
from collections import defaultdict
import random

EVAL_DIR = Path("artifacts/eval")
DATES = [
    "2025-09-06", "2025-09-21", "2025-09-26",
    "2025-10-07", "2025-10-22", "2025-10-30",
    "2025-11-01", "2025-11-15", "2025-11-29",
    "2025-12-01", "2025-12-15", "2025-12-29",
]

bets = []
for d in DATES:
    with open(EVAL_DIR / f"{d}.json", encoding="utf-8") as f:
        data = json.load(f)
    for r in data["races"]:
        for b in r.get("bets", []):
            bets.append({
                "stake": b["stake"],
                "payout": b.get("payout", 0.0),
                "is_hit": b.get("is_hit", False),
                "actual_odds": b.get("actual_odds", 0),
            })

n = len(bets)
hits = [b for b in bets if b["is_hit"]]
n_hits = len(hits)
total_stake = sum(b["stake"] for b in bets)
total_payout = sum(b["payout"] for b in bets)
roi = (total_payout - total_stake) / total_stake
hit_rate = n_hits / n

print(f"=== サンプル概要 ===")
print(f"bets={n}, hits={n_hits}, hit_rate={hit_rate*100:.2f}%")
print(f"ROI={roi*100:+.2f}%")
print(f"total_stake={total_stake}, total_payout={total_payout:.0f}")

# 1. 配当の分布特性
hit_payouts = [b["payout"] for b in hits]
hit_odds = [b["actual_odds"] for b in hits]
print(f"\n=== 的中時オッズ分布 (n={n_hits}) ===")
hit_odds_sorted = sorted(hit_odds)
print(f"  min={min(hit_odds):.1f}x, max={max(hit_odds):.1f}x")
print(f"  mean={sum(hit_odds)/len(hit_odds):.1f}x, median={hit_odds_sorted[n_hits//2]:.1f}x")
print(f"  P25={hit_odds_sorted[n_hits//4]:.1f}x, P75={hit_odds_sorted[3*n_hits//4]:.1f}x")
print(f"  分布: ", end="")
bands = [(0,5), (5,10), (10,15), (15,20), (20,30), (30,50), (50,200)]
for lo, hi in bands:
    cnt = sum(1 for o in hit_odds if lo <= o < hi)
    print(f"{lo}-{hi}x:{cnt}  ", end="")
print()

# 2. bet payoff の SD (これがサンプルサイズの本質)
payoffs = [b["payout"] - b["stake"] for b in bets]  # 1 bet あたりの損益
mean_payoff = sum(payoffs) / n
sd_payoff = math.sqrt(sum((p - mean_payoff)**2 for p in payoffs) / n)
print(f"\n=== bet 単位の損益分布 ===")
print(f"  mean payoff = {mean_payoff:+.2f} yen / bet (= ROI {mean_payoff/100*100:+.2f}%)")
print(f"  SD payoff   = {sd_payoff:.2f} yen / bet")
print(f"  CV (SD/|mean|) = {sd_payoff/abs(mean_payoff) if mean_payoff else 'inf':.1f}")

# 3. 必要サンプルサイズ (片側検定で「真の ROI ≥ +10%」と「ROI = 0%」を有意水準 5% で区別)
# Effect size = (mu_alt - mu_null) / sigma
# n = ((Z_a + Z_b) * sigma / (mu_alt - mu_null))^2
alpha = 0.05
power = 0.80
Z_alpha = 1.645  # 片側 5%
Z_beta = 0.842   # power 80%
print(f"\n=== 必要サンプルサイズ (検出力 {power*100:.0f}%) ===")
for target_roi in [0.05, 0.10, 0.15, 0.20]:
    target_yen = target_roi * 100  # ROI を yen 損益単位に
    delta = target_yen - 0  # null hypothesis = 0
    n_needed = ((Z_alpha + Z_beta) * sd_payoff / delta) ** 2
    days = n_needed / 50  # 1 day ~50 bets
    months = days / 30
    print(f"  true ROI = +{target_roi*100:.0f}% vs 0%: n_needed = {n_needed:.0f} bets, {days:.0f} days, {months:.1f} months")

# 4. 現状の CI 幅から見たサンプル必要量
# CI half-width = Z * SD / sqrt(n)
# 現状 CI 幅: bootstrap [-34.2, +30.0] = ±32pp
# CI 下限 ≥ 0 にするには CI 幅 ≤ ROI*2 = 5.6pp 必要
print(f"\n=== CI 幅から見た必要サンプル ===")
current_ci_width_pp = 32  # 現状半幅
# 半幅 = 1.96 * SD / sqrt(n) (yen 単位)
# 半幅 (% ROI) = 1.96 * SD / sqrt(n) / stake_per_bet
# n_target / n_current = (current_ci / target_ci)^2
for target_ci_width in [25, 20, 15, 10, 5]:
    n_target = n * (current_ci_width_pp / target_ci_width) ** 2
    days = n_target / 50
    print(f"  CI half-width +/-{target_ci_width}pp: n={n_target:.0f} bets, {days:.0f} days")

# 5. ROI 真値の確率分布 (bootstrap で再評価)
print(f"\n=== Bootstrap 95% CI 再算出 (N=2000) ===")
rng = random.Random(42)
roi_samples = []
for _ in range(2000):
    sample = [bets[rng.randint(0, n-1)] for _ in range(n)]
    s = sum(b["stake"] for b in sample)
    p = sum(b["payout"] for b in sample)
    roi_samples.append((p - s) / s if s else 0)
roi_samples.sort()
print(f"  mean = {sum(roi_samples)/len(roi_samples)*100:+.2f}%")
print(f"  P2.5  = {roi_samples[50]*100:+.2f}%")
print(f"  P25   = {roi_samples[500]*100:+.2f}%")
print(f"  P50   = {roi_samples[1000]*100:+.2f}%")
print(f"  P75   = {roi_samples[1500]*100:+.2f}%")
print(f"  P97.5 = {roi_samples[1950]*100:+.2f}%")

# 6. P(true ROI > 0) と P(true ROI > +10%)
p_pos = sum(1 for r in roi_samples if r > 0) / len(roi_samples)
p_10 = sum(1 for r in roi_samples if r > 0.10) / len(roi_samples)
p_neg10 = sum(1 for r in roi_samples if r < -0.10) / len(roi_samples)
p_neg20 = sum(1 for r in roi_samples if r < -0.20) / len(roi_samples)
print(f"\n=== 確率推定 ===")
print(f"  P(真の ROI > 0%)  = {p_pos*100:.1f}%")
print(f"  P(真の ROI > +10%) = {p_10*100:.1f}%")
print(f"  P(真の ROI < -10%) = {p_neg10*100:.1f}%")
print(f"  P(真の ROI < -20%) = {p_neg20*100:.1f}%")

# 7. ヒット 1-2 増減で ROI どう変わるか
print(f"\n=== Hit 数 ±N の感度分析 ===")
avg_payout_per_hit = total_payout / n_hits
print(f"  平均 payout/hit = {avg_payout_per_hit:.0f} yen")
for delta in [-3, -2, -1, 0, +1, +2, +3]:
    hyp_hits = n_hits + delta
    hyp_payout = avg_payout_per_hit * hyp_hits
    hyp_roi = (hyp_payout - total_stake) / total_stake
    print(f"  hits = {hyp_hits} (Δ{delta:+d}): hit_rate = {hyp_hits/n*100:.2f}%, ROI = {hyp_roi*100:+.2f}%")
