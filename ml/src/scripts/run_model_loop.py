"""
モデル構造自律改善ループ ランナー（MODEL_LOOP_PLAN タスク 3）

trials/pending/*.yaml を順に実行し、Walk-Forward バックテストを回して
trials/results.jsonl に KPI を追記、YAML を trials/completed/ へ移動する。

使い方:
  # pending にある全 trial を順次実行
  python ml/src/scripts/run_model_loop.py

  # 特定の trial だけ実行
  python ml/src/scripts/run_model_loop.py --trial T01_window_2024

  # 全 trial 実行（--all は省略時の既定）
  python ml/src/scripts/run_model_loop.py --all

設計書: MODEL_LOOP_PLAN.md §3（アーキテクチャ）, §4 タスク 3
"""
from __future__ import annotations

import argparse
import calendar
import json
import logging
import math
import random
import shutil
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.odds_downloader import (
    load_or_download_month_odds,
    load_or_download_month_trio_odds,
)
from backtest.engine import run_backtest_batch

# 同じ scripts パッケージ内の run_walkforward をインポート
sys.path.insert(0, str(Path(__file__).parent))
import run_walkforward  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[3]
TRIALS_DIR = ROOT / "trials"
PENDING_DIR = TRIALS_DIR / "pending"
COMPLETED_DIR = TRIALS_DIR / "completed"
RESULTS_FILE = TRIALS_DIR / "results.jsonl"
ARTIFACTS_DIR = ROOT / "artifacts"


# ---------------------------------------------------------------------------
# YAML スキーマ検証
# ---------------------------------------------------------------------------

REQUIRED_TOP_KEYS = ["trial_id", "walkforward", "strategy"]
REQUIRED_WALKFORWARD_KEYS = ["start", "end"]
REQUIRED_STRATEGY_KEYS = ["prob_threshold", "ev_threshold", "bet_amount"]


