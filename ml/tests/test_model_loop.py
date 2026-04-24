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
    block_bootstrap_roi_ci,
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
    # broken_months: -50 を下回る月（6月の -60%）= 1
    assert kpi["broken_months"] == 1
    # cvar20: 2 月のうち下位 ceil(0.2*2)=1 月平均 = 最悪月 = -60
    assert kpi["cvar20_month_roi"] == pytest.approx(-60.0)


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
# C. primary_score / classify_verdict（2026-04-24 改訂）
#    新定義: primary_score = roi_total + 0.5 * cvar20 - 10 * broken_months
#    pass: roi≥+10 AND broken_months==0 AND plus_ratio≥0.60 AND roi_ci_low_90≥0
# ---------------------------------------------------------------------------

def test_primary_score_no_broken_no_tail_loss():
    # cvar20 正（プラス月のみ）、broken=0 → ペナルティなし
    kpi = {"roi_total": 20.0, "cvar20_month_roi": 5.0, "broken_months": 0}
    # 20 + 0.5*5 - 0 = 22.5
    assert primary_score(kpi) == pytest.approx(22.5)


def test_primary_score_cvar_negative_no_broken():
    # 裾は負だが -50 超過なし → CVaR 分だけ減点
    kpi = {"roi_total": 15.0, "cvar20_month_roi": -30.0, "broken_months": 0}
    # 15 + 0.5*(-30) - 0 = 0.0
    assert primary_score(kpi) == pytest.approx(0.0)


def test_primary_score_one_broken_month():
    # 破局月 1 件 → -10 の離散ペナルティ
    kpi = {"roi_total": 11.2, "cvar20_month_roi": -79.5, "broken_months": 1}
    # 11.2 + 0.5*(-79.5) - 10 = 11.2 - 39.75 - 10 = -38.55
    assert primary_score(kpi) == pytest.approx(-38.55)


def test_primary_score_multiple_broken_months():
    # 破局月 3 件 → -30
    kpi = {"roi_total": -13.4, "cvar20_month_roi": -72.4, "broken_months": 3}
    # -13.4 + 0.5*(-72.4) - 30 = -13.4 - 36.2 - 30 = -79.6
    assert primary_score(kpi) == pytest.approx(-79.6)


def test_primary_score_backward_compat_missing_fields():
    # 旧 KPI（broken_months / cvar20_month_roi なし）でも落ちない
    kpi = {"roi_total": 20.0, "worst_month_roi": -40.0}
    # cvar20=0, broken=0 → 20.0
    assert primary_score(kpi) == pytest.approx(20.0)


def test_classify_verdict_pass_all_conditions():
    # 全条件クリア
    kpi = {
        "roi_total": 15.0,
        "plus_month_ratio": 0.7,
        "broken_months": 0,
        "roi_ci_low_90": 2.0,
    }
    assert classify_verdict(kpi) == "pass"


def test_classify_verdict_pass_boundary():
    # 境界値: roi=+10, broken=0, plus_ratio=0.60, ci_low=0
    kpi = {
        "roi_total": 10.0,
        "plus_month_ratio": 0.60,
        "broken_months": 0,
        "roi_ci_low_90": 0.0,
    }
    assert classify_verdict(kpi) == "pass"


def test_classify_verdict_marginal_roi_below_10():
    # ROI が +10 に届かない → pass ではなく marginal
    kpi = {
        "roi_total": 5.0,
        "plus_month_ratio": 0.8,
        "broken_months": 0,
        "roi_ci_low_90": 1.0,
    }
    assert classify_verdict(kpi) == "marginal"


def test_classify_verdict_marginal_broken_month():
    # broken_months >= 1 → pass 失格
    kpi = {
        "roi_total": 15.0,
        "plus_month_ratio": 0.7,
        "broken_months": 1,
        "roi_ci_low_90": 5.0,
    }
    assert classify_verdict(kpi) == "marginal"


def test_classify_verdict_marginal_ci_low_negative():
    # roi_ci_low_90 < 0 → pass 失格（偶発採択ガード）
    kpi = {
        "roi_total": 15.0,
        "plus_month_ratio": 0.7,
        "broken_months": 0,
        "roi_ci_low_90": -3.0,
    }
    assert classify_verdict(kpi) == "marginal"


def test_classify_verdict_marginal_plus_ratio_low():
    kpi = {
        "roi_total": 15.0,
        "plus_month_ratio": 0.4,
        "broken_months": 0,
        "roi_ci_low_90": 5.0,
    }
    assert classify_verdict(kpi) == "marginal"


def test_classify_verdict_fail():
    kpi = {
        "roi_total": -20.0,
        "plus_month_ratio": 0.3,
        "broken_months": 3,
        "roi_ci_low_90": -40.0,
    }
    assert classify_verdict(kpi) == "fail"


