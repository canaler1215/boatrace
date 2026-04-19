"""T3: load_or_download_month_trio_odds / download_trio_odds_for_races のユニットテスト"""
import sys
import itertools
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd
import pytest

from collector.odds_downloader import (
    _trio_cache_path,
    _df_to_map,
    download_trio_odds_for_races,
    load_or_download_month_trio_odds,
    load_or_download_month_odds,
    download_odds_for_races,
)

EXPECTED_KEYS = {
    "-".join(map(str, c)) for c in itertools.combinations(range(1, 7), 3)
}

SAMPLE_TRIO_ODDS = {k: float(10 + i) for i, k in enumerate(sorted(EXPECTED_KEYS))}

SAMPLE_RACE_DF = pd.DataFrame([
    {"race_id": "01202510011", "stadium_id": 1, "race_date": "2025-10-01", "race_no": 1},
    {"race_id": "01202510012", "stadium_id": 1, "race_date": "2025-10-01", "race_no": 2},
])


# ---------------------------------------------------------------------------
# _trio_cache_path
# ---------------------------------------------------------------------------

def test_trio_cache_path_format():
    p = _trio_cache_path(2025, 10)
    assert p.name == "trio_odds_202510.parquet"
    assert p.parent.name == "odds"


def test_trio_cache_path_differs_from_trifecta():
    from collector.odds_downloader import _cache_path
    assert _trio_cache_path(2025, 10) != _cache_path(2025, 10)


# ---------------------------------------------------------------------------
# download_trio_odds_for_races — キャッシュなし、ダウンロード成功
# ---------------------------------------------------------------------------

def test_download_trio_returns_correct_map():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"

        with patch("collector.odds_downloader.fetch_trio_odds", return_value=SAMPLE_TRIO_ODDS):
            result = download_trio_odds_for_races(
                SAMPLE_RACE_DF.to_dict("records"), cache_path, max_workers=2
            )

    assert "01202510011" in result
    assert "01202510012" in result
    assert set(result["01202510011"].keys()) == EXPECTED_KEYS


def test_download_trio_saves_parquet():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"

        with patch("collector.odds_downloader.fetch_trio_odds", return_value=SAMPLE_TRIO_ODDS):
            download_trio_odds_for_races(
                SAMPLE_RACE_DF.to_dict("records"), cache_path, max_workers=2
            )

        assert cache_path.exists()
        df = pd.read_parquet(cache_path)
        assert set(df.columns) >= {"race_id", "combination", "odds"}
        assert len(df) == 2 * 20  # 2レース × 20通り


def test_download_trio_partial_cache_removed_after_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"
        partial_path = cache_path.with_suffix(".partial.parquet")

        with patch("collector.odds_downloader.fetch_trio_odds", return_value=SAMPLE_TRIO_ODDS):
            download_trio_odds_for_races(
                SAMPLE_RACE_DF.to_dict("records"), cache_path, max_workers=2
            )

        assert not partial_path.exists()


def test_download_trio_empty_fetch_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"

        with patch("collector.odds_downloader.fetch_trio_odds", return_value={}):
            result = download_trio_odds_for_races(
                SAMPLE_RACE_DF.to_dict("records"), cache_path, max_workers=2
            )

    assert result == {}


def test_download_trio_resumes_from_partial():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"
        partial_path = cache_path.with_suffix(".partial.parquet")

        # 最初のレースが partial に既に保存されている状態を作成
        partial_rows = [
            {"race_id": "01202510011", "combination": k, "odds": v}
            for k, v in SAMPLE_TRIO_ODDS.items()
        ]
        pd.DataFrame(partial_rows).to_parquet(partial_path, index=False)

        call_count = 0

        def mock_fetch(stadium_id, race_date, race_no):
            nonlocal call_count
            call_count += 1
            return SAMPLE_TRIO_ODDS

        with patch("collector.odds_downloader.fetch_trio_odds", side_effect=mock_fetch):
            result = download_trio_odds_for_races(
                SAMPLE_RACE_DF.to_dict("records"), cache_path, max_workers=2
            )

        # 1件だけフェッチされる（残り1レースのみ）
        assert call_count == 1
        assert "01202510011" in result
        assert "01202510012" in result


# ---------------------------------------------------------------------------
# load_or_download_month_trio_odds
# ---------------------------------------------------------------------------

def test_load_from_cache_when_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"

        # キャッシュを作成
        rows = [
            {"race_id": "01202510011", "combination": k, "odds": v}
            for k, v in SAMPLE_TRIO_ODDS.items()
        ]
        pd.DataFrame(rows).to_parquet(cache_path, index=False)

        with patch("collector.odds_downloader._trio_cache_path", return_value=cache_path):
            with patch("collector.odds_downloader.fetch_trio_odds") as mock_fetch:
                result = load_or_download_month_trio_odds(2025, 10, SAMPLE_RACE_DF)
                mock_fetch.assert_not_called()

    assert "01202510011" in result
    assert set(result["01202510011"].keys()) == EXPECTED_KEYS


def test_downloads_when_no_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"

        with patch("collector.odds_downloader._trio_cache_path", return_value=cache_path):
            with patch("collector.odds_downloader.fetch_trio_odds", return_value=SAMPLE_TRIO_ODDS):
                result = load_or_download_month_trio_odds(2025, 10, SAMPLE_RACE_DF)

    assert "01202510011" in result


def test_raises_on_missing_columns():
    bad_df = pd.DataFrame([{"race_id": "01202510011", "stadium_id": 1}])
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "trio_odds_202510.parquet"
        with patch("collector.odds_downloader._trio_cache_path", return_value=cache_path):
            try:
                load_or_download_month_trio_odds(2025, 10, bad_df)
                assert False, "ValueError が発生するはず"
            except ValueError as e:
                assert "race_date" in str(e) or "race_no" in str(e)


# ---------------------------------------------------------------------------
# 後方互換性: 既存の load_or_download_month_odds / download_odds_for_races が壊れていない
# ---------------------------------------------------------------------------

def test_trifecta_download_unaffected():
    """T3 変更後も 3連単のダウンロード関数が正常動作する"""
    sample_trifecta_odds = {"1-2-3": 12.5, "1-2-4": 8.0}
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "odds_202510.parquet"
        with patch("collector.odds_downloader.fetch_odds", return_value=sample_trifecta_odds):
            result = download_odds_for_races(
                SAMPLE_RACE_DF.to_dict("records"), cache_path, max_workers=2
            )
    assert "01202510011" in result
    assert result["01202510011"]["1-2-3"] == 12.5


if __name__ == "__main__":
    tests = [
        test_trio_cache_path_format,
        test_trio_cache_path_differs_from_trifecta,
        test_download_trio_returns_correct_map,
        test_download_trio_saves_parquet,
        test_download_trio_partial_cache_removed_after_success,
        test_download_trio_empty_fetch_returns_empty,
        test_download_trio_resumes_from_partial,
        test_load_from_cache_when_exists,
        test_downloads_when_no_cache,
        test_raises_on_missing_columns,
        test_trifecta_download_unaffected,
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
