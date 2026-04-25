"""
PoC c: ST ばらつき特徴量（racer_st_std / racer_late_rate）の単体テスト

検証項目:
  1. 既知データに対して期待値どおりのばらつきが計算される
  2. NaN を生まない（履歴不足は全体平均で補完）
  3. ルックアヘッドなし（自身の行は計算に使わない）
  4. extra_features 未指定なら従来 12 次元のまま
  5. 不正な extra_features 名で ValueError
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.feature_builder import (  # noqa: E402
    FEATURE_COLUMNS,
    EXTRA_FEATURE_REGISTRY,
    build_features_from_history,
    _add_racer_st_dispersion,
    _LATE_ST_THRESHOLD,
)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """テスト用の最小 DataFrame（race_date は string でも ok）"""
    df = pd.DataFrame(rows)
    df["race_date"] = pd.to_datetime(df["race_date"])
    return df


def test_st_dispersion_no_lookahead():
    """racer A の 4 レース。各行の std/late_rate は当該行を含まないこと。"""
    df = _make_df([
        # racer 1: ST = 0.10, 0.30, 0.15, 0.18
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": 1,
         "racer_id": 1, "start_timing": 0.10, "finish_position": 1},
        {"race_date": "2024-01-02", "race_id": "r2", "boat_no": 1,
         "racer_id": 1, "start_timing": 0.30, "finish_position": 6},
        {"race_date": "2024-01-03", "race_id": "r3", "boat_no": 1,
         "racer_id": 1, "start_timing": 0.15, "finish_position": 2},
        {"race_date": "2024-01-04", "race_id": "r4", "boat_no": 1,
         "racer_id": 1, "start_timing": 0.18, "finish_position": 3},
    ])

    out = _add_racer_st_dispersion(df).sort_values("race_date").reset_index(drop=True)

    # 1 件目: 履歴なし → 全体平均で補完される（NaN ではない）
    assert not pd.isna(out.loc[0, "racer_st_std"])
    assert not pd.isna(out.loc[0, "racer_late_rate"])

    # 2 件目: 履歴 1 件のみ → std は min_periods=2 で NaN → 全体平均で補完
    # (NaN にならないことを確認)
    assert not pd.isna(out.loc[1, "racer_st_std"])

    # 3 件目: 過去 [0.10, 0.30] の std = 0.1414...  late_rate = 1/2 = 0.5
    assert out.loc[2, "racer_st_std"] == pytest.approx(np.std([0.10, 0.30], ddof=1), rel=1e-6)
    assert out.loc[2, "racer_late_rate"] == pytest.approx(0.5)

    # 4 件目: 過去 [0.10, 0.30, 0.15] の std と late_rate = 1/3
    assert out.loc[3, "racer_st_std"] == pytest.approx(
        np.std([0.10, 0.30, 0.15], ddof=1), rel=1e-6
    )
    assert out.loc[3, "racer_late_rate"] == pytest.approx(1 / 3)


def test_st_dispersion_no_nan_when_missing_history():
    """履歴ゼロでも NaN を返さないこと"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": 1,
         "racer_id": 99, "start_timing": 0.15, "finish_position": 1},
    ])
    out = _add_racer_st_dispersion(df)
    assert not out["racer_st_std"].isna().any()
    assert not out["racer_late_rate"].isna().any()


def test_st_dispersion_late_threshold_boundary():
    """ST が _LATE_ST_THRESHOLD ちょうどは late 扱い（>= で判定）"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": 1,
         "racer_id": 7, "start_timing": _LATE_ST_THRESHOLD, "finish_position": 1},
        {"race_date": "2024-01-02", "race_id": "r2", "boat_no": 1,
         "racer_id": 7, "start_timing": 0.10, "finish_position": 1},
        {"race_date": "2024-01-03", "race_id": "r3", "boat_no": 1,
         "racer_id": 7, "start_timing": 0.10, "finish_position": 1},
    ])
    out = _add_racer_st_dispersion(df).sort_values("race_date").reset_index(drop=True)
    # 3 件目: 過去 2 件 [boundary, 0.10] → late 1/2
    assert out.loc[2, "racer_late_rate"] == pytest.approx(0.5)


def test_extra_features_unknown_raises():
    """登録外の extra_features 名で ValueError"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": 1,
         "racer_id": 1, "start_timing": 0.15, "finish_position": 1,
         "stadium_id": 1, "race_no": 1},
    ])
    with pytest.raises(ValueError, match="unknown extra_features"):
        build_features_from_history(df, extra_features=["bogus_feature_xyz"])


def test_extra_features_default_unchanged():
    """extra_features を指定しなければ従来 12 次元のまま"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": i,
         "racer_id": i, "start_timing": 0.15, "finish_position": i,
         "stadium_id": 1, "race_no": 1, "racer_grade": "A1",
         "racer_win_rate": 0.5, "motor_win_rate": 0.4, "boat_win_rate": 0.4,
         "exhibition_time": 6.7, "wind_direction": 1, "wind_speed": 2.0}
        for i in range(1, 7)
    ])
    X, _ = build_features_from_history(df)
    assert list(X.columns) == FEATURE_COLUMNS
    assert X.shape[1] == 12


def test_extra_features_appended():
    """extra_features 指定で末尾に追加列が出ること"""
    df = _make_df([
        {"race_date": "2024-01-01", "race_id": "r1", "boat_no": i,
         "racer_id": i, "start_timing": 0.15, "finish_position": i,
         "stadium_id": 1, "race_no": 1, "racer_grade": "A1",
         "racer_win_rate": 0.5, "motor_win_rate": 0.4, "boat_win_rate": 0.4,
         "exhibition_time": 6.7, "wind_direction": 1, "wind_speed": 2.0}
        for i in range(1, 7)
    ])
    X, _ = build_features_from_history(
        df, extra_features=["racer_st_std", "racer_late_rate"]
    )
    assert list(X.columns) == FEATURE_COLUMNS + ["racer_st_std", "racer_late_rate"]
    assert X.shape[1] == 14
    assert not X.isna().any().any()


def test_registry_sanity():
    """登録名が PoC c の 2 つを含む"""
    assert "racer_st_std" in EXTRA_FEATURE_REGISTRY
    assert "racer_late_rate" in EXTRA_FEATURE_REGISTRY
