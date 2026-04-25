"""
目的関数変更 PoC ハーネス（タスク 6-10-b）

run_feature_poc.py の姉妹版。特徴量はベースライン 12 次元のまま固定し、
LightGBM の学習目的（objective）を切り替えて 1 着識別性能を比較する。

サポートする objective:
  - multiclass : ベースライン (trainer.py 同等、6 クラス分類)
  - binary     : B1 各艇独立に「1 着 か / そうでないか」の二値分類。
                  予測 prob をレース内で sum-to-1 正規化して 1 着確率とする。
  - lambdarank : R1 LightGBM `objective=lambdarank`。group=race、relevance = 5 - y。
                  生スコアをレース内 softmax で確率化。
  - rank_xendcg: P1 LambdaRank の比較対照。同じく score → softmax。

評価指標 (val=指定単月):
  - top-1 accuracy (raw / softmax-normalized)
  - NDCG@1, NDCG@3 (race 単位平均)
  - 1 着 ECE (1着確率 vs 実 1 着フラグ)
  - multi_logloss (multiclass のみで意味、他は参考値)

使い方:
  py -3.12 ml/src/scripts/run_objective_poc.py --val-year 2025 --val-month 12 --tag B1_binary --objective binary
  py -3.12 ml/src/scripts/run_objective_poc.py --val-year 2025 --val-month 12 --tag R1_lambdarank --objective lambdarank
  py -3.12 ml/src/scripts/run_objective_poc.py --val-year 2025 --val-month 12 --tag P1_rank_xendcg --objective rank_xendcg

注意:
  - trainer.py / predictor.py は一切変更しない（PoC 専用ハーネス）。
  - 採用判断は top-1 accuracy +1.0pp 以上 (B1/R1/P1 共通、6-10-a より厳しめ)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from collector.history_downloader import load_history_range  # noqa: E402
from collector.program_downloader import load_program_range, merge_program_data  # noqa: E402
from features.feature_builder import build_features_from_history  # noqa: E402
from model.trainer import LGB_PARAMS, _ece  # noqa: E402

# ベースライン LGB_PARAMS のうち objective/num_class/metric 以外を継承する
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


def _race_softmax(score: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    """レース単位で score を softmax 正規化して 1 着確率を返す (1 次元 array)."""
    out = np.zeros_like(score, dtype=float)
    df = pd.DataFrame({"race_id": race_ids, "score": score})
    for _, idx in df.groupby("race_id", sort=False).groups.items():
        s = score[idx]
        s = s - s.max()  # 数値安定化
        e = np.exp(s)
        out[idx] = e / e.sum()
    return out


def _race_normalize(prob: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    """レース単位で prob を sum-to-1 正規化（B1 用、score がすでに [0,1] の場合）"""
    out = np.zeros_like(prob, dtype=float)
    df = pd.DataFrame({"race_id": race_ids, "p": prob})
    for _, idx in df.groupby("race_id", sort=False).groups.items():
        p = prob[idx]
        s = p.sum()
        if s > 0:
            out[idx] = p / s
        else:
            out[idx] = 1.0 / len(p)
    return out


def _top1_from_p_first(
    p_first: np.ndarray, y: np.ndarray, race_ids: np.ndarray
) -> float:
    """各レースで p_first 最大の艇が y==0 と一致した割合"""
    df = pd.DataFrame(
        {
            "race_id": race_ids,
            "p_first": p_first,
            "is_first": (y == 0).astype(int),
        }
    )
    correct = 0
    total = 0
    for _, g in df.groupby("race_id", sort=False):
        if g["is_first"].sum() == 0:
            continue
        pred_idx = g["p_first"].idxmax()
        if int(g.loc[pred_idx, "is_first"]) == 1:
            correct += 1
        total += 1
    return correct / total if total > 0 else float("nan")


def _ndcg_at_k(
    score: np.ndarray, y: np.ndarray, race_ids: np.ndarray, k: int
) -> float:
    """
    各レース内で score 降順に並べ、relevance=(5-y) を使って NDCG@k を計算した平均。
    y は 0=1着 〜 5=6着。relevance は 5,4,3,2,1,0 (1着=5)。
    """
    df = pd.DataFrame(
        {
            "race_id": race_ids,
            "score": score,
            "rel": 5 - y.astype(int),
        }
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
        # DCG: sum (2^rel - 1) / log2(rank+1)
        dcg = float(((2.0 ** topk_rel - 1) / ranks).sum())
        ideal_rel = np.sort(rel)[::-1][:kk]
        idcg = float(((2.0 ** ideal_rel - 1) / ranks).sum())
        if idcg > 0:
            vals.append(dcg / idcg)
    return float(np.mean(vals)) if vals else float("nan")


def _build_groups(race_ids: pd.Series) -> np.ndarray:
    """
    race_id が連続塊になっている前提で group ベクトルを作る。
    呼び出し前に _sort_for_ranking で race_id 順に並べ替えていること。
    """
    counts = []
    cur = None
    for r in race_ids.values:
        if r != cur:
            counts.append(1)
            cur = r
        else:
            counts[-1] += 1
    return np.array(counts, dtype=int)


def _sort_for_ranking(
    X: pd.DataFrame, y: np.ndarray, race_ids: pd.Series
) -> tuple[pd.DataFrame, np.ndarray, pd.Series]:
    """
    ranking 系 objective 用に race_id 順で並べ直す（同 race の行を連続させる）。
    元データが sort 済みでも非連続な race_id が混じる可能性に対する防御。
    """
    order = np.argsort(race_ids.values, kind="stable")
    X_sorted = X.iloc[order].reset_index(drop=True)
    y_sorted = y[order]
    rid_sorted = race_ids.iloc[order].reset_index(drop=True)
    return X_sorted, y_sorted, rid_sorted


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--val-year", type=int, required=True)
    p.add_argument("--val-month", type=int, required=True)
    p.add_argument("--train-start-year", type=int, default=2023)
    p.add_argument("--train-start-month", type=int, default=1)
    p.add_argument("--tag", type=str, default="objective_poc")
    p.add_argument(
        "--objective",
        type=str,
        required=True,
        choices=["multiclass", "binary", "lambdarank", "rank_xendcg"],
        help="LightGBM objective. multiclass=baseline, binary=B1, lambdarank=R1, rank_xendcg=P1",
    )
    p.add_argument("--num-boost-round", type=int, default=1000)
    p.add_argument("--early-stopping-rounds", type=int, default=50)
    p.add_argument(
        "--out-jsonl",
        type=str,
        default=str(ROOT / "artifacts" / "objective_poc_results.jsonl"),
    )
    args = p.parse_args()

    val_period = pd.Period(f"{args.val_year}-{args.val_month:02d}", freq="M")
    train_end_period = val_period - 1
    print(
        f"[obj-PoC] tag={args.tag} obj={args.objective} "
        f"train={args.train_start_year}-{args.train_start_month:02d}〜{train_end_period} "
        f"val={val_period}"
    )

    # ---- データ ----
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

    print("[3/5] build features (baseline 12 dims)")
    X, y, dates = build_features_from_history(df, return_dates=True)
    print(f"  features shape: {X.shape}")

    date_period = pd.to_datetime(dates).dt.to_period("M")
    val_mask = (date_period == val_period).values
    train_mask = (date_period <= train_end_period).values

    X_train = X[train_mask]
    y_train = y[train_mask]
    X_val = X[val_mask]
    y_val = y[val_mask]

    if "race_id" not in df.columns:
        raise RuntimeError("race_id 列がない、ハーネスを修正せよ")
    race_ids_train = df.loc[X.index[train_mask], "race_id"].reset_index(drop=True)
    race_ids_val = df.loc[X.index[val_mask], "race_id"].reset_index(drop=True)

    print(
        f"  train samples: {len(X_train):,}  val samples: {len(X_val):,}  "
        f"(val races ~ {race_ids_val.nunique():,})"
    )
    if len(X_val) == 0:
        raise RuntimeError(f"val 月 {val_period} のデータが 0 行")

    # ---- 学習 ----
    print(f"[4/5] LightGBM train (objective={args.objective})")
    y_train_arr = y_train.values.astype(int)
    y_val_arr = y_val.values.astype(int)

    # objective ごとにラベル変換と Dataset 構築を切り替える
    if args.objective == "multiclass":
        params = {**SHARED_LGB_PARAMS, "objective": "multiclass", "num_class": 6,
                  "metric": "multi_logloss"}
        dtrain = lgb.Dataset(X_train, label=y_train_arr)
        dval = lgb.Dataset(X_val, label=y_val_arr, reference=dtrain)
    elif args.objective == "binary":
        # 各艇独立: 1 着 (y==0) を陽性
        label_train = (y_train_arr == 0).astype(int)
        label_val = (y_val_arr == 0).astype(int)
        params = {**SHARED_LGB_PARAMS, "objective": "binary", "metric": "binary_logloss"}
        dtrain = lgb.Dataset(X_train, label=label_train)
        dval = lgb.Dataset(X_val, label=label_val, reference=dtrain)
    elif args.objective in ("lambdarank", "rank_xendcg"):
        # ranking 系は race_id 連続塊前提なので明示的に並び替える
        Xt_r, yt_r, rid_t_r = _sort_for_ranking(X_train, y_train_arr, race_ids_train)
        Xv_r, yv_r, rid_v_r = _sort_for_ranking(X_val, y_val_arr, race_ids_val)
        # relevance = 5 - y (1着=5, 6着=0)
        label_train = (5 - yt_r).astype(int)
        label_val = (5 - yv_r).astype(int)
        group_train = _build_groups(rid_t_r)
        group_val = _build_groups(rid_v_r)
        if group_train.sum() != len(Xt_r):
            raise RuntimeError("group_train sum mismatch")
        if group_val.sum() != len(Xv_r):
            raise RuntimeError("group_val sum mismatch")
        params = {
            **SHARED_LGB_PARAMS,
            "objective": args.objective,
            "metric": "ndcg",
            "ndcg_eval_at": [1, 3],
            "label_gain": [0, 1, 3, 7, 15, 31],  # 2^rel - 1 (rel=0..5)
        }
        dtrain = lgb.Dataset(Xt_r, label=label_train, group=group_train)
        dval = lgb.Dataset(Xv_r, label=label_val, group=group_val, reference=dtrain)
        # 評価用に X_val と race_ids_val を ranking 用ソート版に置き換える
        X_val = Xv_r
        y_val_arr = yv_r
        race_ids_val = rid_v_r
    else:
        raise RuntimeError(f"unknown objective {args.objective}")

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

    # ---- 評価 ----
    print("[5/5] evaluate")
    rid_val = race_ids_val.values
    raw_pred = booster.predict(X_val.values)

    if args.objective == "multiclass":
        # raw_pred: (N, 6) — class 0 の prob が p_first
        p_first_raw = raw_pred[:, 0]
        # レース内 sum-to-1 正規化 (multiclass なら sum はほぼ 1 だが念のため)
        p_first_norm = _race_normalize(p_first_raw, rid_val)
        score_for_ndcg = p_first_raw  # ndcg は class-0 prob で 1 着順位を作る
        mlogloss = float(
            -np.log(np.clip(raw_pred[np.arange(len(y_val_arr)), y_val_arr], 1e-15, 1)).mean()
        )
    elif args.objective == "binary":
        # raw_pred: (N,) sigmoid 出力 [0,1]
        p_first_raw = raw_pred
        p_first_norm = _race_normalize(p_first_raw, rid_val)
        score_for_ndcg = raw_pred
        mlogloss = float("nan")  # multiclass log-likelihood は計算不可
    else:  # lambdarank / rank_xendcg
        # raw_pred: (N,) スコア (実数)。レース内 softmax で 1 着確率を作る
        score_for_ndcg = raw_pred
        p_first_norm = _race_softmax(raw_pred, rid_val)
        p_first_raw = p_first_norm  # raw 概念がないため norm を流用
        mlogloss = float("nan")

    top1_raw = _top1_from_p_first(p_first_raw, y_val_arr, rid_val)
    top1_norm = _top1_from_p_first(p_first_norm, y_val_arr, rid_val)

    ndcg1 = _ndcg_at_k(score_for_ndcg, y_val_arr, rid_val, k=1)
    ndcg3 = _ndcg_at_k(score_for_ndcg, y_val_arr, rid_val, k=3)

    true_1st = (y_val_arr == 0).astype(float)
    ece_raw = _ece(p_first_raw, true_1st)
    ece_norm = _ece(p_first_norm, true_1st)

    result = {
        "tag": args.tag,
        "objective": args.objective,
        "val_period": str(val_period),
        "train_start": f"{args.train_start_year}-{args.train_start_month:02d}",
        "n_train": int(len(X_train)),
        "n_val": int(len(X_val)),
        "n_features": int(X.shape[1]),
        "feature_columns": list(X.columns),
        "best_iteration": int(booster.best_iteration or 0),
        "top1_accuracy_raw": float(top1_raw),
        "top1_accuracy_norm": float(top1_norm),
        "ndcg_at_1": float(ndcg1),
        "ndcg_at_3": float(ndcg3),
        "ece_rank1_raw": float(ece_raw),
        "ece_rank1_norm": float(ece_norm),
        "multi_logloss_raw": float(mlogloss),
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
