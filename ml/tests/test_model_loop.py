"""
run_model_loop.py のテスト（MODEL_LOOP_PLAN タスク 3）

検証項目:
  A. スキーマ検証
     1. 必須キー欠落で ValueError
     2. walkforward/strategy が mapping でない場合 ValueError
     3. 正しい YAML は validate を通る
  B. KPI 計算
     4. 合成 DataFrame → ROI / 月次 ROI / plus_month_ratio / avg_hit_odds が正しい
     5. wagered=0 / 空 DataFrame でも落ちない
  C. primary_score / classify_verdict（MODEL_LOOP_PLAN §3-4, §3-5）
     6. worst >= -50 → ペナルティなし
     7. worst < -50 → (|worst| - 50) * 2 のペナルティ
     8. classify_verdict: pass / marginal / fail の境界
  D. discover_pending_trials
     9. 指定 trial_id が見つからなければ FileNotFoundError
     10. glob で yaml を列挙できる（.yaml / .yml 両対応）
  E. execute_trial_file（run_trial_walkforward をモック）
     11. 成功時: pending → completed に移動、results.jsonl に 1 行追記
     12. 失敗時: YAML は pending に残り、results.jsonl に status=error、error.log が作成される

ネットワーク・DB 不要。合成データ / モックで完結。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "scripts"))

import run_model_loop as rml  # noqa: E402
from run_model_loop import (  # noqa: E402
    classify_verdict,
    compute_kpi,
    discover_pending_trials,
    primary_score,
    validate_trial_schema,
)


# ---------------------------------------------------------------------------
# A. スキーマ検証
# ---------------------------------------------------------------------------

_VALID_TRIAL = {
    "trial_id": "T01",
    "walkforward": {"start": "2025-05", "end": "2026-04"},
    "strategy": {
        "prob_threshold": 0.07,
        "ev_threshold": 2.0,
        "bet_amount": 100,
    },
}


def test_validate_ok():
    validate_trial_schema(dict(_VALID_TRIAL))


def test_validate_missing_top_key():
    data = dict(_VALID_TRIAL)
    del data["walkforward"]
    with pytest.raises(ValueError, match="walkforward"):
        validate_trial_schema(data)


def test_validate_missing_walkforward_key():
    data = {**_VALID_TRIAL, "walkforward": {"start": "2025-05"}}
    with pytest.raises(ValueError, match="walkforward.end"):
        validate_trial_schema(data)


def test_validate_missing_strategy_key():
    data = {
        **_VALID_TRIAL,
        "strategy": {"prob_threshold": 0.07, "ev_threshold": 2.0},
    }
    with pytest.raises(ValueError, match="strategy.bet_amount"):
        validate_trial_schema(data)


def test_validate_walkforward_not_mapping():
    data = {**_VALID_TRIAL, "walkforward": ["2025-05", "2026-04"]}
    with pytest.raises(ValueError, match="mapping"):
        validate_trial_schema(data)


# ---------------------------------------------------------------------------
# B. KPI 計算
# ---------------------------------------------------------------------------

def _build_results_df(rows: list[dict]) -> pd.DataFrame:
    """
    rows の各要素は {race_date, bets_placed, amount_wagered, payout_received,
                    matched, matched_odds} を含む dict
    """
    return pd.DataFrame(rows)


def test_compute_kpi_basic():
    # 2 ヶ月: 5月 +50%、6月 -60%（通算 wagered=200, payout=140 → -30%）
    # 5月: wagered=100, payout=150, wins=1, matched_odds=150, hit rate 1/2
    # 6月: wagered=100, payout=40,  wins=1, matched_odds=40,  hit rate 1/2
    rows = [
        # 5月 (2 bets, 1 hit)
        {"race_date": "2025-05-10", "bets_placed": 1, "amount_wagered": 50,
         "payout_received": 0, "matched": False, "matched_odds": 0.0},
        {"race_date": "2025-05-20", "bets_placed": 1, "amount_wagered": 50,
         "payout_received": 150, "matched": True, "matched_odds": 150.0},
        # 6月 (2 bets, 1 hit, 低配当)
        {"race_date": "2025-06-05", "bets_placed": 1, "amount_wagered": 50,
         "payout_received": 0, "matched": False, "matched_odds": 0.0},
        {"race_date": "2025-06-15", "bets_placed": 1, "amount_wagered": 50,
         "payout_received": 40, "matched": True, "matched_odds": 40.0},
    ]
    df = _build_results_df(rows)
    monthly_rows = [
        {"month": "2025-05", "wagered": 100, "payout": 150, "n_bets": 2, "wins": 1},
        {"month": "2025-06", "wagered": 100, "payout": 40, "n_bets": 2, "wins": 1},
    ]

    kpi = compute_kpi(df, monthly_rows)
    assert kpi["total_bets"] == 4
    assert kpi["total_wagered"] == 200.0
    assert kpi["total_payout"] == 190.0
    assert kpi["wins"] == 2
    assert kpi["roi_total"] == pytest.approx(-5.0)  # 190/200 - 1 = -5%
    assert kpi["worst_month_roi"] == pytest.approx(-60.0)
    assert kpi["best_month_roi"] == pytest.approx(50.0)
    assert kpi["plus_months"] == 1
    assert kpi["total_months"] == 2
    assert kpi["plus_month_ratio"] == pytest.approx(0.5)
    # avg_hit_odds は matched=True の matched_odds の平均 = (150+40)/2 = 95
    assert kpi["avg_hit_odds"] == pytest.approx(95.0)
    assert kpi["hit_rate_per_bet"] == pytest.approx(2 / 4)


def test_compute_kpi_empty():
    df = pd.DataFrame(columns=[
        "race_date", "bets_placed", "amount_wagered", "payout_received",
        "matched", "matched_odds",
    ])
    kpi = compute_kpi(df, [])
    assert kpi["total_bets"] == 0
    assert kpi["total_wagered"] == 0.0
    assert kpi["roi_total"] == 0.0
    assert kpi["total_months"] == 0
    assert kpi["plus_month_ratio"] == 0.0


def test_compute_kpi_wagered_zero_month():
    """ある月の wagered=0 でも落ちない（ROI=0 扱い）。"""
    rows = [
        {"race_date": "2025-05-10", "bets_placed": 0, "amount_wagered": 0,
         "payout_received": 0, "matched": False, "matched_odds": 0.0},
    ]
    df = _build_results_df(rows)
    monthly_rows = [
        {"month": "2025-05", "wagered": 0, "payout": 0, "n_bets": 0, "wins": 0},
    ]
    kpi = compute_kpi(df, monthly_rows)
    assert kpi["worst_month_roi"] == 0.0
    assert kpi["roi_total"] == 0.0


# ---------------------------------------------------------------------------
# C. primary_score / classify_verdict
# ---------------------------------------------------------------------------

def test_primary_score_no_penalty():
    # worst = -40 → ペナルティ 0（|worst| <= 50）
    kpi = {"roi_total": 20.0, "worst_month_roi": -40.0}
    assert primary_score(kpi) == pytest.approx(20.0)


def test_primary_score_boundary_minus_50():
    # worst = -50 → ペナルティ 0（等号なのでちょうど境界）
    kpi = {"roi_total": 10.0, "worst_month_roi": -50.0}
    assert primary_score(kpi) == pytest.approx(10.0)


def test_primary_score_with_penalty():
    # worst = -79.5 → penalty = 2 * (79.5 - 50) = 59.0
    # score = 11.2 - 59.0 = -47.8
    kpi = {"roi_total": 11.2, "worst_month_roi": -79.5}
    assert primary_score(kpi) == pytest.approx(-47.8)


def test_classify_verdict_pass():
    kpi = {"roi_total": 15.0, "worst_month_roi": -30.0, "plus_month_ratio": 0.7}
    assert classify_verdict(kpi) == "pass"


def test_classify_verdict_pass_boundary():
    # 境界値（ちょうど満たす）: ROI=0 / worst=-50 / plus_ratio=0.60
    kpi = {"roi_total": 0.0, "worst_month_roi": -50.0, "plus_month_ratio": 0.60}
    assert classify_verdict(kpi) == "pass"


def test_classify_verdict_marginal_worst_too_low():
    # ROI >= 0 だが worst < -50 → marginal
    kpi = {"roi_total": 5.0, "worst_month_roi": -70.0, "plus_month_ratio": 0.7}
    assert classify_verdict(kpi) == "marginal"


def test_classify_verdict_marginal_plus_ratio_low():
    kpi = {"roi_total": 10.0, "worst_month_roi": -30.0, "plus_month_ratio": 0.4}
    assert classify_verdict(kpi) == "marginal"


def test_classify_verdict_fail():
    kpi = {"roi_total": -20.0, "worst_month_roi": -80.0, "plus_month_ratio": 0.3}
    assert classify_verdict(kpi) == "fail"


# ---------------------------------------------------------------------------
# D. discover_pending_trials
# ---------------------------------------------------------------------------

def test_discover_specific_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(rml, "TRIALS_DIR", tmp_path)
    monkeypatch.setattr(rml, "PENDING_DIR", tmp_path / "pending")
    with pytest.raises(FileNotFoundError, match="NOPE"):
        discover_pending_trials("NOPE")


def test_discover_glob_yaml_and_yml(tmp_path, monkeypatch):
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "T01.yaml").write_text("trial_id: T01\n", encoding="utf-8")
    (pending / "T02.yml").write_text("trial_id: T02\n", encoding="utf-8")
    (pending / ".gitkeep").write_text("", encoding="utf-8")  # 無視される

    monkeypatch.setattr(rml, "TRIALS_DIR", tmp_path)
    monkeypatch.setattr(rml, "PENDING_DIR", pending)

    found = discover_pending_trials(None)
    names = [p.name for p in found]
    assert set(names) == {"T01.yaml", "T02.yml"}


def test_discover_specific_matches_exact(tmp_path, monkeypatch):
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "T01_window_2024.yaml").write_text("trial_id: T01\n", encoding="utf-8")
    (pending / "T02.yaml").write_text("trial_id: T02\n", encoding="utf-8")

    monkeypatch.setattr(rml, "TRIALS_DIR", tmp_path)
    monkeypatch.setattr(rml, "PENDING_DIR", pending)

    found = discover_pending_trials("T01_window_2024")
    assert len(found) == 1
    assert found[0].name == "T01_window_2024.yaml"


# ---------------------------------------------------------------------------
# E. execute_trial_file（run_trial_walkforward をモック）
# ---------------------------------------------------------------------------

def _write_trial_yaml(path: Path, trial_id: str) -> None:
    data = {
        "trial_id": trial_id,
        "description": f"desc of {trial_id}",
        "walkforward": {"start": "2025-05", "end": "2025-06"},
        "strategy": {
            "prob_threshold": 0.07,
            "ev_threshold": 2.0,
            "bet_amount": 100,
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def _setup_dirs(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, Path]:
    """trials ディレクトリ群を tmp_path 下に差し替え、artifacts も差し替える。"""
    trials = tmp_path / "trials"
    pending = trials / "pending"
    completed = trials / "completed"
    artifacts = tmp_path / "artifacts"
    pending.mkdir(parents=True)
    completed.mkdir(parents=True)
    artifacts.mkdir(parents=True)

    monkeypatch.setattr(rml, "TRIALS_DIR", trials)
    monkeypatch.setattr(rml, "PENDING_DIR", pending)
    monkeypatch.setattr(rml, "COMPLETED_DIR", completed)
    monkeypatch.setattr(rml, "RESULTS_FILE", trials / "results.jsonl")
    monkeypatch.setattr(rml, "ARTIFACTS_DIR", artifacts)
    return trials, pending, completed, artifacts


def test_execute_trial_success(tmp_path, monkeypatch):
    trials, pending, completed, artifacts = _setup_dirs(tmp_path, monkeypatch)
    yaml_path = pending / "T01_test.yaml"
    _write_trial_yaml(yaml_path, "T01_test")

    # run_trial_walkforward をモック
    dummy_csv = artifacts / "walkforward_T01_test.csv"
    dummy_csv.write_text("stub,csv\n", encoding="utf-8")
    fake_run_result = rml.TrialRunResult(
        kpi={
            "total_bets": 1000,
            "total_wagered": 100000.0,
            "total_payout": 115000.0,
            "wins": 5,
            "roi_total": 15.0,
            "worst_month_roi": -40.0,
            "best_month_roi": 60.0,
            "plus_months": 2,
            "total_months": 2,
            "plus_month_ratio": 1.0,
            "avg_hit_odds": 300.0,
            "hit_rate_per_bet": 0.005,
        },
        monthly_roi={"2025-05": 60.0, "2025-06": -40.0},
        model_metrics={"metrics": {"ece_rank1_calibrated": 0.1337}},
        csv_path=dummy_csv,
    )
    monkeypatch.setattr(rml, "run_trial_walkforward",
                        lambda trial, trial_id: fake_run_result)

    record = rml.execute_trial_file(yaml_path)

    # YAML が completed に移動されていること
    assert not yaml_path.exists()
    assert (completed / "T01_test.yaml").exists()

    # results.jsonl に 1 行追記されている
    lines = (trials / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["trial_id"] == "T01_test"
    assert rec["status"] == "success"
    assert rec["kpi"]["roi_total"] == 15.0
    assert rec["kpi"]["ece_rank1_calibrated"] == pytest.approx(0.1337)
    assert rec["primary_score"] == pytest.approx(15.0)  # worst=-40 → no penalty
    # plus_ratio=1.0, worst=-40, roi=15 → pass
    assert rec["verdict"] == "pass"
    assert "duration_sec" in rec
    assert rec["description"] == "desc of T01_test"

    # summary JSON も作成される
    summary_path = artifacts / "walkforward_T01_test_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["trial_id"] == "T01_test"
    assert summary["verdict"] == "pass"


def test_execute_trial_failure(tmp_path, monkeypatch):
    trials, pending, completed, artifacts = _setup_dirs(tmp_path, monkeypatch)
    yaml_path = pending / "T02_boom.yaml"
    _write_trial_yaml(yaml_path, "T02_boom")

    def fake_run(trial, trial_id):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(rml, "run_trial_walkforward", fake_run)

    record = rml.execute_trial_file(yaml_path)

    # YAML は pending に残る
    assert yaml_path.exists()
    assert not (completed / "T02_boom.yaml").exists()

    # results.jsonl に status=error
    lines = (trials / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["trial_id"] == "T02_boom"
    assert rec["status"] == "error"
    assert rec["error_type"] == "RuntimeError"
    assert "synthetic failure" in rec["error_message"]

    # エラーログ作成
    log_path = artifacts / "model_loop_T02_boom_error.log"
    assert log_path.exists()
    log_content = log_path.read_text(encoding="utf-8")
    assert "synthetic failure" in log_content
    assert "Traceback" in log_content


def test_execute_trial_invalid_yaml(tmp_path, monkeypatch):
    """必須キー欠落 YAML → 失敗扱いで pending に残る。"""
    trials, pending, completed, artifacts = _setup_dirs(tmp_path, monkeypatch)
    yaml_path = pending / "T03_bad.yaml"
    yaml_path.write_text("trial_id: T03_bad\nno_walkforward: here\n", encoding="utf-8")

    # run_trial_walkforward までは到達しないはず
    monkeypatch.setattr(rml, "run_trial_walkforward",
                        lambda trial, trial_id: pytest.fail("should not be called"))

    record = rml.execute_trial_file(yaml_path)

    assert record["status"] == "error"
    assert record["error_type"] == "ValueError"
    assert yaml_path.exists()
