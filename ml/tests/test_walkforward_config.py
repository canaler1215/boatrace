"""
run_walkforward.py の config 対応テスト（MODEL_LOOP_PLAN タスク 2）

検証項目:
  1. build_sample_weight: config=None / mode=None → None を返す
  2. build_sample_weight: mode="recency" → 直近 N ヶ月のみ weight 倍、
     ref_date 境界で正しく切り替わる
  3. build_sample_weight: mode="exp_decay" → 単調減少、ref_date 同日で 1.0
  4. build_sample_weight: 未知 mode → ValueError
  5. build_features_from_history(return_dates=True) → X と race_dates の長さが一致、
     インデックス整合、dtype が datetime
  6. build_features_from_history の後方互換: return_dates を渡さなければ従来の (X, y)
  7. get_model_for_month: trial_config が None なら既存動作（モック下）
  8. get_model_for_month: trial_config に lgb_params を渡すと train() に伝搬する

ネットワーク・DB 不要。合成データで完結。
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

# run_walkforward.py は scripts/ 配下。sys.path で直接 import できるよう追加。
sys.path.insert(0, str(ROOT / "src" / "scripts"))


# ---------------------------------------------------------------------------
# build_sample_weight
# ---------------------------------------------------------------------------

from run_walkforward import build_sample_weight  # noqa: E402


def _dates_series(start: str, periods: int, freq: str = "D") -> pd.Series:
    return pd.Series(pd.date_range(start=start, periods=periods, freq=freq))


def test_sample_weight_none_config():
    dates = _dates_series("2024-01-01", 10)
    assert build_sample_weight(dates, pd.Timestamp("2025-12-31"), None) is None
    assert build_sample_weight(dates, pd.Timestamp("2025-12-31"), {}) is None
    assert build_sample_weight(dates, pd.Timestamp("2025-12-31"), {"mode": None}) is None


def test_sample_weight_recency_boundary():
    # ref_date = 2025-12-31, recency_months=6, weight=3.0
    # → 2025-06-30 以降は 3.0、それより前は 1.0
    # 注: cutoff = ref - 6 months = 2025-06-30, cutoff 以降の dates が重み対象
    dates = pd.Series(pd.to_datetime([
        "2024-01-01",   # 古い → 1.0
        "2025-01-01",   # 古い → 1.0
        "2025-06-29",   # cutoff 直前 → 1.0
        "2025-06-30",   # cutoff 当日 → 3.0
        "2025-07-01",   # 新しい → 3.0
        "2025-12-31",   # 新しい → 3.0
    ]))
    w = build_sample_weight(
        dates, pd.Timestamp("2025-12-31"),
        {"mode": "recency", "recency_months": 6, "recency_weight": 3.0},
    )
    assert w is not None
    assert w.shape == (6,)
    np.testing.assert_allclose(w, [1.0, 1.0, 1.0, 3.0, 3.0, 3.0])


def test_sample_weight_recency_defaults():
    """省略時の既定値 (recency_months=12, recency_weight=3.0) で動作すること。"""
    dates = pd.Series(pd.to_datetime([
        "2024-12-30",   # 1.0（12ヶ月境界直前）
        "2024-12-31",   # 3.0（cutoff 当日）
        "2025-06-01",   # 3.0
    ]))
    w = build_sample_weight(
        dates, pd.Timestamp("2025-12-31"),
        {"mode": "recency"},
    )
    np.testing.assert_allclose(w, [1.0, 3.0, 3.0])


def test_sample_weight_exp_decay_monotonic():
    dates = pd.Series(pd.to_datetime([
        "2025-12-31",  # age=0 → 1.0
        "2025-06-30",  # age~6mo
        "2024-12-31",  # age~12mo
        "2023-12-31",  # age~24mo
    ]))
    w = build_sample_weight(
        dates, pd.Timestamp("2025-12-31"),
        {"mode": "exp_decay", "decay_k": 0.1},
    )
    # 最新は 1.0 付近
    assert abs(w[0] - 1.0) < 1e-6
    # 単調非増加
    assert w[0] >= w[1] >= w[2] >= w[3]
    # 全て正
    assert (w > 0).all()


def test_sample_weight_unknown_mode_raises():
    dates = _dates_series("2024-01-01", 5)
    with pytest.raises(ValueError, match="Unknown sample_weight mode"):
        build_sample_weight(dates, pd.Timestamp("2025-12-31"), {"mode": "foo_bar"})


# ---------------------------------------------------------------------------
# build_features_from_history(return_dates=True)
# ---------------------------------------------------------------------------

from features.feature_builder import build_features_from_history, FEATURE_COLUMNS  # noqa: E402


def _make_history_df(n_races: int = 10, seed: int = 0) -> pd.DataFrame:
    """build_features_from_history に渡せる最小限の合成データフレーム。"""
    rng = np.random.default_rng(seed)
    rows = []
    base_date = pd.Timestamp("2025-01-01")
    for r in range(n_races):
        race_date = base_date + pd.Timedelta(days=r)
        race_id = f"2025010{r % 10}_01_{r:02d}"
        for b in range(1, 7):
            rows.append({
                "race_id": race_id,
                "race_date": race_date.date(),
                "race_no": 1,
                "stadium_id": 1,
                "boat_no": b,
                "racer_id": 1000 + b,
                "finish_position": b,  # 艇番=着順（合成）
                "exhibition_time": rng.uniform(6.5, 7.0),
                "motor_win_rate": rng.uniform(30, 50),
                "boat_win_rate": rng.uniform(30, 50),
                "win_rate": rng.uniform(4.0, 6.0),
                "racer_grade": rng.choice(["A1", "A2", "B1", "B2"]),
                "start_timing": rng.uniform(0.1, 0.3),
                "wind_direction": rng.integers(1, 17),
                "wind_speed": rng.uniform(0, 5),
            })
    return pd.DataFrame(rows)


def test_build_features_backward_compat_returns_two():
    df = _make_history_df()
    out = build_features_from_history(df)
    assert isinstance(out, tuple) and len(out) == 2
    X, y = out
    assert list(X.columns) == FEATURE_COLUMNS
    assert len(X) == len(y)


def test_build_features_return_dates_returns_three():
    df = _make_history_df()
    out = build_features_from_history(df, return_dates=True)
    assert isinstance(out, tuple) and len(out) == 3
    X, y, dates = out
    assert len(X) == len(y) == len(dates)
    # インデックスが一致
    assert X.index.equals(dates.index)
    # dtype が datetime
    assert pd.api.types.is_datetime64_any_dtype(dates)


# ---------------------------------------------------------------------------
# get_model_for_month: trial_config 伝搬
# ---------------------------------------------------------------------------

import run_walkforward  # noqa: E402


def _setup_get_model_mocks(monkeypatch, tmp_path, capture: dict):
    """
    get_model_for_month(retrain=True) の依存関係をモック:
      - load_history_range / load_program_range / merge_program_data
      - build_features_from_history
      - trainer.train: 呼び出し引数を capture dict に記録してダミー Path を返す
      - joblib.load: ダミーモデル（辞書）を返す
    """
    def fake_load_history(*a, **kw):
        # 1000 行以上必要（retrain の前提チェックを通す）
        # 日付は 2024-01-01 〜 2025-11 末をカバーするように分散させ、
        # recency cutoff（test_year=2025/12 → ref=2025-11-30 → 6mo前=2025-05-31）
        # の前後に十分な行数が存在する状態にする。
        return pd.DataFrame({
            "race_id": [f"r{i}" for i in range(2000)],
            "race_date": pd.date_range("2024-01-01", periods=2000, freq="12h"),
            "finish_position": [(i % 6) + 1 for i in range(2000)],
        })

    def fake_load_program(*a, **kw):
        return pd.DataFrame()

    def fake_merge(df_k, df_b):
        return df_k

    def fake_bffh(df, *, return_dates=False):
        n = len(df)
        X = pd.DataFrame(np.zeros((n, 12)), columns=[f"f{i}" for i in range(12)])
        y = pd.Series([(i % 6) for i in range(n)])
        if return_dates:
            dates = pd.Series(pd.to_datetime(df["race_date"]).values, index=X.index)
            return X, y, dates
        return X, y

    def fake_train(X, y, version, **kwargs):
        capture["kwargs"] = kwargs
        capture["version"] = version
        capture["n_samples"] = len(X)
        model_path = tmp_path / f"model_{version}.pkl"
        model_path.write_bytes(b"dummy")
        if kwargs.get("return_metrics"):
            return {
                "model_path": model_path,
                "metrics": {"ece_rank1_raw": 0.1, "ece_rank1_calibrated": 0.09,
                            "n_train": len(X) - 10, "n_val": 10},
                "best_iteration": 20,
                "params": {"num_leaves": (kwargs.get("lgb_params") or {}).get("num_leaves", 63)},
            }
        return model_path

    def fake_joblib_load(path):
        return {"booster": "dummy_booster", "softmax_calibrators": [None] * 6}

    monkeypatch.setattr(run_walkforward, "load_history_range", fake_load_history)
    monkeypatch.setattr(run_walkforward, "load_program_range", fake_load_program)
    monkeypatch.setattr(run_walkforward, "merge_program_data", fake_merge)
    monkeypatch.setattr(run_walkforward, "build_features_from_history", fake_bffh)
    monkeypatch.setattr(run_walkforward, "train", fake_train)
    monkeypatch.setattr(run_walkforward.joblib, "load", fake_joblib_load)


def test_get_model_for_month_trial_config_none(monkeypatch, tmp_path):
    """trial_config=None のとき、train() に既定値が渡る（後方互換）。"""
    capture = {}
    _setup_get_model_mocks(monkeypatch, tmp_path, capture)

    model = run_walkforward.get_model_for_month(
        test_year=2025, test_month=12,
        retrain=True,
        train_start_year=2023, train_start_month=1,
    )
    assert model is not None
    assert capture["kwargs"]["lgb_params"] is None
    assert capture["kwargs"]["num_boost_round"] == 1000
    assert capture["kwargs"]["early_stopping_rounds"] == 50
    assert capture["kwargs"]["sample_weight"] is None
    assert capture["kwargs"]["return_metrics"] is False


def test_get_model_for_month_lgb_params_passthrough(monkeypatch, tmp_path):
    """trial_config.lgb_params が train() に渡されること。"""
    capture = {}
    _setup_get_model_mocks(monkeypatch, tmp_path, capture)

    trial_config = {
        "lgb_params": {"num_leaves": 31, "learning_rate": 0.02},
        "training": {
            "num_boost_round": 500,
            "early_stopping_rounds": 30,
        },
    }
    run_walkforward.get_model_for_month(
        test_year=2025, test_month=12,
        retrain=True,
        train_start_year=2023, train_start_month=1,
        trial_config=trial_config,
    )
    assert capture["kwargs"]["lgb_params"] == {"num_leaves": 31, "learning_rate": 0.02}
    assert capture["kwargs"]["num_boost_round"] == 500
    assert capture["kwargs"]["early_stopping_rounds"] == 30
    assert capture["kwargs"]["sample_weight"] is None  # mode 未指定


def test_get_model_for_month_sample_weight_recency(monkeypatch, tmp_path):
    """sample_weight.mode=recency のとき、train() に配列が渡されること。"""
    capture = {}
    _setup_get_model_mocks(monkeypatch, tmp_path, capture)

    trial_config = {
        "training": {
            "sample_weight": {
                "mode": "recency",
                "recency_months": 6,
                "recency_weight": 2.5,
            },
        },
    }
    run_walkforward.get_model_for_month(
        test_year=2025, test_month=12,
        retrain=True,
        train_start_year=2023, train_start_month=1,
        trial_config=trial_config,
    )
    sw = capture["kwargs"]["sample_weight"]
    assert sw is not None
    assert isinstance(sw, np.ndarray)
    assert len(sw) == capture["n_samples"]
    # recency_weight=2.5 が最大値として現れること
    assert sw.max() == pytest.approx(2.5)
    assert sw.min() == pytest.approx(1.0)


def test_get_model_for_month_return_metrics(monkeypatch, tmp_path):
    """return_metrics=True のとき (model, metrics_dict) が返る。"""
    capture = {}
    _setup_get_model_mocks(monkeypatch, tmp_path, capture)

    model, metrics = run_walkforward.get_model_for_month(
        test_year=2025, test_month=12,
        retrain=True,
        train_start_year=2023, train_start_month=1,
        return_metrics=True,
    )
    assert model is not None
    assert isinstance(metrics, dict)
    assert "metrics" in metrics
    assert "ece_rank1_calibrated" in metrics["metrics"]
