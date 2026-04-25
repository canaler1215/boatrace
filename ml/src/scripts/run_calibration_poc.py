"""
キャリブレーション再設計 PoC ハーネス（タスク 6-10-c 第 2 候補 C1/C2）

run_purged_cv_poc.py の姉妹版。LightGBM 出力 (multiclass 6 クラス) に対する
キャリブレーション手法を切り替えて確率質と top-1 を比較する。

split 構成（PoC 全 calibrator で共通、apples-to-apples 比較のため）:
  - train (LightGBM 学習): 2023-01 〜 (val_period - 2 ヶ月)
  - cal   (calibrator fit): val_period - 1 ヶ月（単月）
  - eval  (評価): val_period（単月）

サポートする calibrator-mode:
  - per_class_ir : per-class IsotonicRegression + softmax 再正規化（trainer.py 同等）
  - joint_ir     : C2: per-class IR の出力を logit 化して最終 softmax で再結合
                   （独立 fit ではなく、6 クラスをまとめて softmax 正規化に通すことで
                    sum-to-1 制約を学習段階で考慮した結合 IR 近似）
  - dirichlet    : C1: Dirichlet calibration. log(p_norm) を入力にして 6 クラス
                   多項ロジスティック回帰を fit。`sklearn.linear_model.LogisticRegression`
                   (multinomial, L2 正則化) で実装

評価指標 (val=指定単月):
  - top-1 accuracy (calibrated)
  - NDCG@1, NDCG@3
  - 1 着 ECE (raw / calibrated)
  - trifecta ECE (calibrated): 3 連単確率 vs 実 3 連単的中フラグ（CLAUDE.md 重大発見の直接指標）
  - multi_logloss (calibrated)

使い方:
  py -3.12 ml/src/scripts/run_calibration_poc.py --val-year 2025 --val-month 12 \
      --tag CAL_baseline   --calibrator per_class_ir
  py -3.12 ml/src/scripts/run_calibration_poc.py --val-year 2025 --val-month 12 \
      --tag CAL_C2_joint_ir --calibrator joint_ir
  py -3.12 ml/src/scripts/run_calibration_poc.py --val-year 2025 --val-month 12 \
      --tag CAL_C1_dirichlet --calibrator dirichlet

採用判断:
  - top-1 accuracy +1.0pp 以上 → 採用
  - +0.5〜+1.0pp → 保留
  - +0.5pp 未満 → 却下
  - 補助基準: trifecta ECE が baseline 比 50% 以上改善 → 保留以上として記録

注意:
  - trainer.py / predictor.py / engine.py は一切変更しない（PoC 専用ハーネス）。
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from collector.history_downloader import load_history_range  # noqa: E402
from collector.program_downloader import load_program_range, merge_program_data  # noqa: E402
from features.feature_builder import build_features_from_history  # noqa: E402
from model.trainer import LGB_PARAMS, _ece  # noqa: E402

SHARED_LGB_PARAMS = {
    "learning_rate": LGB_PARAMS["learning_rate"],
    "num_leaves": LGB_PARAMS["num_leaves"],
    "min_child_samples": LGB_PARAMS["min_child_samples"],
    "feature_fraction": LGB_PARAMS["feature_fraction"],
    "bagging_fraction": LGB_PARAMS["bagging_fraction"],
    "bagging_freq": LGB_PARAMS["bagging_freq"],
    "verbose": -1,
    "n_jobs": -1,
}


def _row_softmax(z: np.ndarray) -> np.ndarray:
    """行ごとの softmax (N, K)"""
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def _row_normalize(p: np.ndarray) -> np.ndarray:
    """行ごとの sum-to-1 (N, K)"""
    s = p.sum(axis=1, keepdims=True)
    return p / np.maximum(s, 1e-12)


# --------------------------------------------------------------------- top-1
def _top1_from_p_first(
    p_first: np.ndarray, y: np.ndarray, race_ids: np.ndarray
) -> float:
    df = pd.DataFrame(
        {"race_id": race_ids, "p_first": p_first, "is_first": (y == 0).astype(int)}
    )
    correct = total = 0
    for _, g in df.groupby("race_id", sort=False):
        if g["is_first"].sum() == 0:
            continue
        if int(g.loc[g["p_first"].idxmax(), "is_first"]) == 1:
            correct += 1
        total += 1
    return correct / total if total else float("nan")


# --------------------------------------------------------------------- NDCG
def _ndcg_at_k(
    score: np.ndarray, y: np.ndarray, race_ids: np.ndarray, k: int
) -> float:
    df = pd.DataFrame(
        {"race_id": race_ids, "score": score, "rel": 5 - y.astype(int)}
    )
    vals = []
    for _, g in df.groupby("race_id", sort=False):
        rel = g["rel"].values
        sc = g["score"].values
        kk = min(k, len(rel))
        if kk == 0:
            continue
        order = np.argsort(-sc)
        topk_rel = rel[order][:kk]
        ranks = np.log2(np.arange(2, kk + 2))
        dcg = float(((2.0 ** topk_rel - 1) / ranks).sum())
        ideal_rel = np.sort(rel)[::-1][:kk]
        idcg = float(((2.0 ** ideal_rel - 1) / ranks).sum())
        if idcg > 0:
            vals.append(dcg / idcg)
    return float(np.mean(vals)) if vals else float("nan")


# --------------------------------------------------------------------- trifecta ECE
def _trifecta_ece(
    cal_probs: np.ndarray,
    y: np.ndarray,
    race_ids: np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Plackett-Luce 近似で 3 連単 (1着, 2着, 3着) 確率を計算し、
    実際の 3 連単的中フラグとの ECE を返す。

    各レースで全 boat の 1 着確率 p1 を入力に取り、
      P(a→b→c) = p1[a] * p1[b]/(1 - p1[a]) * p1[c]/(1 - p1[a] - p1[b])
    として全 6P3=120 通りの 3 連単確率を計算。
    実際の (1着, 2着, 3着) 並びを正解とする。

    全レース・全 120 通りを 1 つの ECE 配列にまとめて 10-bin ECE を返す。
    """
    df = pd.DataFrame(
        {
            "race_id": race_ids,
            "boat_idx": np.arange(len(y)),
            "p1": cal_probs[:, 0],
            "y": y.astype(int),
        }
    )
    all_probs = []
    all_targets = []
    for _, g in df.groupby("race_id", sort=False):
        if len(g) < 6:
            continue
        rows = g.reset_index(drop=True)
        p1 = rows["p1"].values
        # 真の 1, 2, 3 着の boat_idx を rows 内 index で取得
        # y==0: 1着, y==1: 2着, y==2: 3着
        try:
            true_a = int(np.where(rows["y"].values == 0)[0][0])
            true_b = int(np.where(rows["y"].values == 1)[0][0])
            true_c = int(np.where(rows["y"].values == 2)[0][0])
        except IndexError:
            continue
        for a, b, c in permutations(range(len(rows)), 3):
            denom1 = max(1.0 - p1[a], 1e-9)
            denom2 = max(1.0 - p1[a] - p1[b], 1e-9)
            p_abc = p1[a] * (p1[b] / denom1) * (p1[c] / denom2)
            p_abc = float(np.clip(p_abc, 0.0, 1.0))
            target = 1.0 if (a == true_a and b == true_b and c == true_c) else 0.0
            all_probs.append(p_abc)
            all_targets.append(target)

    if not all_probs:
        return float("nan")
    probs = np.array(all_probs)
    targets = np.array(all_targets)
    return _ece(probs, targets, n_bins=n_bins)


