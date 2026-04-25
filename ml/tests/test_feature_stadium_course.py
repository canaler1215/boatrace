"""
PoC b: 場×コース勝率特徴量（course_win_rate）の単体テスト
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.feature_builder import (  # noqa: E402
    FEATURE_COLUMNS,
    EXTRA_FEATURE_REGISTRY,
    build_features_from_history,
)
from features.stadium_features import (  # noqa: E402
    STADIUM_COURSE_WIN_RATE,
    DEFAULT_COURSE_WIN_RATE,
    add_stadium_course_features,
)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "race_date" in df.columns:
        df["race_date"] = pd.to_datetime(df["race_date"])
    return df


def test_course_win_rate_uses_default_when_table_empty(monkeypatch):
    """テーブル未登録の場では DEFAULT_COURSE_WIN_RATE を返す"""
    df = _make_df([
        {"stadium_id": 999, "boat_no": 1},
        {"stadium_id": 999, "boat_no": 6},
    ])
    out = add_stadium_course_features(df)
    assert out.loc[0, "course_win_rate"] == DEFAULT_COURSE_WIN_RATE[1]
    assert out.loc[1, "course_win_rate"] == DEFAULT_COURSE_WIN_RATE[6]


def test_course_win_rate_uses_table_when_present(monkeypatch):
    """テーブルにある場は per-stadium 値を返す"""
    monkeypatch.setitem(STADIUM_COURSE_WIN_RATE, 13, {1: 0.689, 2: 0.18, 3: 0.10,
                                                       4: 0.07, 5: 0.04, 6: 0.02})
    df = _make_df([
        {"stadium_id": 13, "boat_no": 1},
        {"stadium_id": 13, "boat_no": 4},
    ])
    out = add_stadium_course_features(df)
    assert out.loc[0, "course_win_rate"] == pytest.approx(0.689)
    assert out.loc[1, "course_win_rate"] == pytest.approx(0.07)


def test_course_win_rate_no_nan():
    """NaN を絶対に出さないこと（学習時の fillna(0) 経由でも数値で確実に埋まる）"""
    df = _make_df([
        {"stadium_id": None, "boat_no": 3},
        {"stadium_id": 1, "boat_no": None},
    ])
    out = add_stadium_course_features(df)
    assert not out["course_win_rate"].isna().any()


def test_extra_feature_course_appended():
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": i,
         "racer_id": i, "start_timing": 0.15, "finish_position": i,
         "stadium_id": 1, "race_no": 1, "racer_grade": "A1",
         "racer_win_rate": 0.5, "motor_win_rate": 0.4, "boat_win_rate": 0.4,
         "exhibition_time": 6.7, "wind_direction": 1, "wind_speed": 2.0}
        for i in range(1, 7)
    ])
    X, _ = build_features_from_history(df, extra_features=["course_win_rate"])
    assert "course_win_rate" in X.columns
    assert list(X.columns)[-1] == "course_win_rate"
    assert not X.isna().any().any()


def test_registry_has_course_win_rate():
    assert "course_win_rate" in EXTRA_FEATURE_REGISTRY
