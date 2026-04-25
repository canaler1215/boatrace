"""
特徴量拡張 PoC ハーネス（タスク 6-10）

train: 2023-01 〜 (val_year, val_month) の前月
val  : (val_year, val_month) 単月
で LightGBM を学習し、val の top-1 accuracy / 1着 ECE / multi-logloss を出力する。

trainer.py の `_train_impl` 互換ロジックを使うが、val split は時系列末尾10%ではなく
「指定月をまるごと val」とする。ベースラインと特徴量追加版の比較を高速化する目的。

使い方:
  py -3.12 ml/src/scripts/run_feature_poc.py --val-year 2025 --val-month 12
  py -3.12 ml/src/scripts/run_feature_poc.py --val-year 2025 --val-month 12 --tag baseline
  py -3.12 ml/src/scripts/run_feature_poc.py --val-year 2025 --val-month 12 --tag c_st_var
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from collector.history_downloader import load_history_range  # noqa: E402
from collector.program_downloader import load_program_range, merge_program_data  # noqa: E402
from features.feature_builder import build_features_from_history, FEATURE_COLUMNS  # noqa: E402
from model.trainer import LGB_PARAMS, _softmax_normalize, _ece  # noqa: E402


def _multi_logloss(probs: np.ndarray, y: np.ndarray) -> float:
    eps = 1e-15
    p = np.clip(probs, eps, 1 - eps)
    return float(-np.log(p[np.arange(len(y)), y]).mean())


def _top1_accuracy(probs: np.ndarray, y: np.ndarray, race_ids: pd.Series) -> float:
    """
    val 内の各レースで P(着順=1, つまり class=0) が最大の艇の予測が、
    実際に 1 着だった艇と一致した割合。
    """
    df = pd.DataFrame(
        {
            "race_id": race_ids.values,
            "p_first": probs[:, 0],
            "is_first": (y == 0).astype(int),
        }
    )
    correct = 0
    total = 0
    for _, g in df.groupby("race_id", sort=False):
        if g["is_first"].sum() == 0:
            continue  # 1 着不在（DNF 等）
        pred_idx = g["p_first"].idxmax()
        if int(g.loc[pred_idx, "is_first"]) == 1:
            correct += 1
        total += 1
    return correct / total if total > 0 else float("nan")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--val-year", type=int, required=True)
    p.add_argument("--val-month", type=int, required=True)
    p.add_argument("--train-start-year", type=int, default=2023)
    p.add_argument("--train-start-month", type=int, default=1)
    p.add_argument("--tag", type=str, default="baseline", help="出力ラベル")
    p.add_argument(
        "--extra-features",
        type=str,
        nargs="*",
        default=[],
        help="build_features_from_history(extra_features=...) に渡す追加特徴量名リスト",
    )
    p.add_argument("--num-boost-round", type=int, default=1000)
    p.add_argument("--early-stopping-rounds", type=int, default=50)
    p.add_argument(
        "--out-jsonl",
        type=str,
        default=str(ROOT / "artifacts" / "feature_poc_results.jsonl"),
        help="結果を 1 行 append する JSONL パス",
    )
    args = p.parse_args()

    val_period = pd.Period(f"{args.val_year}-{args.val_month:02d}", freq="M")
    train_end_period = val_period - 1

    print(
        f"[PoC] tag={args.tag}  train={args.train_start_year}-{args.train_start_month:02d}"
        f"〜{train_end_period}  val={val_period}"
    )

    # ---- データロード（train_start 〜 val 月）----
    print("[1/5] history load")
    df_hist = load_history_range(
        start_year=args.train_start_year,
        start_month=args.train_start_month,
        end_year=args.val_year,
        end_month=args.val_month,
    )
    print(f"  history rows: {len(df_hist):,}")

    print("[2/5] program load + merge")
    df_prog = load_program_range(
        start_year=args.train_start_year,
        start_month=args.train_start_month,
        end_year=args.val_year,
        end_month=args.val_month,
    )
    df = merge_program_data(df_hist, df_prog)
    print(f"  after merge: {len(df):,}")

    print(f"[3/5] build features (extras={args.extra_features})")
    X, y, dates = build_features_from_history(
        df, return_dates=True, extra_features=args.extra_features
    )
    print(f"  features shape: {X.shape}  columns: {list(X.columns)}")

    # train/val split: dates の period が val_period かどうか
    date_period = pd.to_datetime(dates).dt.to_period("M")
    val_mask = (date_period == val_period).values
    train_mask = (date_period <= train_end_period).values

    X_train = X[train_mask]
    y_train = y[train_mask]
    X_val = X[val_mask]
    y_val = y[val_mask]

    # race_id を val 行に合わせて取得（top-1 accuracy 用）
    if "race_id" in df.columns:
        race_ids_val = df.loc[X.index[val_mask], "race_id"]
    else:
        raise RuntimeError("race_id 列がない、ハーネスを修正せよ")

    print(f"  train samples: {len(X_train):,}  val samples: {len(X_val):,}")
    if len(X_val) == 0:
        raise RuntimeError(f"val 月 {val_period} のデータが 0 行。データキャッシュを確認")

    # ---- 学習 ----
    print("[4/5] LightGBM train")
    dtrain = lgb.Dataset(X_train, label=y_train)
    dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)
    booster = lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=args.num_boost_round,
        valid_sets=[dval],
        callbacks=[
            lgb.early_stopping(stopping_rounds=args.early_stopping_rounds, verbose=True),
            lgb.log_evaluation(period=100),
        ],
    )

    # ---- 評価 ----
    print("[5/5] evaluate")
    raw_probs = booster.predict(X_val.values)
    norm_probs = _softmax_normalize(raw_probs)
    y_val_arr = y_val.values.astype(int)

    # per-class IR（trainer.py と同一手順）
    softmax_calibrators = []
    for k in range(6):
        true_k = (y_val_arr == k).astype(float)
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(norm_probs[:, k], true_k)
        softmax_calibrators.append(ir)
    cal_raw = np.stack(
        [softmax_calibrators[k].predict(norm_probs[:, k]) for k in range(6)], axis=1
    )
    cal_probs = _softmax_normalize(cal_raw)

    true_1st = (y_val_arr == 0).astype(float)
    ece_raw = _ece(raw_probs[:, 0], true_1st)
    ece_norm = _ece(norm_probs[:, 0], true_1st)
    ece_cal = _ece(cal_probs[:, 0], true_1st)

    top1_raw = _top1_accuracy(raw_probs, y_val_arr, race_ids_val)
    top1_norm = _top1_accuracy(norm_probs, y_val_arr, race_ids_val)
    top1_cal = _top1_accuracy(cal_probs, y_val_arr, race_ids_val)

    mlogloss_raw = _multi_logloss(raw_probs, y_val_arr)
    mlogloss_norm = _multi_logloss(norm_probs, y_val_arr)
    mlogloss_cal = _multi_logloss(cal_probs, y_val_arr)

    result = {
        "tag": args.tag,
        "val_period": str(val_period),
        "train_start": f"{args.train_start_year}-{args.train_start_month:02d}",
        "n_train": int(len(X_train)),
        "n_val": int(len(X_val)),
        "n_features": int(X.shape[1]),
        "feature_columns": list(X.columns),
        "best_iteration": int(booster.best_iteration or 0),
        "top1_accuracy_raw": top1_raw,
        "top1_accuracy_norm": top1_norm,
        "top1_accuracy_calibrated": top1_cal,
        "ece_rank1_raw": float(ece_raw),
        "ece_rank1_norm": float(ece_norm),
        "ece_rank1_calibrated": float(ece_cal),
        "multi_logloss_raw": float(mlogloss_raw),
        "multi_logloss_norm": float(mlogloss_norm),
        "multi_logloss_calibrated": float(mlogloss_cal),
    }

    print("---- RESULT ----")
    for k, v in result.items():
        if isinstance(v, list):
            continue
        print(f"  {k}: {v}")

    out_path = Path(args.out_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(f"appended → {out_path}")


if __name__ == "__main__":
    main()
