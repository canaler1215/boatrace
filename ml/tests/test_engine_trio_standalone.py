"""T4 standalone test — engine.py の3連複対応検証 (依存なし)"""
from itertools import combinations, permutations

# ── 再実装（依存なしで検証） ────────────────────────────────────────────

BOAT_WIN_RATES = {1: 0.450, 2: 0.150, 3: 0.130, 4: 0.110, 5: 0.090, 6: 0.070}
PAYOUT_RATE = 0.75


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


def _calc_market_trio_probs():
    rates = BOAT_WIN_RATES
    result = {}
    for combo in combinations(range(1, 7), 3):
        prob = 0.0
        for perm in permutations(combo):
            a, b, c = perm
            denom_b = 1.0 - rates[a]
            denom_c = denom_b - rates[b]
            prob += rates[a] * (rates[b] / max(denom_b, 1e-9)) * (rates[c] / max(denom_c, 1e-9))
        result["-".join(map(str, combo))] = float(prob)
    return result


def _is_trio_hit(actual_combo, trio_combo):
    if actual_combo is None:
        return False
    return frozenset(actual_combo.split("-")) == frozenset(trio_combo.split("-"))


# ── テストヘルパー ───────────────────────────────────────────────────────

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


# ── テスト: SYNTHETIC_TRIO_ODDS ──────────────────────────────────────────

print("=== SYNTHETIC_TRIO_ODDS ===")
market = _calc_market_trio_probs()
total = sum(market.values())
check("エントリ数=20", len(market) == 20, str(len(market)))
check("合計確率≒1.0", abs(total - 1.0) < 1e-9, f"{total:.10f}")
check("全確率>=0", all(v >= 0 for v in market.values()))
check("キーがソート済み", all(k == "-".join(sorted(k.split("-"))) for k in market))

synthetic_trio = {k: round(PAYOUT_RATE / max(v, 1e-9), 2) for k, v in market.items()}
check("合成オッズ(1-2-3)が最低", synthetic_trio["1-2-3"] < synthetic_trio["4-5-6"])
print(f"  1-2-3: {synthetic_trio['1-2-3']}x  4-5-6: {synthetic_trio['4-5-6']}x")

# ── テスト: _is_trio_hit ──────────────────────────────────────────────────

print("\n=== _is_trio_hit ===")
cases = [
    ("1-2-3", "1-2-3", True, "完全一致"),
    ("2-1-3", "1-2-3", True, "順番違い (2着1着3着)"),
    ("3-2-1", "1-2-3", True, "逆順"),
    ("1-2-4", "1-2-3", False, "異なる艇番"),
    (None, "1-2-3", False, "actual=None"),
    ("1-2-3-4", "1-2-3", False, "4艇文字列（異常系）"),
]
for actual, trio, expected, label in cases:
    result = _is_trio_hit(actual, trio)
    check(label, result == expected, f"got={result}")

# ── テスト: calc_trio_probs と整合性 ────────────────────────────────────

print("\n=== calc_trio_probs ===")
win_probs = [0.3, 0.25, 0.2, 0.15, 0.07, 0.03]
trio_probs = calc_trio_probs(win_probs)
check("エントリ数=20", len(trio_probs) == 20)
check("合計確率≒1.0", abs(sum(trio_probs.values()) - 1.0) < 1e-9)

# ── テスト: 的中判定シミュレーション ────────────────────────────────────

print("\n=== 的中判定シミュレーション ===")
# actual = 2-1-3 (2着1番、1着2番、3着3番 → 3連単2-1-3、3連複1-2-3)
actual_trifecta = "2-1-3"
trio_combo_hit = "1-2-3"
trio_combo_miss = "1-2-4"

check("trio_hit 正しく判定", _is_trio_hit(actual_trifecta, trio_combo_hit))
check("trio_miss 正しく判定", not _is_trio_hit(actual_trifecta, trio_combo_miss))

# 3連単的中は3連複も的中するはず
trifecta_combo = "1-2-3"
actual_exact = "1-2-3"
check("3連単完全一致 → 3連複も的中", _is_trio_hit(actual_exact, trifecta_combo))

print(f"\n{passed}/{passed+failed} passed")
import sys
sys.exit(0 if failed == 0 else 1)
