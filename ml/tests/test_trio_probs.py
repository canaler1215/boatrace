"""T1: calc_trio_probs のユニットテスト"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
from model.predictor import calc_trio_probs, calc_trifecta_probs


def test_entry_count():
    probs = np.array([0.3, 0.25, 0.2, 0.15, 0.07, 0.03])
    trio = calc_trio_probs(probs)
    assert len(trio) == 20, f"期待20エントリ、実際{len(trio)}"


def test_keys_are_sorted():
    probs = np.array([0.3, 0.25, 0.2, 0.15, 0.07, 0.03])
    trio = calc_trio_probs(probs)
    for k in trio:
        parts = k.split("-")
        assert parts == sorted(parts), f"キーがソートされていない: {k}"


def test_sum_to_one():
    probs = np.array([0.3, 0.25, 0.2, 0.15, 0.07, 0.03])
    trio = calc_trio_probs(probs)
    total = sum(trio.values())
    assert abs(total - 1.0) < 1e-9, f"合計が1.0でない: {total:.8f}"


def test_sum_to_one_uniform():
    probs = np.ones(6) / 6
    trio = calc_trio_probs(probs)
    total = sum(trio.values())
    assert abs(total - 1.0) < 1e-9, f"均等確率: 合計が1.0でない: {total:.8f}"


def test_uniform_equal_probs():
    probs = np.ones(6) / 6
    trio = calc_trio_probs(probs)
    vals = list(trio.values())
    # 均等確率なら全20通りが等確率 = 1/20 = 0.05
    assert max(vals) - min(vals) < 1e-9, "均等確率なら全エントリ等確率"
    assert abs(vals[0] - 1.0 / 20) < 1e-9, f"均等確率: 各エントリ={vals[0]:.6f}, 期待={1/20:.6f}"


def test_consistency_with_trifecta():
    """3連複 = 対応する3連単6通りの合計 であることを確認"""
    probs = np.array([0.3, 0.25, 0.2, 0.15, 0.07, 0.03])
    trio = calc_trio_probs(probs)
    trifecta = calc_trifecta_probs(probs)

    for combo_key, trio_prob in trio.items():
        boats = set(combo_key.split("-"))
        trifecta_sum = sum(
            v for k, v in trifecta.items() if set(k.split("-")) == boats
        )
        assert abs(trio_prob - trifecta_sum) < 1e-9, (
            f"整合性エラー {combo_key}: trio={trio_prob:.8f}, 3連単合計={trifecta_sum:.8f}"
        )


def test_all_keys_present():
    from itertools import combinations
    probs = np.ones(6) / 6
    trio = calc_trio_probs(probs)
    expected_keys = {"-".join(map(str, c)) for c in combinations(range(1, 7), 3)}
    assert set(trio.keys()) == expected_keys


def test_nonnegative():
    probs = np.array([0.5, 0.3, 0.1, 0.05, 0.03, 0.02])
    trio = calc_trio_probs(probs)
    for k, v in trio.items():
        assert v >= 0, f"負の確率: {k}={v}"


if __name__ == "__main__":
    tests = [
        test_entry_count,
        test_keys_are_sorted,
        test_sum_to_one,
        test_sum_to_one_uniform,
        test_uniform_equal_probs,
        test_consistency_with_trifecta,
        test_all_keys_present,
        test_nonnegative,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {t.__name__} — {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {t.__name__} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} passed")
    sys.exit(0 if failed == 0 else 1)
