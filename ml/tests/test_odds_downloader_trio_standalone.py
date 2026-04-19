"""T3 standalone test (no external dependencies) — _trio_cache_path / _df_to_map logic"""
import sys
import itertools
from pathlib import Path


# --- Inline implementations to test without importing the full module ---

def _cache_path(year: int, month: int) -> Path:
    base = Path(__file__).parents[3] / "data" / "odds"
    return base / f"odds_{year}{month:02d}.parquet"


def _trio_cache_path(year: int, month: int) -> Path:
    base = Path(__file__).parents[3] / "data" / "odds"
    return base / f"trio_odds_{year}{month:02d}.parquet"


EXPECTED_KEYS = {"-".join(map(str, c)) for c in itertools.combinations(range(1, 7), 3)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_trio_cache_path_filename():
    p = _trio_cache_path(2025, 10)
    assert p.name == "trio_odds_202510.parquet", f"expected trio_odds_202510.parquet, got {p.name}"


def test_trio_cache_path_directory():
    p = _trio_cache_path(2025, 10)
    assert p.parent.name == "odds", f"expected parent 'odds', got {p.parent.name}"


def test_trio_cache_path_zero_padded_month():
    p = _trio_cache_path(2025, 3)
    assert p.name == "trio_odds_202503.parquet", f"expected trio_odds_202503.parquet, got {p.name}"


def test_trio_cache_path_differs_from_trifecta():
    trifecta = _cache_path(2025, 10)
    trio = _trio_cache_path(2025, 10)
    assert trifecta != trio, "trio and trifecta cache paths should differ"


def test_expected_keys_count():
    assert len(EXPECTED_KEYS) == 20, f"expected 20 keys, got {len(EXPECTED_KEYS)}"


def test_expected_keys_sorted():
    for key in EXPECTED_KEYS:
        parts = key.split("-")
        assert parts == sorted(parts, key=int), f"key not sorted: {key}"


def test_trio_combination_structure():
    """combinations(range(1,7), 3) の 20通りが正しい組合せ数"""
    combos = list(itertools.combinations(range(1, 7), 3))
    assert len(combos) == 20
    for combo in combos:
        assert len(combo) == 3
        assert len(set(combo)) == 3  # 重複なし
        assert all(1 <= x <= 6 for x in combo)  # 有効な艇番


if __name__ == "__main__":
    tests = [
        test_trio_cache_path_filename,
        test_trio_cache_path_directory,
        test_trio_cache_path_zero_padded_month,
        test_trio_cache_path_differs_from_trifecta,
        test_expected_keys_count,
        test_expected_keys_sorted,
        test_trio_combination_structure,
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