# --------------------------------------------------------------------- calibrators
def _fit_per_class_ir(
    raw_probs_cal: np.ndarray, y_cal: np.ndarray
) -> list[IsotonicRegression]:
    """trainer.py 同等: row 正規化 → per-class IR fit"""
    norm = _row_normalize(raw_probs_cal)
    irs = []
    for k in range(6):
        true_k = (y_cal == k).astype(float)
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(norm[:, k], true_k)
        irs.append(ir)
    return irs


def _apply_per_class_ir(
    raw_probs: np.ndarray, irs: list[IsotonicRegression]
) -> np.ndarray:
    """per-class IR 適用 → row 再正規化"""
    norm = _row_normalize(raw_probs)
    cal_raw = np.stack([irs[k].predict(norm[:, k]) for k in range(6)], axis=1)
    return _row_normalize(cal_raw)


def _fit_joint_ir(
    raw_probs_cal: np.ndarray, y_cal: np.ndarray
) -> tuple[list[IsotonicRegression], float]:
    """
    C2 結合 IR: per-class IR を fit し、適用時は logit に変換して softmax で再結合する。
    softmax の温度 T は cal split 上で多項 NLL を最小化するように 1 次元 grid search で選ぶ。
    """
    irs = _fit_per_class_ir(raw_probs_cal, y_cal)
    # logit 変換 → softmax 再結合の温度を grid search
    norm = _row_normalize(raw_probs_cal)
    cal_raw = np.stack([irs[k].predict(norm[:, k]) for k in range(6)], axis=1)
    cal_clip = np.clip(cal_raw, 1e-6, 1 - 1e-6)
    logit = np.log(cal_clip)  # log-prob を softmax 入力に
    best_t, best_nll = 1.0, float("inf")
    for t in np.linspace(0.5, 2.0, 31):
        z = logit / t
        p = _row_softmax(z)
        nll = -np.log(np.clip(p[np.arange(len(y_cal)), y_cal], 1e-15, 1)).mean()
        if nll < best_nll:
            best_nll = nll
            best_t = t
    return irs, float(best_t)