def load_trial_yaml(path: Path) -> dict:
    """trial YAML を読み込み、必須キーを検証する。"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: YAML ルートは mapping でなければなりません")
    validate_trial_schema(data, path)
    return data


def validate_trial_schema(data: dict, path: Path | None = None) -> None:
    """trial YAML の必須キーを検証。欠落していれば ValueError。"""
    ctx = f"{path}: " if path else ""
    for key in REQUIRED_TOP_KEYS:
        if key not in data:
            raise ValueError(f"{ctx}必須キー '{key}' が欠落しています")
    wf = data["walkforward"]
    if not isinstance(wf, dict):
        raise ValueError(f"{ctx}'walkforward' は mapping でなければなりません")
    for key in REQUIRED_WALKFORWARD_KEYS:
        if key not in wf:
            raise ValueError(f"{ctx}必須キー 'walkforward.{key}' が欠落しています")
    strat = data["strategy"]
    if not isinstance(strat, dict):
        raise ValueError(f"{ctx}'strategy' は mapping でなければなりません")
    for key in REQUIRED_STRATEGY_KEYS:
        if key not in strat:
            raise ValueError(f"{ctx}必須キー 'strategy.{key}' が欠落しています")


# ---------------------------------------------------------------------------
# KPI 計算 / スコア / verdict
# ---------------------------------------------------------------------------

def compute_kpi(all_results: pd.DataFrame, monthly_rows: list[dict]) -> dict:
    """
    Walk-Forward 結果 DataFrame と月別集計から KPI を算出する。

    monthly_rows: run_walkforward.py と同じ形式
      [{"month": "YYYY-MM", "wagered", "payout", "n_bets", "wins"}, ...]
    """
    total_bets = int(all_results["bets_placed"].sum()) if len(all_results) else 0
    total_wagered = float(all_results["amount_wagered"].sum()) if len(all_results) else 0.0
    total_payout = float(all_results["payout_received"].sum()) if len(all_results) else 0.0
    wins = int(all_results["matched"].sum()) if len(all_results) else 0

    roi_total = (
        (total_payout / total_wagered - 1) * 100 if total_wagered > 0 else 0.0
    )
    hit_rate_per_bet = wins / total_bets if total_bets > 0 else 0.0

    matched = all_results[all_results["matched"]] if len(all_results) else all_results
    avg_hit_odds = float(matched["matched_odds"].mean()) if len(matched) > 0 else 0.0

    # 月次 ROI
    monthly_roi: dict[str, float] = {}
    for row in monthly_rows:
        w = row["wagered"]
        p = row["payout"]
        roi_m = (p / w - 1) * 100 if w > 0 else 0.0
        monthly_roi[row["month"]] = round(roi_m, 2)

    total_months = len(monthly_roi)
    plus_months = sum(1 for v in monthly_roi.values() if v > 0)
    plus_month_ratio = plus_months / total_months if total_months > 0 else 0.0

    if monthly_roi:
        worst_month_roi = min(monthly_roi.values())
        best_month_roi = max(monthly_roi.values())
    else:
        worst_month_roi = 0.0
        best_month_roi = 0.0

    # broken_months: -50% を下回った月数（離散カウント。単月事故の二重罰を避ける）
    broken_months = sum(1 for v in monthly_roi.values() if v < -50.0)

    # CVaR20: 下位 20% の月次 ROI 平均（最低 1 月）。裾の「平均」なので
    # 単月 min と違い 2〜3 月分の情報を使う。月数 < 5 の smoke ランでも最低 1 月で動く。
    if monthly_roi:
        sorted_vals = sorted(monthly_roi.values())
        k = max(1, math.ceil(0.20 * total_months))
        cvar20 = sum(sorted_vals[:k]) / k
    else:
        cvar20 = 0.0

    return {
        "total_bets": total_bets,
        "total_wagered": total_wagered,
        "total_payout": total_payout,
        "wins": wins,
        "roi_total": round(roi_total, 2),
        "worst_month_roi": round(worst_month_roi, 2),
        "best_month_roi": round(best_month_roi, 2),
        "plus_months": plus_months,
        "total_months": total_months,
        "plus_month_ratio": round(plus_month_ratio, 4),
        "broken_months": broken_months,
        "cvar20_month_roi": round(cvar20, 2),
        "avg_hit_odds": round(avg_hit_odds, 2),
        "hit_rate_per_bet": round(hit_rate_per_bet, 6),
    }


def block_bootstrap_roi_ci(
    monthly_rows: list[dict],
    block_length: int = 3,
    n_resamples: int = 2000,
    ci_level: float = 0.90,
    seed: int = 0,
) -> dict:
    """
    月次 (wagered, payout) を block bootstrap で再サンプリングし、
    通算 ROI の信頼区間を返す。

    retrain 周期 3 ヶ月を念頭にブロック長 3 を既定値とする（独立仮定の破れを緩和）。
    seed 固定で決定論的。月数 < block_length*2 の場合はブロック長を自動縮小する。

    Parameters
    ----------
    monthly_rows : list[dict]
        compute_kpi と同じ形式。{"month", "wagered", "payout", ...}
    block_length : int
        ブロック長（既定 3 = 再学習間隔）
    n_resamples : int
        ブートストラップ反復数
    ci_level : float
        片側信頼水準（既定 0.90 → 5% / 95% パーセンタイル）
    seed : int

    Returns
    -------
    dict : {"roi_ci_low", "roi_ci_high", "n_resamples", "block_length"}
        月数 0 の場合は low=high=0.0。
    """
    n = len(monthly_rows)
    if n == 0:
        return {
            "roi_ci_low": 0.0,
            "roi_ci_high": 0.0,
            "n_resamples": 0,
            "block_length": block_length,
        }

    # ブロック長はサンプル月数を超えないように調整
    bl = max(1, min(block_length, n))
    n_blocks = math.ceil(n / bl)

    wagered = [float(r["wagered"]) for r in monthly_rows]
    payout = [float(r["payout"]) for r in monthly_rows]

    rng = random.Random(seed)
    rois: list[float] = []
    for _ in range(n_resamples):
        # circular block bootstrap: 開始位置を n 個からランダム選択、n 月分に切り詰め
        w_sum = 0.0
        p_sum = 0.0
        collected = 0
        for _b in range(n_blocks):
            start = rng.randrange(n)
            for k in range(bl):
                if collected >= n:
                    break
                idx = (start + k) % n
                w_sum += wagered[idx]
                p_sum += payout[idx]
                collected += 1
            if collected >= n:
                break
        if w_sum > 0:
            rois.append((p_sum / w_sum - 1.0) * 100.0)
        else:
            rois.append(0.0)

    rois.sort()
    alpha = (1.0 - ci_level) / 2.0
    lo_idx = max(0, int(math.floor(alpha * n_resamples)))
    hi_idx = min(n_resamples - 1, int(math.ceil((1.0 - alpha) * n_resamples)) - 1)
    return {
        "roi_ci_low": round(rois[lo_idx], 2),
        "roi_ci_high": round(rois[hi_idx], 2),
        "n_resamples": n_resamples,
        "block_length": bl,
    }


def primary_score(kpi: dict) -> float:
    """
    CVaR20 ベースの複合スコア（高いほど良い）。

    定義:
        primary_score = roi_total + 0.5 * cvar20 - 10 * broken_months

    設計意図:
      - 旧式の `roi - 2*max(0, -50-worst)` は worst_month が単月事故で
        振れると primary_score も大きく動き、さらに roi_total と二重に
        worst 月を参照する非対称性があった（レビュー 2026-04-24 指摘）。
      - 新定義では裾の指標を「CVaR20（下位20%月の平均）」に置き換え、
        -50% 超過は離散カウント（broken_months）× 係数 10 で階段状に罰則。
      - 月次事故が 1 件あっても -10 のペナルティで済み、他 11 ヶ月の
        実績が見える。2 件超でも線形にしか増えない。
    """
    roi = kpi.get("roi_total", 0.0)
    cvar20 = kpi.get("cvar20_month_roi", 0.0)
    broken = kpi.get("broken_months", 0)
    return round(roi + 0.5 * cvar20 - 10.0 * broken, 2)


# verdict 判定の閾値（CLAUDE.md「現行の運用方針」実運用再開条件と整合）
PASS_ROI_MIN = 10.0         # 通算 ROI ≥ +10%
PASS_PLUS_RATIO_MIN = 0.60  # プラス月比率 ≥ 60%
PASS_BROKEN_MAX = 0         # 破局月 0 本（worst > -50% と等価）
PASS_CI_LOW_MIN = 0.0       # bootstrap CI 下限 ≥ 0


def classify_verdict(kpi: dict) -> str:
    """
    合否判定: pass / marginal / fail。

    pass 必要条件（すべて満たすこと）:
      - roi_total ≥ +10%           … CLAUDE.md 実運用再開条件
      - broken_months == 0          … worst_month_roi > -50% と等価
      - plus_month_ratio ≥ 0.60
      - roi_ci_low_90 ≥ 0           … block bootstrap 下限（偶発採択ガード）
        ※ `roi_ci_low_90` が kpi に無い場合はチェックをスキップ（互換）

    marginal: roi_total ≥ 0（pass は満たさないが、通算は黒字）
    fail: それ以外
    """
    roi = kpi.get("roi_total", 0.0)
    plus_ratio = kpi.get("plus_month_ratio", 0.0)
    broken = kpi.get("broken_months", None)
    ci_low = kpi.get("roi_ci_low_90", None)

    # broken_months が無い旧 KPI では worst_month_roi から導出
    if broken is None:
        worst = kpi.get("worst_month_roi", 0.0)
        broken = 1 if worst < -50.0 else 0

    pass_ok = (
        roi >= PASS_ROI_MIN
        and broken <= PASS_BROKEN_MAX
        and plus_ratio >= PASS_PLUS_RATIO_MIN
        and (ci_low is None or ci_low >= PASS_CI_LOW_MIN)
    )
    if pass_ok:
        return "pass"
    if roi >= 0:
        return "marginal"
    return "fail"


# ---------------------------------------------------------------------------
# trial モデル永続化
# ---------------------------------------------------------------------------

def _copy_trial_model(
    train_result: dict,
    trial_id: str,
    test_year: int,
    test_month: int,
) -> Path | None:
    """
    retrain 直後の model_path を trial_id を含む名前で artifacts/ にコピーする。

    共有ファイル（model_<train_end>_from<train_start>_wf.pkl）は同じ train_start を
    使う別 trial の retrain で上書きされるため、trial_id 付きコピーを残しておく。
    これにより後から /trial-design 等で個別 trial のモデルを再参照できる。

    命名: artifacts/model_loop_<trial_id>_<test_year><test_month>.pkl
    （test_year/month はそのモデルを使うテスト月を示す。学習末尾月はその前月）

    Parameters
    ----------
    train_result : dict
        trainer.train(return_metrics=True) または
        get_model_for_month(return_metrics=True) が返す dict。"model_path" キー必須。
    trial_id : str
    test_year, test_month : int
        この retrain で作ったモデルを適用するテスト月。

    Returns
    -------
    Path | None
        コピー先のパス。model_path が取れない場合は None。
    """
    if not isinstance(train_result, dict):
        return None
    src = train_result.get("model_path")
    if src is None:
        return None
    src_path = Path(src)
    if not src_path.exists():
        logger.warning(
            "[%s] model_path %s が見つからず、trial コピーをスキップ",
            trial_id, src_path,
        )
        return None
    dst = ARTIFACTS_DIR / f"model_loop_{trial_id}_{test_year}{test_month:02d}.pkl"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dst)
    logger.info("[%s] trial モデルを保存: %s", trial_id, dst.name)
    return dst


# ---------------------------------------------------------------------------
# Walk-Forward 実行
# ---------------------------------------------------------------------------

@dataclass
class TrialRunResult:
    kpi: dict
    monthly_roi: dict[str, float]
    monthly_rows: list[dict]  # block bootstrap 再計算のために生の月次集計を保持
    model_metrics: dict | None  # trainer.train の return_metrics dict（最後の学習月分）
    csv_path: Path


def run_trial_walkforward(trial: dict, trial_id: str) -> TrialRunResult:
    """
    1 trial の Walk-Forward を実行し、集計結果を返す。

    設計書 §4 タスク 3: run_walkforward.main() をコピーせず、
    ライブラリ関数 `get_model_for_month` + `run_backtest_batch` を直接組み立てる。
    """
    wf_cfg = trial["walkforward"]
    start_year, start_month = run_walkforward.parse_ym(wf_cfg["start"])
    end_year, end_month = run_walkforward.parse_ym(wf_cfg["end"])
    retrain_interval = int(wf_cfg.get("retrain_interval", 1))
    real_odds = bool(wf_cfg.get("real_odds", True))

    training_cfg = trial.get("training") or {}
    train_start_year = int(training_cfg.get("train_start_year", 2023))
    train_start_month = int(training_cfg.get("train_start_month", 1))

    strat = trial["strategy"]
    prob_threshold = float(strat["prob_threshold"])
    ev_threshold = float(strat["ev_threshold"])
    bet_amount = int(strat["bet_amount"])
    max_bets = int(strat.get("max_bets", 5))
    min_odds = strat.get("min_odds")
    exclude_courses = strat.get("exclude_courses") or None
    exclude_stadiums = strat.get("exclude_stadiums") or None
    bet_type = strat.get("bet_type", "trifecta")

    # trial_config を get_model_for_month に注入
    trial_config_for_train = {
        "lgb_params": trial.get("lgb_params"),
        "training": {
            "sample_weight": training_cfg.get("sample_weight"),
            "num_boost_round": training_cfg.get("num_boost_round", 1000),
            "early_stopping_rounds": training_cfg.get("early_stopping_rounds", 50),
        },
    }

    months = list(
        run_walkforward.month_range(start_year, start_month, end_year, end_month)
    )
    logger.info(
        "[%s] Walk-Forward: %s 〜 %s (%d ヶ月, retrain_interval=%d, real_odds=%s)",
        trial_id, wf_cfg["start"], wf_cfg["end"], len(months),
        retrain_interval, real_odds,
    )

    all_frames: list[pd.DataFrame] = []
    monthly_rows: list[dict] = []
    cached_model = None
    last_metrics: dict | None = None

    for i, (test_year, test_month) in enumerate(months):
        logger.info("[%s] ── %d-%02d 開始 ──", trial_id, test_year, test_month)

        should_retrain = (i % retrain_interval == 0)
        if should_retrain:
            model, train_result = run_walkforward.get_model_for_month(
                test_year, test_month,
                retrain=True,
                train_start_year=train_start_year,
                train_start_month=train_start_month,
                trial_config=trial_config_for_train,
                return_metrics=True,
            )
            if isinstance(train_result, dict) and "metrics" in train_result:
                last_metrics = train_result
            # trial 固有の永続コピーを保存（MODEL_LOOP_PLAN §3-1 準拠）
            # 共有ファイル model_<train_end>_from<train_start>_wf.pkl は後続 trial に
            # 上書きされるため、trial_id を含む名前で別コピーを残す。
            _copy_trial_model(train_result, trial_id, test_year, test_month)
        else:
            model = run_walkforward.get_model_for_month(
                test_year, test_month,
                retrain=False,
                train_start_year=train_start_year,
                train_start_month=train_start_month,
                cached_model=cached_model,
            )
        cached_model = model

        df_test = run_walkforward.load_month_data(test_year, test_month)
        if df_test.empty:
            logger.warning("[%s] %d-%02d: データなし、スキップ", trial_id, test_year, test_month)
            continue

        odds_by_race: dict[str, dict[str, float]] = {}
        if real_odds:
            if bet_type == "trio":
                odds_by_race = load_or_download_month_trio_odds(test_year, test_month, df_test)
            else:
                odds_by_race = load_or_download_month_odds(test_year, test_month, df_test)
            logger.info("[%s] 実オッズ: %d レース分取得", trial_id, len(odds_by_race))

        results, skipped = run_backtest_batch(
            df_test=df_test,
            model=model,
            odds_by_race=odds_by_race,
            prob_threshold=prob_threshold,
            bet_amount=bet_amount,
            max_bets_per_race=max_bets,
            ev_threshold=ev_threshold,
            exclude_courses=exclude_courses,
            min_odds=min_odds,
            exclude_stadiums=exclude_stadiums,
            bet_type=bet_type,
        )
        logger.info(
            "[%s] %d-%02d 完了 レース=%d スキップ=%d",
            trial_id, test_year, test_month, len(results), skipped,
        )
        if not results:
            continue

        df_month = pd.DataFrame(results)
        all_frames.append(df_month)
        monthly_rows.append({
            "month": f"{test_year}-{test_month:02d}",
            "wagered": float(df_month["amount_wagered"].sum()),
            "payout": float(df_month["payout_received"].sum()),
            "n_bets": int(df_month["bets_placed"].sum()),
            "wins": int(df_month["matched"].sum()),
        })

    if not all_frames:
        raise RuntimeError(f"[{trial_id}] 全月でデータが取得できませんでした")

    all_results = pd.concat(all_frames, ignore_index=True).sort_values(
        ["race_date", "race_id"]
    )

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    csv_path = ARTIFACTS_DIR / f"walkforward_{trial_id}.csv"
    all_results.to_csv(csv_path, index=False)
    logger.info("[%s] 結果 CSV: %s", trial_id, csv_path)

    kpi = compute_kpi(all_results, monthly_rows)
    monthly_roi = {row["month"]:
                   round((row["payout"] / row["wagered"] - 1) * 100, 2)
                   if row["wagered"] > 0 else 0.0
                   for row in monthly_rows}

    return TrialRunResult(
        kpi=kpi,
        monthly_roi=monthly_roi,
        monthly_rows=monthly_rows,
        model_metrics=last_metrics,
        csv_path=csv_path,
    )


# ---------------------------------------------------------------------------
# results.jsonl 出力
# ---------------------------------------------------------------------------

def write_results_line(record: dict) -> None:
    """results.jsonl に 1 行追記する（存在しなければディレクトリごと作成）。"""
    TRIALS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_success_record(
    trial_id: str,
    started_at: datetime,
    finished_at: datetime,
    run_result: TrialRunResult,
    trial: dict,
) -> dict:
    kpi = dict(run_result.kpi)
    if run_result.model_metrics and "metrics" in run_result.model_metrics:
        ece = run_result.model_metrics["metrics"].get("ece_rank1_calibrated")
        if ece is not None:
            kpi["ece_rank1_calibrated"] = round(float(ece), 6)

    # block bootstrap で通算 ROI の 90% CI を算出し、verdict 必要条件に使う。
    # ブロック長 3 = retrain 周期（MODEL_LOOP_PLAN §3-2）。
    ci = block_bootstrap_roi_ci(
        run_result.monthly_rows,
        block_length=3,
        n_resamples=2000,
        ci_level=0.90,
        seed=0,
    )
    kpi["roi_ci_low_90"] = ci["roi_ci_low"]
    kpi["roi_ci_high_90"] = ci["roi_ci_high"]

    summary_path = ARTIFACTS_DIR / f"walkforward_{trial_id}_summary.json"
    summary = {
        "trial_id": trial_id,
        "kpi": kpi,
        "monthly_roi": run_result.monthly_roi,
        "primary_score": primary_score(kpi),
        "verdict": classify_verdict(kpi),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return {
        "trial_id": trial_id,
        "description": trial.get("description", ""),
        "started_at": started_at.astimezone().isoformat(),
        "finished_at": finished_at.astimezone().isoformat(),
        "duration_sec": int((finished_at - started_at).total_seconds()),
        "status": "success",
        "kpi": kpi,
        "monthly_roi": run_result.monthly_roi,
        "primary_score": primary_score(kpi),
        "verdict": classify_verdict(kpi),
        "csv_path": str(run_result.csv_path.relative_to(ROOT))
                    if run_result.csv_path.is_relative_to(ROOT)
                    else str(run_result.csv_path),
    }


def build_error_record(
    trial_id: str,
    started_at: datetime,
    finished_at: datetime,
    error: Exception,
    trial: dict | None,
) -> dict:
    return {
        "trial_id": trial_id,
        "description": (trial or {}).get("description", ""),
        "started_at": started_at.astimezone().isoformat(),
        "finished_at": finished_at.astimezone().isoformat(),
        "duration_sec": int((finished_at - started_at).total_seconds()),
        "status": "error",
        "error_type": type(error).__name__,
        "error_message": str(error),
    }


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def discover_pending_trials(specific_id: str | None = None) -> list[Path]:
    """trials/pending/*.yaml を列挙して返す。specific_id 指定時はその 1 本のみ。"""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    if specific_id:
        candidates = list(PENDING_DIR.glob(f"{specific_id}.yaml")) + \
                     list(PENDING_DIR.glob(f"{specific_id}.yml"))
        if not candidates:
            raise FileNotFoundError(
                f"trial '{specific_id}' が {PENDING_DIR} に見つかりません"
            )
        return sorted(candidates)
    return sorted(
        list(PENDING_DIR.glob("*.yaml")) + list(PENDING_DIR.glob("*.yml"))
    )


def execute_trial_file(yaml_path: Path) -> dict:
    """
    1 本の trial YAML を実行し、results.jsonl に 1 行追記。
    成功時は pending → completed に YAML を移動する。
    失敗時は YAML は pending のまま残す（再実行可能）。

    Returns
    -------
    dict : results.jsonl に書き出した記録
    """
    trial_id = yaml_path.stem
    started_at = datetime.now(timezone.utc)
    trial: dict | None = None

    try:
        trial = load_trial_yaml(yaml_path)
        trial_id = trial.get("trial_id", trial_id)  # YAML 内の trial_id を優先
        run_result = run_trial_walkforward(trial, trial_id)
        finished_at = datetime.now(timezone.utc)
        record = build_success_record(
            trial_id, started_at, finished_at, run_result, trial,
        )
        write_results_line(record)
        # 成功時のみ completed に移動
        COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
        dest = COMPLETED_DIR / yaml_path.name
        shutil.move(str(yaml_path), str(dest))
        logger.info("[%s] ✅ 完了 → %s", trial_id, dest)
        logger.info(
            "[%s] ROI=%.1f%% worst=%.1f%% primary=%.1f verdict=%s",
            trial_id,
            record["kpi"]["roi_total"],
            record["kpi"]["worst_month_roi"],
            record["primary_score"],
            record["verdict"],
        )
        return record
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        record = build_error_record(trial_id, started_at, finished_at, exc, trial)
        write_results_line(record)
        # エラーログ
        log_path = ARTIFACTS_DIR / f"model_loop_{trial_id}_error.log"
        ARTIFACTS_DIR.mkdir(exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"trial_id: {trial_id}\n")
            f.write(f"yaml_path: {yaml_path}\n")
            f.write(f"error: {type(exc).__name__}: {exc}\n\n")
            f.write(traceback.format_exc())
        logger.error("[%s] ❌ 失敗: %s (log: %s)", trial_id, exc, log_path)
        return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="モデル構造自律改善ループのランナー（trials/pending/ を順に実行）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--trial", type=str, default=None,
                        help="特定の trial_id のみ実行（省略時は pending 全て）")
    parser.add_argument("--all", action="store_true",
                        help="pending 全てを実行（既定、--trial と同時指定不可）")
    args = parser.parse_args()

    if args.trial and args.all:
        parser.error("--trial と --all は同時に指定できません")

    try:
        pending = discover_pending_trials(args.trial)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    if not pending:
        logger.info("pending trial なし（%s）", PENDING_DIR)
        return

    logger.info("pending trial: %d 本", len(pending))
    records: list[dict] = []
    for yaml_path in pending:
        logger.info("=" * 62)
        logger.info("  実行: %s", yaml_path.name)
        logger.info("=" * 62)
        record = execute_trial_file(yaml_path)
        records.append(record)

    # サマリー表示
    logger.info("=" * 62)
    logger.info("  全 trial 完了 サマリー")
    logger.info("=" * 62)
    for r in records:
        if r["status"] == "success":
            logger.info(
                "  [%s] %s  ROI=%.1f%% worst=%.1f%% primary=%.1f verdict=%s",
                r["trial_id"], r["status"],
                r["kpi"]["roi_total"], r["kpi"]["worst_month_roi"],
                r["primary_score"], r["verdict"],
            )
        else:
            logger.info("  [%s] %s  error=%s",
                        r["trial_id"], r["status"],
                        r.get("error_type", "?"))


if __name__ == "__main__":
    main()
