"""T1 standalone test (numpy-free)"""
from itertools import combinations, permutations


def calc_trio_probs(win_probs):
    total = sum(win_probs)
    p = [x / max(total, 1e-9) for x in win_probs]
    result = {}
    for combo in combinations(range(1, 7), 3):
        key = "-".join(map(str, combo))
        prob = 0.0
        for perm in permutations(combo):
            a, b, c = perm[0] - 1, perm[1] - 1, perm[2] - 1
            denom_b = 1.0 - p[a]
            denom_c = 1.0 - p[a] - p[b]
            if denom_b > 0 and denom_c > 0:
                prob += p[a] * (p[b] / denom_b) * (p[c] / denom_c)
        result[key] = float(prob)
    return result


def calc_trifecta_probs(win_probs):
    total = sum(win_probs)
    p = [x / max(total, 1e-9) for x in win_probs]
    result = {}
    for combo in permutations(range(1, 7), 3):
        p1 = p[combo[0] - 1]
        p2 = p[combo[1] - 1] / max(1 - p1, 1e-9)
        p3 = p[combo[2] - 1] / max(1 - p1 - p[combo[1] - 1], 1e-9)
        result[f"{combo[0]}-{combo[1]}-{combo[2]}"] = p1 * p2 * p3
    return result


passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))
        failed += 1


win_probs = [0.3, 0.25, 0.2, 0.15, 0.07, 0.03]
trio = calc_trio_probs(win_probs)

check("エントリ数=20", len(trio) == 20, str(len(trio)))
check("キーがソート済み", all(k == "-".join(sorted(k.split("-"))) for k in trio))

total = sum(trio.values())
check("合計確率≒1.0", abs(total - 1.0) < 1e-9, f"{total:.10f}")

uniform = [1 / 6] * 6
trio_u = calc_trio_probs(uniform)
total_u = sum(trio_u.values())
check("均等確率の合計≒1.0", abs(total_u - 1.0) < 1e-9, f"{total_u:.10f}")

vals_u = list(trio_u.values())
check(
    "均等確率では全エントリ=1/20",
    max(vals_u) - min(vals_u) < 1e-9 and abs(vals_u[0] - 1.0 / 20) < 1e-9,
    f"max={max(vals_u):.8f} min={min(vals_u):.8f}",
)

trifecta = calc_trifecta_probs(win_probs)
mismatch = [
    f"{k}: trio={v:.8f}, 3連単合計={sum(tv for tk,tv in trifecta.items() if set(tk.split('-'))==set(k.split('-'))):.8f}"
    for k, v in trio.items()
    if abs(v - sum(tv for tk, tv in trifecta.items() if set(tk.split("-")) == set(k.split("-")))) >= 1e-9
]
check("3連単との整合性", len(mismatch) == 0, str(mismatch[:2]))

expected_keys = {"-".join(map(str, c)) for c in combinations(range(1, 7), 3)}
check("全20キー一致", set(trio.keys()) == expected_keys)

check("全確率>=0", all(v >= 0 for v in trio.values()))

print(f"\n上位5エントリ:")
for k, v in sorted(trio.items(), key=lambda x: -x[1])[:5]:
    print(f"  {k}: {v:.4f}")

print(f"\n{passed}/{passed+failed} passed")
import sys
sys.exit(0 if failed == 0 else 1)
