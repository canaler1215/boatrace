"""
LightGBM 学習スクリプト
各艇の1着確率を推定するマルチクラス分類モデル (6クラス = 着順1〜6)

Session 6 変更点:
  - Temperature Scaling を廃止 → ソフトマックス正規化 + Isotonic Regression（per-bin 補正）
  - val データで: raw probs → softmax 正規化 → per-class IR 学習 → 再正規化
  - 保存形式: {"booster": lgb.Booster, "softmax_calibrators": list[IsotonicRegression]}
  - sum-to-1 を保持したまま構造的なビン別バイアスを補正（Session 3 の課題を解決）

Session 5 変更点（廃止済み）:
  - Temperature Scaling: T≈1.0 に収束しグローバルスカラーでは解決不可能と確定

Model Loop 拡張（2026-04-24〜）:
  - keyword-only 引数で lgb_params / num_boost_round / early_stopping_rounds / sample_weight を注入可能に
  - 戻り値を dict 化: {"model_path": Path, "metrics": {...}, "best_iteration": int}
  - 既存呼び出し (train(X, y, version)) は後方互換のため Path を直接返す動作も維持するが、
    新規コードは戻り値を dict として扱うこと。内部では _train_impl に分離。

タスク 6-10-d 拡張（2026-04-25〜）:
  - lgb_params.objective="lambdarank" / "rank_xendcg" モードを追加
  - 既存 multiclass モードと共存。CLI / 設定で切替可能
  - lambdarank: race_id 順ソート + group 構築、relevance = 5 - y
  - 推論: booster.predict() (N,) → race-level softmax で 1 着確率 → (N, 6) ブロードキャスト
    → 0 列目に 1 着確率、1〜5 列目に (1 - p_first) / 5 を等分配置
  - per-class IsotonicRegression は 0 列目（1 着）が実質的に意味を持つ
  - engine.py は raw_probs[:, 0] のみ参照するため API 互換
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from sklearn.isotonic import IsotonicRegression

# ranking 系 objective（race_id ソート + group ベクトル必須）
RANKING_OBJECTIVES = {"lambdarank", "rank_xendcg"}

MODEL_DIR = Path(__file__).parents[3] / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)

LGB_PARAMS = {
    "objective": "multiclass",
    "num_class": 6,
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
    "n_jobs": -1,
}


def _softmax_normalize(probs: np.ndarray) -> np.ndarray:
    """行ごとに sum-to-1 正規化（各レースの6艇確率を合計1に揃える）"""
    row_sum = probs.sum(axis=1, keepdims=True)
    return probs / np.maximum(row_sum, 1e-9)


def _ece(prob: np.ndarray, true_bin: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error（簡易計算）"""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    n = len(prob)
    if n == 0:
        return float("nan")
    ece = 0.0
    for i in range(n_bins):
        mask = (prob >= bins[i]) & (prob < bins[i + 1])
        if mask.sum() == 0:
            continue
        ece += mask.sum() / n * abs(prob[mask].mean() - true_bin[mask].mean())
    return ece


def _build_groups(race_ids: pd.Series) -> np.ndarray:
    """
    race_id が連続塊になっている前提で group ベクトル（各 race の行数）を作る。
    呼び出し前に _sort_for_ranking で race_id 順に並べ替えていること。
    """
    counts: list[int] = []
    cur = None
    for r in race_ids.values:
        if r != cur:
            counts.append(1)
            cur = r
        else:
            counts[-1] += 1
    return np.array(counts, dtype=int)


def _sort_for_ranking(
    X: pd.DataFrame,
    y: pd.Series,
    race_ids: pd.Series,
    sample_weight: np.ndarray | None,
):
    """
    ranking 系 objective 用に race_id 順で並べ直す（同 race の行を連続させる）。
    元データが sort 済みでも非連続な race_id が混じる可能性に対する防御。
    sample_weight も同じ並びで返す（None なら None）。
    """
    order = np.argsort(race_ids.values, kind="stable")
    X_sorted = X.iloc[order].reset_index(drop=True)
    y_sorted = y.iloc[order].reset_index(drop=True)
    rid_sorted = race_ids.iloc[order].reset_index(drop=True)
    sw_sorted = sample_weight[order] if sample_weight is not None else None
    return X_sorted, y_sorted, rid_sorted, sw_sorted


def _race_softmax(score: np.ndarray, race_ids: np.ndarray) -> np.ndarray:
    """レース単位で score を softmax 正規化して 1 着確率（per-row）を返す。"""
    out = np.zeros_like(score, dtype=float)
    df = pd.DataFrame({"race_id": race_ids, "score": score})
    for _, idx in df.groupby("race_id", sort=False).groups.items():
        s = score[idx]
        s = s - s.max()  # 数値安定化
        e = np.exp(s)
        total = e.sum()
        out[idx] = (e / total) if total > 0 else (1.0 / len(s))
    return out