def test_classify_verdict_ci_missing_is_skipped():
    # 旧 KPI（roi_ci_low_90 なし）でも pass 判定は可能（互換）
    kpi = {
        "roi_total": 15.0,
        "plus_month_ratio": 0.7,
        "broken_months": 0,
    }
    assert classify_verdict(kpi) == "pass"


def test_classify_verdict_broken_derived_from_worst():
    # broken_months が無いが worst_month_roi はある → worst < -50 なら 1 扱い
    kpi = {
        "roi_total": 15.0,
        "plus_month_ratio": 0.7,
        "worst_month_roi": -70.0,
        "roi_ci_low_90": 5.0,
    }
    assert classify_verdict(kpi) == "marginal"


# ---------------------------------------------------------------------------
# C-bis. block_bootstrap_roi_ci
# ---------------------------------------------------------------------------

def test_bootstrap_empty_rows():
    ci = block_bootstrap_roi_ci([])
    assert ci["roi_ci_low"] == 0.0
    assert ci["roi_ci_high"] == 0.0
    assert ci["n_resamples"] == 0


def test_bootstrap_deterministic_with_seed():
    # seed 固定なら同じ結果
    rows = [
        {"month": "2025-05", "wagered": 1000.0, "payout": 1100.0},
        {"month": "2025-06", "wagered": 1000.0, "payout": 900.0},
        {"month": "2025-07", "wagered": 1000.0, "payout": 1200.0},
        {"month": "2025-08", "wagered": 1000.0, "payout": 800.0},
    ]
    ci1 = block_bootstrap_roi_ci(rows, seed=42, n_resamples=500)
    ci2 = block_bootstrap_roi_ci(rows, seed=42, n_resamples=500)
    assert ci1 == ci2


def test_bootstrap_ci_brackets_roughly_mean():
    # 全月プラス → CI 下限が正 / 下限 < 上限
    rows = [
        {"month": f"2025-{m:02d}", "wagered": 1000.0, "payout": 1200.0}
        for m in range(1, 13)
    ]
    ci = block_bootstrap_roi_ci(rows, seed=0, n_resamples=500)
    # 毎月 ROI = +20% なので CI は +20% 付近に収束
    assert 15.0 <= ci["roi_ci_low"] <= 25.0
    assert 15.0 <= ci["roi_ci_high"] <= 25.0
    assert ci["roi_ci_low"] <= ci["roi_ci_high"]


def test_bootstrap_negative_tail_gives_negative_lower_bound():
    # 破局月を含む系列 → CI 下限が 0 を下回ることを期待
    rows = [
        {"month": "2025-05", "wagered": 1000.0, "payout": 1100.0},  # +10%
        {"month": "2025-06", "wagered": 1000.0, "payout": 1050.0},  # +5%
        {"month": "2025-07", "wagered": 1000.0, "payout": 300.0},   # -70%
        {"month": "2025-08", "wagered": 1000.0, "payout": 1050.0},  # +5%
        {"month": "2025-09", "wagered": 1000.0, "payout": 1050.0},  # +5%
        {"month": "2025-10", "wagered": 1000.0, "payout": 250.0},   # -75%
    ]
    ci = block_bootstrap_roi_ci(rows, seed=0, n_resamples=1000, block_length=3)
    assert ci["roi_ci_low"] < 0.0
    assert ci["roi_ci_high"] > ci["roi_ci_low"]


def test_bootstrap_block_length_auto_shrink():
    # 月数 1、block_length=3 指定でも落ちない
    rows = [{"month": "2025-05", "wagered": 1000.0, "payout": 1200.0}]
    ci = block_bootstrap_roi_ci(rows, block_length=3, n_resamples=100, seed=0)
    assert ci["block_length"] == 1  # auto-shrunk
    assert ci["roi_ci_low"] == pytest.approx(20.0)
    assert ci["roi_ci_high"] == pytest.approx(20.0)


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
            "broken_months": 0,
            "cvar20_month_roi": -40.0,
            "avg_hit_odds": 300.0,
            "hit_rate_per_bet": 0.005,
        },
        monthly_roi={"2025-05": 60.0, "2025-06": -40.0},
        monthly_rows=[
            {"month": "2025-05", "wagered": 50000.0, "payout": 80000.0,
             "n_bets": 500, "wins": 3},
            {"month": "2025-06", "wagered": 50000.0, "payout": 35000.0,
             "n_bets": 500, "wins": 2},
        ],
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
    # bootstrap CI が KPI に注入されている
    assert "roi_ci_low_90" in rec["kpi"]
    assert "roi_ci_high_90" in rec["kpi"]
    # primary_score 新定義: 15 + 0.5*(-40) - 10*0 = -5.0
    assert rec["primary_score"] == pytest.approx(-5.0)
    # 新 pass 条件: roi=15 ≥ +10, broken=0, plus_ratio=1.0, ci_low ≥ 0 のはず
    # （2 月とも wagered=50000 でうち1月は +60% あるため CI 下限は正になりうる）
    # ここでは verdict が pass または marginal のいずれかであることを確認
    assert rec["verdict"] in ("pass", "marginal")
    assert "duration_sec" in rec
    assert rec["description"] == "desc of T01_test"

    # summary JSON も作成される
    summary_path = artifacts / "walkforward_T01_test_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["trial_id"] == "T01_test"
    assert summary["verdict"] == rec["verdict"]


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