def _apply_joint_ir(
    raw_probs: np.ndarray, irs: list[IsotonicRegression], temperature: float
) -> np.ndarray:
    norm = _row_normalize(raw_probs)
    cal_raw = np.stack([irs[k].predict(norm[:, k]) for k in range(6)], axis=1)
    cal_clip = np.clip(cal_raw, 1e-6, 1 - 1e-6)
    logit = np.log(cal_clip)
    return _row_softmax(logit / temperature)


def _fit_dirichlet(
    raw_probs_cal: np.ndarray, y_cal: np.ndarray
) -> LogisticRegression:
    """
    C1 Dirichlet calibration: log(p_norm) を 6 次元入力として、
    sklearn の LogisticRegression(multi_class='multinomial', penalty='l2') を fit。
    """
    norm = _row_normalize(raw_probs_cal)
    log_p = np.log(np.clip(norm, 1e-12, 1.0))
    clf = LogisticRegression(
        multi_class="multinomial",
        solver="lbfgs",
        C=1.0,  # L2 正則化（デフォルト）
        max_iter=1000,
        n_jobs=-1,
    )
    clf.fit(log_p, y_cal)
    return clf


def _apply_dirichlet(
    raw_probs: np.ndarray, clf: LogisticRegression
) -> np.ndarray:
    norm = _row_normalize(raw_probs)
    log_p = np.log(np.clip(norm, 1e-12, 1.0))
    proba = clf.predict_proba(log_p)
    # クラス順を 0..5 に揃える（LogisticRegression はラベルでソートされる）
    classes = list(clf.classes_)
    if classes != list(range(6)):
        idx_map = [classes.index(k) for k in range(6)]
        proba = proba[:, idx_map]
    return proba