def _broadcast_first_to_six(p_first: np.ndarray) -> np.ndarray:
    """
    1 着確率 (N,) を (N, 6) に展開する。
    0 列目: 1 着確率、1〜5 列目: (1 - p_first) / 5 を等分配置。
    sum-to-1 を行ごとに維持し、後段の per-class IR + softmax 再正規化と互換にする。
    """
    n = len(p_first)
    out = np.zeros((n, 6), dtype=float)
    out[:, 0] = p_first
    rest = np.clip(1.0 - p_first, 0.0, 1.0) / 5.0
    out[:, 1:] = rest[:, None]
    return out


def _merge_lgb_params(overrides: dict | None) -> dict:
    """LGB_PARAMS をベースに overrides をマージ。overrides が None なら LGB_PARAMS をそのまま返す。"""
    merged = dict(LGB_PARAMS)
    if overrides:
        # objective/num_class/metric/n_jobs/verbose はベース側を尊重しつつ上書き可能
        for k, v in overrides.items():
            merged[k] = v
    return merged


def train(
    X: pd.DataFrame,
    y: pd.Series,
    version: str,
    *,
    lgb_params: dict | None = None,
    num_boost_round: int = 1000,
    early_stopping_rounds: int = 50,
    sample_weight: np.ndarray | None = None,
    race_ids: pd.Series | None = None,
    return_metrics: bool = False,
) -> Path | dict:
    """
    モデルを学習して artifacts/model_{version}.pkl に保存する。

    Session 6 変更:
      - 時系列 split（最後の 10% を val）
      - ソフトマックス正規化 + Isotonic Regression: raw probs → 正規化 → per-class IR → 再正規化
      - 保存形式: {"booster": lgb.Booster, "softmax_calibrators": list[IsotonicRegression]}

    Parameters
    ----------
    X : pd.DataFrame  特徴量 (FEATURE_COLUMNS)
    y : pd.Series     ラベル  着順 - 1  (0=1着, 1=2着, ..., 5=6着)
    version : str     バージョン文字列 (例: "202504")
    lgb_params : dict | None
        LGB_PARAMS にマージする上書きパラメータ。None なら既定のまま。
    num_boost_round : int
        最大ブースティングラウンド数（デフォルト 1000）
    early_stopping_rounds : int
        early stopping の我慢回数（デフォルト 50）
    sample_weight : np.ndarray | None
        学習サンプルの重み（X と同じ行数、train split 側のみが使われる）。
        None なら均等重み。
    race_ids : pd.Series | None
        ranking 系 objective（lambdarank / rank_xendcg）の場合に必須。
        X と同じ行数の race_id 列。multiclass / binary では使用しない。
    return_metrics : bool
        True の場合、dict を返す（model_path / metrics / best_iteration / params）。
        False（デフォルト）の場合、後方互換のため Path のみを返す。

    Returns
    -------
    Path または dict
        return_metrics=False: 保存されたモデルファイルのパス（後方互換）
        return_metrics=True:  {"model_path": Path, "metrics": {...}, "best_iteration": int, "params": dict}
    """
    params = _merge_lgb_params(lgb_params)
    objective = params.get("objective", "multiclass")
    is_ranking = objective in RANKING_OBJECTIVES

    if is_ranking and race_ids is None:
        raise ValueError(
            f"ranking objective '{objective}' requires race_ids (pd.Series, "
            f"same length as X)"
        )

    # --- 時系列 split: 最後の 10% を val ---
    n = len(X)
    n_val = max(int(n * 0.1), 1)
    X_train, X_val = X.iloc[:-n_val], X.iloc[-n_val:]
    y_train, y_val = y.iloc[:-n_val], y.iloc[-n_val:]

    # sample_weight の split（指定があれば）
    w_train = None
    if sample_weight is not None:
        sw = np.asarray(sample_weight)
        if len(sw) != n:
            raise ValueError(
                f"sample_weight length ({len(sw)}) must match X length ({n})"
            )
        w_train = sw[:-n_val]

    # race_ids の split（ranking 系のみ必要）
    rid_train = rid_val = None
    if is_ranking:
        if len(race_ids) != n:
            raise ValueError(
                f"race_ids length ({len(race_ids)}) must match X length ({n})"
            )
        rid_train = race_ids.iloc[:-n_val].reset_index(drop=True)
        rid_val = race_ids.iloc[-n_val:].reset_index(drop=True)

    print(f"Train: {len(X_train):,} samples  Val: {len(X_val):,} samples  (時系列 split)")
    if w_train is not None:
        print(f"  sample_weight: min={w_train.min():.3f} max={w_train.max():.3f} "
              f"mean={w_train.mean():.3f}")
    print(f"  objective={objective}  is_ranking={is_ranking}")

    if is_ranking:
        # ranking 系: race_id 順ソート + group + relevance ラベル化
        X_train, y_train, rid_train, w_train = _sort_for_ranking(
            X_train, y_train, rid_train, w_train
        )
        X_val, y_val, rid_val, _ = _sort_for_ranking(X_val, y_val, rid_val, None)

        # relevance = 5 - y (1着=5, 6着=0). label_gain と整合
        label_train = (5 - y_train.values.astype(int)).astype(int)
        label_val = (5 - y_val.values.astype(int)).astype(int)

        group_train = _build_groups(rid_train)
        group_val = _build_groups(rid_val)
        if group_train.sum() != len(X_train):
            raise RuntimeError("group_train sum mismatch")
        if group_val.sum() != len(X_val):
            raise RuntimeError("group_val sum mismatch")

        # ranking 系 default: label_gain と ndcg_eval_at を補完
        params.setdefault("label_gain", [0, 1, 3, 7, 15, 31])
        params.setdefault("ndcg_eval_at", [1, 3])
        # multiclass 由来の num_class / metric は ranking で不整合になるため除去
        params.pop("num_class", None)
        # metric が multi_logloss など multiclass 用の場合は ndcg に置き換え
        # （ユーザーが明示的に ndcg / map / mean_average_precision を指定した場合は尊重）
        m = params.get("metric")
        if m in (None, "multi_logloss", "multi_error"):
            params["metric"] = "ndcg"

        dtrain = lgb.Dataset(X_train, label=label_train, weight=w_train, group=group_train)
        dval = lgb.Dataset(X_val, label=label_val, group=group_val, reference=dtrain)
    else:
        dtrain = lgb.Dataset(X_train, label=y_train, weight=w_train)
        dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        valid_sets=[dval],
        callbacks=[
            lgb.early_stopping(stopping_rounds=early_stopping_rounds, verbose=True),
            lgb.log_evaluation(period=100),
        ],
    )

    # --- Session 6: ソフトマックス正規化 → Isotonic Regression ---
    y_val_arr = y_val.values.astype(int)

    if is_ranking:
        # ranking score (N,) → race-level softmax で 1 着確率 → (N, 6) ブロードキャスト
        scores = booster.predict(X_val.values)
        p_first = _race_softmax(scores, rid_val.values)
        raw_probs = _broadcast_first_to_six(p_first)
    else:
        raw_probs = booster.predict(X_val.values)       # (N_val, 6)

    # Step 1: レース内 sum-to-1 正規化
    normalized = _softmax_normalize(raw_probs)      # (N_val, 6)

    # Step 2: per-class Isotonic Regression（ビン別構造バイアスを補正）
    softmax_calibrators = []
    for k in range(6):
        true_k = (y_val_arr == k).astype(float)
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(normalized[:, k], true_k)
        softmax_calibrators.append(ir)

    # ECE 比較（1着クラス）
    true_1st   = (y_val_arr == 0).astype(float)
    ece_before = _ece(raw_probs[:, 0], true_1st)

    # calibrate → 再正規化 → 1着 ECE 計測
    cal_raw = np.stack(
        [softmax_calibrators[k].predict(normalized[:, k]) for k in range(6)], axis=1
    )
    cal_probs = _softmax_normalize(cal_raw)
    ece_after = _ece(cal_probs[:, 0], true_1st)

    print(f"  [Softmax + Isotonic Regression]")
    print(f"  [1着 ECE]  before={ece_before:.5f} → after={ece_after:.5f}")

    # --- 保存: {"booster": ..., "softmax_calibrators": [...]} ---
    model_pkg = {"booster": booster, "softmax_calibrators": softmax_calibrators}
    out_path = MODEL_DIR / f"model_{version}.pkl"
    joblib.dump(model_pkg, out_path)
    print(f"Model saved: {out_path}  (best iteration: {booster.best_iteration})")

    if return_metrics:
        return {
            "model_path": out_path,
            "metrics": {
                "ece_rank1_raw": float(ece_before),
                "ece_rank1_calibrated": float(ece_after),
                "n_train": int(len(X_train)),
                "n_val": int(len(X_val)),
            },
            "best_iteration": int(booster.best_iteration or 0),
            "params": params,
        }
    return out_path