# ---------------------------------------------------------------------------
# F. _copy_trial_model（trial 固有モデルの永続コピー）
# ---------------------------------------------------------------------------

def test_copy_trial_model_success(tmp_path, monkeypatch):
    """retrain 直後の model_path が trial_id 付きでコピーされる。"""
    monkeypatch.setattr(rml, "ARTIFACTS_DIR", tmp_path)

    src = tmp_path / "model_202504_from202301_wf.pkl"
    src.write_bytes(b"dummy-pickle-bytes")

    dst = rml._copy_trial_model(
        {"model_path": src, "metrics": {}},
        trial_id="T00_baseline",
        test_year=2025,
        test_month=5,
    )

    assert dst is not None
    assert dst == tmp_path / "model_loop_T00_baseline_202505.pkl"
    assert dst.exists()
    assert dst.read_bytes() == b"dummy-pickle-bytes"
    # 元ファイルは残っている（shutil.copy2 なので移動ではない）
    assert src.exists()


def test_copy_trial_model_overwrites_previous_trial(tmp_path, monkeypatch):
    """
    同じ train_start を使う別 trial 実行時、共有 src を別 trial の学習結果に
    上書きされても、前 trial の trial_id 付きコピーは残り続けることを確認。
    """
    monkeypatch.setattr(rml, "ARTIFACTS_DIR", tmp_path)
    src = tmp_path / "model_202504_from202301_wf.pkl"

    # T00 の retrain 結果
    src.write_bytes(b"T00-content")
    rml._copy_trial_model(
        {"model_path": src}, "T00_baseline", 2025, 5,
    )
    # T04（同じ train_start=2023/1、別ハイパラ）の retrain で src が上書きされる想定
    src.write_bytes(b"T04-content")
    rml._copy_trial_model(
        {"model_path": src}, "T04_lgbm_regularized", 2025, 5,
    )

    t00 = tmp_path / "model_loop_T00_baseline_202505.pkl"
    t04 = tmp_path / "model_loop_T04_lgbm_regularized_202505.pkl"
    assert t00.read_bytes() == b"T00-content"
    assert t04.read_bytes() == b"T04-content"


def test_copy_trial_model_missing_path_returns_none(tmp_path, monkeypatch, caplog):
    """model_path が存在しないファイルなら警告ログ + None を返し、例外を出さない。"""
    monkeypatch.setattr(rml, "ARTIFACTS_DIR", tmp_path)
    missing = tmp_path / "does_not_exist.pkl"

    with caplog.at_level("WARNING"):
        result = rml._copy_trial_model(
            {"model_path": missing}, "T00_baseline", 2025, 5,
        )

    assert result is None
    assert any("trial コピーをスキップ" in r.message for r in caplog.records)


def test_copy_trial_model_non_dict_returns_none(tmp_path, monkeypatch):
    """train_result が dict でない（後方互換の Path 返却など）の場合は None。"""
    monkeypatch.setattr(rml, "ARTIFACTS_DIR", tmp_path)
    assert rml._copy_trial_model(None, "T00", 2025, 5) is None
    assert rml._copy_trial_model(Path("x"), "T00", 2025, 5) is None


def test_copy_trial_model_dict_without_model_path_returns_none(tmp_path, monkeypatch):
    """dict だが model_path キーがない場合も None（例外は出さない）。"""
    monkeypatch.setattr(rml, "ARTIFACTS_DIR", tmp_path)
    assert rml._copy_trial_model({"metrics": {}}, "T00", 2025, 5) is None


def test_copy_trial_model_filename_format(tmp_path, monkeypatch):
    """命名規則: model_loop_<trial_id>_<YYYY><MM>.pkl（MM は 0 埋め 2 桁）。"""
    monkeypatch.setattr(rml, "ARTIFACTS_DIR", tmp_path)
    src = tmp_path / "model_x.pkl"
    src.write_bytes(b"x")

    dst = rml._copy_trial_model({"model_path": src}, "T01", 2026, 1)
    assert dst.name == "model_loop_T01_202601.pkl"

    dst2 = rml._copy_trial_model({"model_path": src}, "T07_window_2024_plus_weight", 2025, 12)
    assert dst2.name == "model_loop_T07_window_2024_plus_weight_202512.pkl"
