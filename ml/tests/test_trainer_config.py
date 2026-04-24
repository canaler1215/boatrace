"""
trainer.train() の config 対応テスト（MODEL_LOOP_PLAN タスク 1）

検証項目:
  1. 後方互換: train(X, y, version) が Path を返すこと
  2. return_metrics=True で dict（model_path/metrics/best_iteration/params）を返すこと
  3. lgb_params でパラメータ上書きが効くこと（num_leaves を変えて params に反映される）
  4. num_boost_round / early_stopping_rounds が指定通りに伝搬すること（best_iteration ≤ 指定値）
  5. sample_weight を渡しても例外なく完走し、長さ不一致で ValueError を出すこと
  6. 保存形式 {"booster": ..., "softmax_calibrators": [...]} が維持されること

合成データで 12 次元 × 数千件 / num_class=6 / num_boost_round 少なめ（~30）で高速化。
LightGBM・scikit-learn・numpy・pandas が必要（ml/requirements.txt 準拠）。
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ml/src を import path に入れる
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from model import trainer  # noqa: E402
from model.trainer import train, LGB_PARAMS  # noqa: E402


# 12 次元特徴量（feature_builder と同じ列名は不要、本テストでは形だけ合わせる）
FEATURE_COLS = [f"f{i}" for i in range(12)]
N_CLASSES = 6


def _make_synthetic_data(n_races: int = 800, seed: int = 42):
    """1 レース = 6 行（各艇）、6艇のうち着順 0〜5 を1つずつ割り当てる合成データ。"""
    rng = np.random.default_rng(seed)
    n = n_races * N_CLASSES
    X = pd.DataFrame(rng.normal(size=(n, 12)), columns=FEATURE_COLS)
    # 各レースで 0..5 をシャッフルしたラベル
    y_list = []
    for _ in range(n_races):
        perm = rng.permutation(N_CLASSES)
        y_list.extend(perm.tolist())
    y = pd.Series(y_list, dtype=int)
    return X, y


@pytest.fixture(scope="module")
def synthetic_xy():
    return _make_synthetic_data()


@pytest.fixture(autouse=True)
def _redirect_model_dir(monkeypatch, tmp_path):
    """MODEL_DIR を tmp に差し替えて、テスト成果物がリポジトリに残らないようにする。"""
    monkeypatch.setattr(trainer, "MODEL_DIR", tmp_path)
    yield


def test_backward_compat_returns_path(synthetic_xy):
    """旧 API: train(X, y, version) が Path を返す（後方互換）。"""
    X, y = synthetic_xy
    out = train(X, y, "test_compat",
                num_boost_round=20, early_stopping_rounds=10)
    assert isinstance(out, Path), f"expected Path, got {type(out)}"
    assert out.exists(), "model file not saved"


def test_return_metrics_dict(synthetic_xy):
    """return_metrics=True で dict を返す。"""
    X, y = synthetic_xy
    result = train(X, y, "test_metrics",
                   num_boost_round=20, early_stopping_rounds=10,
                   return_metrics=True)
    assert isinstance(result, dict)
    assert "model_path" in result and isinstance(result["model_path"], Path)
    assert result["model_path"].exists()
    assert "metrics" in result and isinstance(result["metrics"], dict)
    assert "ece_rank1_raw" in result["metrics"]
    assert "ece_rank1_calibrated" in result["metrics"]
    assert "n_train" in result["metrics"]
    assert "n_val" in result["metrics"]
    assert "best_iteration" in result
    assert isinstance(result["best_iteration"], int)
    assert "params" in result and isinstance(result["params"], dict)


def test_lgb_params_override(synthetic_xy):
    """lgb_params で上書きが効き、戻り値 params に反映される。"""
    X, y = synthetic_xy
    override = {"num_leaves": 15, "learning_rate": 0.1, "min_child_samples": 30}
    result = train(X, y, "test_override",
                   lgb_params=override,
                   num_boost_round=15, early_stopping_rounds=5,
                   return_metrics=True)
    assert result["params"]["num_leaves"] == 15
    assert result["params"]["learning_rate"] == 0.1
    assert result["params"]["min_child_samples"] == 30
    # ベース値は保持されている
    assert result["params"]["objective"] == "multiclass"
    assert result["params"]["num_class"] == 6
    # 元の LGB_PARAMS が副作用で変更されていないこと
    assert LGB_PARAMS["num_leaves"] == 63
    assert LGB_PARAMS["learning_rate"] == 0.05


def test_num_boost_round_respected(synthetic_xy):
    """num_boost_round 上限が守られる（best_iteration は指定値以下）。"""
    X, y = synthetic_xy
    result = train(X, y, "test_round_limit",
                   num_boost_round=10, early_stopping_rounds=5,
                   return_metrics=True)
    assert 0 <= result["best_iteration"] <= 10


def test_sample_weight_accepted(synthetic_xy):
    """sample_weight を渡しても完走し、モデルが保存される。"""
    X, y = synthetic_xy
    n = len(X)
    # 後半サンプルを 2 倍重みに
    w = np.ones(n)
    w[n // 2:] = 2.0
    result = train(X, y, "test_weight",
                   sample_weight=w,
                   num_boost_round=20, early_stopping_rounds=10,
                   return_metrics=True)
    assert result["model_path"].exists()


def test_sample_weight_length_mismatch_raises(synthetic_xy):
    """sample_weight の長さが X と合わないと ValueError。"""
    X, y = synthetic_xy
    wrong_w = np.ones(len(X) - 5)
    with pytest.raises(ValueError, match="sample_weight length"):
        train(X, y, "test_weight_err",
              sample_weight=wrong_w,
              num_boost_round=10, early_stopping_rounds=5)


def test_saved_model_schema(synthetic_xy, tmp_path):
    """保存形式 {"booster": ..., "softmax_calibrators": [...]} を維持。"""
    import joblib
    X, y = synthetic_xy
    path = train(X, y, "test_schema",
                 num_boost_round=15, early_stopping_rounds=5)
    pkg = joblib.load(path)
    assert isinstance(pkg, dict)
    assert "booster" in pkg
    assert "softmax_calibrators" in pkg
    assert len(pkg["softmax_calibrators"]) == N_CLASSES
