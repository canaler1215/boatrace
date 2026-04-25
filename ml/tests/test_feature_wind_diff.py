"""
PoC a: 直前気象差分（wind_speed_diff）の単体テスト
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.feature_builder import (  # noqa: E402
    EXTRA_FEATURE_REGISTRY,
    build_features_from_history,
    _add_wind_speed_diff,
)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "race_date" in df.columns:
        df["race_date"] = pd.to_datetime(df["race_date"])
    return df


def test_wind_speed_diff_no_lookahead():
    """場 1 の 3 レース wind_speed=[2.0, 4.0, 6.0]。各行の差分は過去平均との差で当該行は使わない。"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": 1,
         "stadium_id": 1, "wind_speed": 2.0},
        {"race_date": "2024-01-02", "race_id": "r2", "boat_no": 1,
         "stadium_id": 1, "wind_speed": 4.0},
        {"race_date": "2024-01-03", "race_id": "r3", "boat_no": 1,
         "stadium_id": 1, "wind_speed": 6.0},
    ])

    out = _add_wind_speed_diff(df).sort_values("race_date").reset_index(drop=True)

    # 1 件目: 過去なし → 全体平均で補完 (mean=4.0)。diff = 2.0 - 4.0 = -2.0
    assert out.loc[0, "wind_speed_diff"] == pytest.approx(2.0 - 4.0)
    # 2 件目: 過去 [2.0] の mean=2.0 → diff = 4.0 - 2.0 = 2.0
    assert out.loc[1, "wind_speed_diff"] == pytest.approx(4.0 - 2.0)
    # 3 件目: 過去 [2.0, 4.0] の mean=3.0 → diff = 6.0 - 3.0 = 3.0
    assert out.loc[2, "wind_speed_diff"] == pytest.approx(6.0 - 3.0)


def test_wind_speed_diff_per_stadium_independent():
    """場 1 と場 2 で履歴が混ざらないこと"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": 1,
         "stadium_id": 1, "wind_speed": 5.0},
        {"race_date": "2024-01-01", "race_id": "r2", "boat_no": 1,
         "stadium_id": 2, "wind_speed": 1.0},
        {"race_date": "2024-01-02", "race_id": "r3", "boat_no": 1,
         "stadium_id": 1, "wind_speed": 7.0},
    ])
    out = _add_wind_speed_diff(df).sort_values(["race_date", "race_id"]).reset_index(drop=True)

    # 3 件目（場 1）の過去は場 1 の [5.0] のみ → diff = 7.0 - 5.0 = 2.0
    target = out[(out["stadium_id"] == 1) & (out["race_id"] == "r3")].iloc[0]
    assert target["wind_speed_diff"] == pytest.approx(7.0 - 5.0)


def test_wind_speed_diff_no_nan():
    """NaN を出さないこと"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": 1,
         "stadium_id": 1, "wind_speed": None},
    ])
    out = _add_wind_speed_diff(df)
    assert not out["wind_speed_diff"].isna().any()


def test_wind_speed_diff_registered():
    assert "wind_speed_diff" in EXTRA_FEATURE_REGISTRY


def test_wind_speed_diff_in_build_features():
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": i,
         "racer_id": i, "start_timing": 0.15, "finish_position": i,
         "stadium_id": 1, "race_no": 1, "racer_grade": "A1",
         "racer_win_rate": 0.5, "motor_win_rate": 0.4, "boat_win_rate": 0.4,
         "exhibition_time": 6.7, "wind_direction": 1, "wind_speed": 3.0}
        for i in range(1, 7)
    ])
    X, _ = build_features_from_history(df, extra_features=["wind_speed_diff"])
    assert "wind_speed_diff" in X.columns
    assert not X.isna().any().any()
