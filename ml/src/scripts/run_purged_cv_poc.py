"""
Purged / Embargoed time-series CV PoC ハーネス（タスク 6-10-c）

run_objective_poc.py の姉妹版。特徴量・objective はベースライン（multiclass 12 次元）
で固定し、train/val split のロジックだけを変えて leak の影響を測る。

サポートする split-mode:
  - baseline      : 月境界 split（現行 PoC と同じ）
  - embargo7      : train を val 月開始日 - 7 日 より前に限定
  - embargo14     : train を val 月開始日 - 14 日 より前に限定
  - meeting_purge : val 月開始日 - 7 日以降に同一場で行われたレースを train から除外
                    （meeting_id 不在のため近似。将来 program data から meeting boundary
                    を抽出する設計に差し替え可能。注: 外側の embargo は適用しない方針 ）

評価指標 (val=指定単月):
  - top-1 accuracy (raw / softmax-normalized)
  - NDCG@1, NDCG@3 (race 単位平均)
  - 1 着 ECE
  - multi_logloss
  - 参考: train サンプル削減率（baseline 比）

使い方:
  py -3.12 ml/src/scripts/run_purged_cv_poc.py --val-year 2025 --val-month 12 \
      --tag PCV_baseline       --split-mode baseline
  py -3.12 ml/src/scripts/run_purged_cv_poc.py --val-year 2025 --val-month 12 \
      --tag PCV_embargo7       --split-mode embargo7
  py -3.12 ml/src/scripts/run_purged_cv_poc.py --val-year 2025 --val-month 12 \
      --tag PCV_embargo14      --split-mode embargo14
  py -3.12 ml/src/scripts/run_purged_cv_poc.py --val-year 2025 --val-month 12 \
      --tag PCV_meeting_purge  --split-mode meeting_purge

採用判断 (PURGED_CV_POC_RESULTS.md):
  - leak あり baseline と embargo/meeting_purge の top-1 accuracy 差で評価
  - +0.5pp 以上低下なら leak 確認 → 採用
  - ±0.3pp 以内なら leak 影響なし → 却下

注意:
  - trainer.py / predictor.py / engine.py は一切変更しない（PoC 専用ハーネス）。
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


def _race_normalize(prob: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    """レース単位で prob を sum-to-1 正規化"""
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
        dcg = float(((2.0 ** topk_rel - 1) / ranks).sum())
        ideal_rel = np.sort(rel)[::-1][:kk]
        idcg = float(((2.0 ** ideal_rel - 1) / ranks).sum())
        if idcg > 0:
            vals.append(dcg / idcg)
    return float(np.mean(vals)) if vals else float("nan")


def _build_train_mask(
    dates: pd.Series,
    stadium_ids: pd.Series,
    val_period: pd.Period,
    split_mode: str,
) -> np.ndarray:
    """
    split-mode に応じて train mask を構築する。val mask は呼び出し側で計算する。

    Parameters
    ----------
    dates : pd.Series (datetime64)  全行の race_date
    stadium_ids : pd.Series (int)   全行の stadium_id
    val_period : pd.Period          val 月（月単位）
    split_mode : str                baseline / embargo7 / embargo14 / meeting_purge

    Returns
    -------
    np.ndarray (bool)  train 行を True にした mask
    """
    val_start_ts = pd.Timestamp(val_period.start_time.date())
    val_end_ts = pd.Timestamp(val_period.end_time.date())

    if split_mode == "baseline":
        # 月境界 split: val 月より前を train
        return (dates < val_start_ts).values

    if split_mode == "embargo7":
        cutoff = val_start_ts - pd.Timedelta(days=7)
        return (dates < cutoff).values

    if split_mode == "embargo14":
        cutoff = val_start_ts - pd.Timedelta(days=14)
        return (dates < cutoff).values

    if split_mode == "meeting_purge":
        # 月境界 split をベースに、val 月開始日 - 7 日以降に同一場でレースがある
        # (stadium_id, race_date) を train から除外する近似。
        # 将来: program data から meeting boundary (節の初日〜最終日) を抽出して
        # 同一節を完全除外する設計に差し替え可能。
        base = (dates < val_start_ts).values
        purge_window_start = val_start_ts - pd.Timedelta(days=7)
        # val 月内に出走実績のある stadium に対し、purge_window_start 以降の
        # 同 stadium のレースを除外
        df_v = pd.DataFrame(
            {"date": dates.values, "sid": stadium_ids.values}
        )
        val_sids = set(
            df_v.loc[(df_v["date"] >= val_start_ts) & (df_v["date"] <= val_end_ts), "sid"]
            .dropna()
            .astype(int)
            .unique()
        )
        in_purge = (
            (df_v["date"] >= purge_window_start)
            & (df_v["date"] < val_start_ts)
            & (df_v["sid"].isin(val_sids))
        ).values
        return base & ~in_purge

    raise ValueError(f"unknown split_mode: {split_mode}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--val-year", type=int, required=True)
    p.add_argument("--val-month", type=int, required=True)
    p.add_argument("--train-start-year", type=int, default=2023)
    p.add_argument("--train-start-month", type=int, default=1)
    p.add_argument("--tag", type=str, default="purged_cv_poc")
    p.add_argument(
        "--split-mode",
        type=str,
        required=True,
        choices=["baseline", "embargo7", "embargo14", "meeting_purge"],
    )
    p.add_argument("--num-boost-round", type=int, default=1000)
    p.add_argument("--early-stopping-rounds", type=int, default=50)
    p.add_argument(
        "--out-jsonl",
        type=str,
        default=str(ROOT / "artifacts" / "purged_cv_poc_results.jsonl"),
    )
    args = p.parse_args()

    val_period = pd.Period(f"{args.val_year}-{args.val_month:02d}", freq="M")
    print(
        f"[PCV-PoC] tag={args.tag} split={args.split_mode} "
        f"train_start={args.train_start_year}-{args.train_start_month:02d} "
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

    # race_id / stadium_id を X と同じ index 順で取り出す
    if "race_id" not in df.columns:
        raise RuntimeError("race_id 列がない")
    if "stadium_id" not in df.columns:
        raise RuntimeError("stadium_id 列がない")
    race_ids_all = df.loc[X.index, "race_id"].reset_index(drop=True)
    stadium_ids_all = df.loc[X.index, "stadium_id"].reset_index(drop=True)
    dates_aligned = pd.to_datetime(dates).reset_index(drop=True)

    # val mask: 月境界（全 mode 共通）
    date_period = dates_aligned.dt.to_period("M")
    val_mask = (date_period == val_period).values

    # train mask: split_mode で切り替え
    train_mask = _build_train_mask(
        dates=dates_aligned,
        stadium_ids=stadium_ids_all,
        val_period=val_period,
        split_mode=args.split_mode,
    )

    # baseline 比の削減率を測るため、参考の baseline mask も計算
    baseline_train_mask = _build_train_mask(
        dates=dates_aligned,
        stadium_ids=stadium_ids_all,
        val_period=val_period,
        split_mode="baseline",
    )

    X_train = X.iloc[train_mask].reset_index(drop=True)
    y_train = y.iloc[train_mask].reset_index(drop=True)
    X_val = X.iloc[val_mask].reset_index(drop=True)
    y_val = y.iloc[val_mask].reset_index(drop=True)
    race_ids_val = race_ids_all.iloc[val_mask].reset_index(drop=True)

    n_train = int(len(X_train))
    n_train_baseline = int(baseline_train_mask.sum())
    train_reduction = (
        1.0 - n_train / n_train_baseline if n_train_baseline > 0 else float("nan")
    )

    print(
        f"  train samples: {n_train:,} "
        f"(baseline {n_train_baseline:,}, reduction {train_reduction:.4f})  "
        f"val samples: {len(X_val):,}  (val races ~ {race_ids_val.nunique():,})"
    )
    if len(X_val) == 0:
        raise RuntimeError(f"val 月 {val_period} のデータが 0 行")
    if n_train == 0:
        raise RuntimeError("train サンプルが 0 行（split_mode 設定を見直せ）")

    # ---- 学習 (multiclass 固定) ----
    print(f"[4/5] LightGBM train (objective=multiclass)")
    y_train_arr = y_train.values.astype(int)
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

    # ---- 評価 ----
    print("[5/5] evaluate")
    rid_val = race_ids_val.values
    raw_pred = booster.predict(X_val.values)

    # raw_pred: (N, 6) — class 0 の prob が p_first
    p_first_raw = raw_pred[:, 0]
    p_first_norm = _race_normalize(p_first_raw, rid_val)
    score_for_ndcg = p_first_raw
    mlogloss = float(
        -np.log(np.clip(raw_pred[np.arange(len(y_val_arr)), y_val_arr], 1e-15, 1)).mean()
    )

    top1_raw = _top1_from_p_first(p_first_raw, y_val_arr, rid_val)
    top1_norm = _top1_from_p_first(p_first_norm, y_val_arr, rid_val)
    ndcg1 = _ndcg_at_k(score_for_ndcg, y_val_arr, rid_val, k=1)
    ndcg3 = _ndcg_at_k(score_for_ndcg, y_val_arr, rid_val, k=3)
    true_1st = (y_val_arr == 0).astype(float)
    ece_raw = _ece(p_first_raw, true_1st)
    ece_norm = _ece(p_first_norm, true_1st)

    result = {
        "tag": args.tag,
        "split_mode": args.split_mode,
        "val_period": str(val_period),
        "train_start": f"{args.train_start_year}-{args.train_start_month:02d}",
        "n_train": n_train,
        "n_train_baseline": n_train_baseline,
        "train_reduction_ratio": float(train_reduction),
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