# --------------------------------------------------------------------- main
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--val-year", type=int, required=True)
    p.add_argument("--val-month", type=int, required=True)
    p.add_argument("--train-start-year", type=int, default=2023)
    p.add_argument("--train-start-month", type=int, default=1)
    p.add_argument("--tag", type=str, default="cal_poc")
    p.add_argument(
        "--calibrator",
        type=str,
        required=True,
        choices=["per_class_ir", "joint_ir", "dirichlet"],
    )
    p.add_argument("--num-boost-round", type=int, default=1000)
    p.add_argument("--early-stopping-rounds", type=int, default=50)
    p.add_argument(
        "--out-jsonl",
        type=str,
        default=str(ROOT / "artifacts" / "calibration_poc_results.jsonl"),
    )
    args = p.parse_args()

    val_period = pd.Period(f"{args.val_year}-{args.val_month:02d}", freq="M")
    cal_period = val_period - 1
    train_end_period = val_period - 2

    print(
        f"[CAL-PoC] tag={args.tag} cal={args.calibrator} "
        f"train={args.train_start_year}-{args.train_start_month:02d}〜{train_end_period} "
        f"cal={cal_period} val={val_period}"
    )

    # ---- データ ----
    print("[1/6] history load")
    df_hist = load_history_range(
        start_year=args.train_start_year,
        start_month=args.train_start_month,
        end_year=args.val_year,
        end_month=args.val_month,
    )
    print(f"  history rows: {len(df_hist):,}")

    print("[2/6] program load + merge")
    df_prog = load_program_range(
        start_year=args.train_start_year,
        start_month=args.train_start_month,
        end_year=args.val_year,
        end_month=args.val_month,
    )
    df = merge_program_data(df_hist, df_prog)
    print(f"  after merge: {len(df):,}")

    print("[3/6] build features (baseline 12 dims)")
    X, y, dates = build_features_from_history(df, return_dates=True)
    print(f"  features shape: {X.shape}")

    if "race_id" not in df.columns:
        raise RuntimeError("race_id 列がない")
    race_ids_all = df.loc[X.index, "race_id"].reset_index(drop=True)
    dates_aligned = pd.to_datetime(dates).reset_index(drop=True)
    date_period = dates_aligned.dt.to_period("M")

    train_mask = (date_period <= train_end_period).values
    cal_mask = (date_period == cal_period).values
    val_mask = (date_period == val_period).values

    X_train = X.iloc[train_mask].reset_index(drop=True)
    y_train = y.iloc[train_mask].reset_index(drop=True)
    X_cal = X.iloc[cal_mask].reset_index(drop=True)
    y_cal = y.iloc[cal_mask].reset_index(drop=True)
    X_val = X.iloc[val_mask].reset_index(drop=True)
    y_val = y.iloc[val_mask].reset_index(drop=True)
    rid_val = race_ids_all.iloc[val_mask].reset_index(drop=True).values

    print(
        f"  train: {len(X_train):,}  cal: {len(X_cal):,}  val: {len(X_val):,} "
        f"(val races ~ {pd.Series(rid_val).nunique():,})"
    )
    if len(X_val) == 0 or len(X_cal) == 0 or len(X_train) == 0:
        raise RuntimeError("split のいずれかが 0 行")

    # ---- LightGBM 学習（全 calibrator 共通の base model）----
    print("[4/6] LightGBM train (objective=multiclass)")
    y_train_arr = y_train.values.astype(int)
    y_cal_arr = y_cal.values.astype(int)
    y_val_arr = y_val.values.astype(int)

    params = {
        **SHARED_LGB_PARAMS,
        "objective": "multiclass",
        "num_class": 6,
        "metric": "multi_logloss",
    }
    dtrain = lgb.Dataset(X_train, label=y_train_arr)
    dval = lgb.Dataset(X_val, label=y_val_arr, reference=dtrain)

    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=args.num_boost_round,
        valid_sets=[dval],
        callbacks=[
            lgb.early_stopping(stopping_rounds=args.early_stopping_rounds, verbose=True),
            lgb.log_evaluation(period=100),
        ],
    )

    # ---- calibrator fit ----
    print(f"[5/6] fit calibrator ({args.calibrator}) on cal split")
    raw_cal = booster.predict(X_cal.values)
    raw_val = booster.predict(X_val.values)

    extra_meta: dict = {}
    if args.calibrator == "per_class_ir":
        irs = _fit_per_class_ir(raw_cal, y_cal_arr)
        cal_val = _apply_per_class_ir(raw_val, irs)
    elif args.calibrator == "joint_ir":
        irs, temperature = _fit_joint_ir(raw_cal, y_cal_arr)
        cal_val = _apply_joint_ir(raw_val, irs, temperature)
        extra_meta["temperature"] = temperature
        print(f"  joint_ir temperature: {temperature:.4f}")
    elif args.calibrator == "dirichlet":
        clf = _fit_dirichlet(raw_cal, y_cal_arr)
        cal_val = _apply_dirichlet(raw_val, clf)
        extra_meta["dirichlet_n_iter"] = int(clf.n_iter_.max())
        print(f"  dirichlet n_iter: {extra_meta['dirichlet_n_iter']}")
    else:
        raise RuntimeError(f"unknown calibrator {args.calibrator}")

    # ---- 評価 ----
    print("[6/6] evaluate")
    p_first_raw = raw_val[:, 0]
    p_first_cal = cal_val[:, 0]

    top1_raw = _top1_from_p_first(p_first_raw, y_val_arr, rid_val)
    top1_cal = _top1_from_p_first(p_first_cal, y_val_arr, rid_val)

    ndcg1 = _ndcg_at_k(p_first_cal, y_val_arr, rid_val, k=1)
    ndcg3 = _ndcg_at_k(p_first_cal, y_val_arr, rid_val, k=3)

    true_1st = (y_val_arr == 0).astype(float)
    ece_raw = _ece(p_first_raw, true_1st)
    ece_cal = _ece(p_first_cal, true_1st)

    mlogloss_cal = float(
        -np.log(np.clip(cal_val[np.arange(len(y_val_arr)), y_val_arr], 1e-15, 1)).mean()
    )

    tri_ece = _trifecta_ece(cal_val, y_val_arr, rid_val)

    result = {
        "tag": args.tag,
        "calibrator": args.calibrator,
        "val_period": str(val_period),
        "cal_period": str(cal_period),
        "train_end": str(train_end_period),
        "n_train": int(len(X_train)),
        "n_cal": int(len(X_cal)),
        "n_val": int(len(X_val)),
        "n_features": int(X.shape[1]),
        "best_iteration": int(booster.best_iteration or 0),
        "top1_accuracy_raw": float(top1_raw),
        "top1_accuracy_cal": float(top1_cal),
        "ndcg_at_1": float(ndcg1),
        "ndcg_at_3": float(ndcg3),
        "ece_rank1_raw": float(ece_raw),
        "ece_rank1_cal": float(ece_cal),
        "trifecta_ece_cal": float(tri_ece),
        "multi_logloss_cal": float(mlogloss_cal),
        **extra_meta,
    }

    print("---- RESULT ----")
    for k, v in result.items():
        print(f"  {k}: {v}")

    out_path = Path(args.out_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(f"appended → {out_path}")


if __name__ == "__main__":
    main()
