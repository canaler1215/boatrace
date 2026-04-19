"""T2: fetch_trio_odds のユニットテスト（HTTPモック使用）"""
import sys
import itertools
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bs4 import BeautifulSoup
from collector.openapi_client import fetch_trio_odds


EXPECTED_KEYS = {
    "-".join(map(str, c)) for c in itertools.combinations(range(1, 7), 3)
}


def _make_soup_data_combination(sorted_keys: bool = True) -> BeautifulSoup:
    """data-combination 属性付き HTML を生成"""
    tds = []
    for combo in itertools.combinations(range(1, 7), 3):
        if sorted_keys:
            key = "-".join(map(str, combo))
        else:
            # 逆順にしてソートされていないケースを模擬
            key = "-".join(map(str, reversed(combo)))
        odds_val = float(10 + sum(combo))
        tds.append(f'<td data-combination="{key}">{odds_val}</td>')
    html = "<table><tr>" + "".join(tds) + "</tr></table>"
    return BeautifulSoup(html, "lxml")


def _make_soup_odds_point() -> BeautifulSoup:
    """class=oddsPoint セル20個の HTML を生成（data-combination なし）"""
    tds = []
    for i, combo in enumerate(itertools.combinations(range(1, 7), 3)):
        odds_val = float(10 + i)
        tds.append(f'<td class="oddsPoint">{odds_val}</td>')
    html = "<table><tr>" + "".join(tds) + "</tr></table>"
    return BeautifulSoup(html, "lxml")


def _make_soup_wrong_count(n: int = 15) -> BeautifulSoup:
    """セル数が不正な HTML"""
    tds = [f'<td class="oddsPoint">{float(i)}</td>' for i in range(n)]
    html = "<table><tr>" + "".join(tds) + "</tr></table>"
    return BeautifulSoup(html, "lxml")


def _patch_get(soup: BeautifulSoup):
    return patch("collector.openapi_client._get", return_value=soup)


def test_returns_20_entries_data_combination():
    with _patch_get(_make_soup_data_combination()):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    assert len(result) == 20, f"期待20エントリ、実際{len(result)}"


def test_keys_are_sorted_data_combination():
    with _patch_get(_make_soup_data_combination()):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    for k in result:
        parts = k.split("-")
        assert parts == sorted(parts, key=int), f"キーがソートされていない: {k}"


def test_all_expected_keys_data_combination():
    with _patch_get(_make_soup_data_combination()):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    assert set(result.keys()) == EXPECTED_KEYS


def test_unsorted_data_combination_normalized():
    """data-combination が逆順でもキーを正規化する"""
    with _patch_get(_make_soup_data_combination(sorted_keys=False)):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    assert len(result) == 20
    for k in result:
        parts = k.split("-")
        assert parts == sorted(parts, key=int), f"キーがソートされていない: {k}"
    assert set(result.keys()) == EXPECTED_KEYS


def test_positive_odds_data_combination():
    with _patch_get(_make_soup_data_combination()):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    for k, v in result.items():
        assert v > 0, f"オッズが0以下: {k}={v}"


def test_fallback_odds_point_20_cells():
    with _patch_get(_make_soup_odds_point()):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    assert len(result) == 20
    assert set(result.keys()) == EXPECTED_KEYS


def test_fallback_odds_point_values_match_order():
    """フォールバック時は combinations 順に値が対応している"""
    with _patch_get(_make_soup_odds_point()):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    for i, combo in enumerate(itertools.combinations(range(1, 7), 3)):
        key = "-".join(map(str, combo))
        assert result[key] == float(10 + i), f"{key}: 期待{10+i}, 実際{result[key]}"


def test_fallback_wrong_count_returns_empty():
    """セル数が20でない場合は空を返す"""
    with _patch_get(_make_soup_wrong_count(15)):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    assert result == {}


def test_empty_page_returns_empty():
    soup = BeautifulSoup("<html></html>", "lxml")
    with _patch_get(soup):
        result = fetch_trio_odds(1, "2025-10-01", 1)
    assert result == {}


if __name__ == "__main__":
    tests = [
        test_returns_20_entries_data_combination,
        test_keys_are_sorted_data_combination,
        test_all_expected_keys_data_combination,
        test_unsorted_data_combination_normalized,
        test_positive_odds_data_combination,
        test_fallback_odds_point_20_cells,
        test_fallback_odds_point_values_match_order,
        test_fallback_wrong_count_returns_empty,
        test_empty_page_returns_empty,
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
    import sys as _sys
    _sys.exit(0 if failed == 0 else 1)
