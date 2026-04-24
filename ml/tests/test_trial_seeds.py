"""
trials/pending/ に配置された初期 trial seeds（MODEL_LOOP_PLAN タスク 4）の
YAML 妥当性を検証する。

検証項目:
  1. 期待される 8 本（T00〜T07）が全て揃っていること
  2. 各 YAML が load_trial_yaml を通過すること（スキーマ検証）
  3. trial_id がファイル名と一致すること
  4. strategy セクションが全 trial で統一されていること（比較可能性の保証）
  5. walkforward 期間が 2025-05〜2026-04 で統一されていること
  6. sample_weight.mode が正しい値（null / "recency"）を取ること

ネットワーク・DB 不要、重たい学習は走らない。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "ml" / "src"))
sys.path.insert(0, str(ROOT / "ml" / "src" / "scripts"))

from run_model_loop import load_trial_yaml  # noqa: E402

PENDING_DIR = ROOT / "trials" / "pending"

EXPECTED_TRIAL_IDS = [
    "T00_baseline",
    "T01_window_2024",
    "T02_window_2025",
    "T03_sample_weight_recency",
    "T04_lgbm_regularized",
    "T05_lgbm_conservative_lr",
    "T06_early_stop_tight",
    "T07_window_2024_plus_weight",
]

# MODEL_LOOP_PLAN §4 タスク 4: strategy セクションは全 trial で統一
EXPECTED_STRATEGY = {
    "prob_threshold": 0.07,
    "ev_threshold": 2.0,
    "min_odds": 100.0,
    "exclude_courses": [],
    "exclude_stadiums": [2, 3, 4, 9, 11, 14, 16, 17, 21, 23],
    "bet_amount": 100,
    "max_bets": 5,
    "bet_type": "trifecta",
}


def _seed_paths() -> list[Path]:
    return sorted(PENDING_DIR.glob("*.yaml"))


def test_all_expected_seeds_present():
    """期待される 8 本（T00〜T07）が trials/pending/ に全て揃っている。"""
    paths = _seed_paths()
    actual_ids = [p.stem for p in paths]
    for tid in EXPECTED_TRIAL_IDS:
        assert tid in actual_ids, f"trial seed '{tid}' が欠落: pending には {actual_ids}"


@pytest.mark.parametrize("trial_id", EXPECTED_TRIAL_IDS)
def test_seed_loads_and_validates(trial_id: str):
    """各 seed YAML が load_trial_yaml を通過する（必須キーが揃っている）。"""
    path = PENDING_DIR / f"{trial_id}.yaml"
    assert path.exists(), f"{path} が存在しません"
    data = load_trial_yaml(path)
    assert data["trial_id"] == trial_id, (
        f"trial_id がファイル名と不一致: file={trial_id} yaml={data['trial_id']}"
    )


@pytest.mark.parametrize("trial_id", EXPECTED_TRIAL_IDS)
def test_seed_strategy_is_unified(trial_id: str):
    """MODEL_LOOP_PLAN §4 タスク 4: strategy は全 trial で統一されている。"""
    path = PENDING_DIR / f"{trial_id}.yaml"
    data = load_trial_yaml(path)
    strat = data["strategy"]
    for key, expected in EXPECTED_STRATEGY.items():
        assert strat.get(key) == expected, (
            f"{trial_id}: strategy.{key}={strat.get(key)!r} が "
            f"期待値 {expected!r} と異なる（比較統一違反）"
        )


@pytest.mark.parametrize("trial_id", EXPECTED_TRIAL_IDS)
def test_seed_walkforward_period_unified(trial_id: str):
    """MODEL_LOOP_PLAN §1-3: Walk-Forward は 2025-05〜2026-04 統一。"""
    path = PENDING_DIR / f"{trial_id}.yaml"
    data = load_trial_yaml(path)
    wf = data["walkforward"]
    assert wf["start"] == "2025-05", f"{trial_id}: walkforward.start={wf['start']!r}"
    assert wf["end"] == "2026-04", f"{trial_id}: walkforward.end={wf['end']!r}"
    assert wf.get("retrain_interval") == 3, (
        f"{trial_id}: retrain_interval={wf.get('retrain_interval')!r} "
        "（MODEL_LOOP_PLAN §1-3 合意: 3 ヶ月ごと）"
    )
    assert wf.get("real_odds") is True, f"{trial_id}: real_odds は True 固定"


@pytest.mark.parametrize("trial_id", EXPECTED_TRIAL_IDS)
def test_seed_sample_weight_mode_valid(trial_id: str):
    """sample_weight.mode は null / "recency" / "exp_decay" のいずれか。"""
    path = PENDING_DIR / f"{trial_id}.yaml"
    data = load_trial_yaml(path)
    sw = (data.get("training") or {}).get("sample_weight") or {}
    mode = sw.get("mode")
    assert mode in (None, "recency", "exp_decay"), (
        f"{trial_id}: sample_weight.mode={mode!r} は不正値"
    )
    if mode == "recency":
        assert "recency_months" in sw, f"{trial_id}: recency_months が必要"
        assert "recency_weight" in sw, f"{trial_id}: recency_weight が必要"
        assert sw["recency_months"] > 0
        assert sw["recency_weight"] > 0


def test_t00_baseline_uses_defaults():
    """T00 は trainer.py 既定（train_start=2023/1、lgb_params 上書きなし）。"""
    data = load_trial_yaml(PENDING_DIR / "T00_baseline.yaml")
    training = data.get("training") or {}
    assert training.get("train_start_year") == 2023
    assert training.get("train_start_month") == 1
    assert (training.get("sample_weight") or {}).get("mode") is None
    assert "lgb_params" not in data or not data["lgb_params"], (
        "T00 は lgb_params 上書きなし（他 trial の比較基準）"
    )


def test_t01_window_2024_changes_only_start_year():
    """T01 は train_start_year のみ T00 から変更されている。"""
    data = load_trial_yaml(PENDING_DIR / "T01_window_2024.yaml")
    assert data["training"]["train_start_year"] == 2024
    assert data["training"]["train_start_month"] == 1


def test_t03_sample_weight_recency_shape():
    """T03 は recency_months=12 / recency_weight=3.0 で設計書と一致。"""
    data = load_trial_yaml(PENDING_DIR / "T03_sample_weight_recency.yaml")
    sw = data["training"]["sample_weight"]
    assert sw["mode"] == "recency"
    assert sw["recency_months"] == 12
    assert sw["recency_weight"] == 3.0


def test_t04_lgbm_regularized_params():
    """T04 は num_leaves=31 / min_child_samples=200 に絞っている。"""
    data = load_trial_yaml(PENDING_DIR / "T04_lgbm_regularized.yaml")
    lgb = data["lgb_params"]
    assert lgb["num_leaves"] == 31
    assert lgb["min_child_samples"] == 200


def test_t05_lgbm_conservative_lr_params():
    """T05 は lr=0.02 / num_boost_round=2000 を明示。"""
    data = load_trial_yaml(PENDING_DIR / "T05_lgbm_conservative_lr.yaml")
    assert data["lgb_params"]["learning_rate"] == 0.02
    assert data["training"]["num_boost_round"] == 2000


def test_t06_early_stop_tight_param():
    """T06 は early_stopping_rounds=30 を明示。"""
    data = load_trial_yaml(PENDING_DIR / "T06_early_stop_tight.yaml")
    assert data["training"]["early_stopping_rounds"] == 30


def test_t07_combo_window_and_weight():
    """T07 は T01 (window=2024) + recency (6ヶ月 × 2.0) の複合。"""
    data = load_trial_yaml(PENDING_DIR / "T07_window_2024_plus_weight.yaml")
    assert data["training"]["train_start_year"] == 2024
    sw = data["training"]["sample_weight"]
    assert sw["mode"] == "recency"
    assert sw["recency_months"] == 6
    assert sw["recency_weight"] == 2.0
