"""
Perfect-Oracle Upper Bound 計算（T16 reference, MODEL_LOOP §5「ツリー外撤退確証」枠）

「現行 strategy 下で達成可能な ROI の理論上限」を求める。
モデルが完全正解（actual 1-2-3 trifecta に確率 1.0）した場合の ROI を、
T07/T13 と完全に同じ Walk-Forward 期間 + strategy で算出する。

設計:
- /model-loop の trial 出力フォーマットに完全準拠
  (artifacts/walkforward_T16_*_summary.json + CSV + trials/results.jsonl 追記)
- 既存 trainer.py / predictor.py / engine.py には触らない
- KPI / verdict / block bootstrap CI は run_model_loop の関数を直接借用

オラクルの動作:
- 各 eligible race（場除外通過・6 艇全揃い・DNF なし）で actual 1-2-3 trifecta オッズを取得
- odds ≥ min_odds なら 100 円ベット（1 点のみ）、payout = odds × 100
- odds < min_odds なら未ベット（race 行は記録）
- prob/EV フィルタは prob=1.0 で常に通過するため無視

期待される効用:
- ROI が +10% 大幅超過 → strategy 自体の天井は高く、モデル側にまだ伸び代あり
- ROI が +10% 近辺/未達 → strategy（min_odds 100x 等）が天井で、モデル改善では届かない
  → フェーズ 6 完全撤退 + 馬券種転換 (B-3) 路線の正当性が補強される
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.odds_downloader import load_or_download_month_odds
from backtest.engine import get_actual_combo
from backtest.odds_simulator import SYNTHETIC_ODDS

sys.path.insert(0, str(Path(__file__).parent))
import run_walkforward  # noqa: E402
import run_model_loop  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[3]
ARTIFACTS_DIR = ROOT / "artifacts"


def run_oracle_month(
    test_year: int,
    test_month: int,
    *,
    real_odds: bool,
    min_odds: float | None,
    exclude_stadiums: list[int] | None,
    bet_amount: int,
    bet_type: str = "trifecta",
) -> tuple[pd.DataFrame, dict]:
    """1 月分のオラクル backtest を実行し、結果 DataFrame と月次集計を返す。"""
    df = run_walkforward.load_month_data(test_year, test_month)
    if df.empty:
        return pd.DataFrame(), {
            "month": f"{test_year}-{test_month:02d}",
            "wagered": 0.0, "payout": 0.0, "n_bets": 0, "wins": 0,
        }

    odds_by_race: dict[str, dict[str, float]] = {}
    if real_odds:
        odds_by_race = load_or_download_month_odds(test_year, test_month, df)
        logger.info("[oracle] %d-%02d 実オッズ: %d レース分", test_year, test_month, len(odds_by_race))

    excluded = set(exclude_stadiums or [])
    rows: list[dict] = []
    skipped = 0

    for race_id, race_group in df.groupby("race_id"):
        if len(race_group) != 6:
            skipped += 1
            continue
        sid = (
            int(race_group["stadium_id"].iloc[0])
            if "stadium_id" in race_group.columns else None
        )
        if sid is not None and sid in excluded:
            skipped += 1
            continue
        actual_combo = get_actual_combo(race_group)
        if actual_combo is None:
            skipped += 1
            continue

        race_odds = odds_by_race.get(str(race_id))
        # engine.py と同じフォールバック判定（60 組未満は synthetic 使用）
        use_real_odds = race_odds is not None and len(race_odds) >= 60
        effective_odds = race_odds if use_real_odds else SYNTHETIC_ODDS

        odds_value = float(effective_odds.get(actual_combo, 0.0))

        if min_odds is not None and odds_value < min_odds:
            bets_placed = 0
            amount_wagered = 0.0
            payout_received = 0.0
            matched = False
            matched_combo: str | None = None
            matched_odds = 0.0
        else:
            bets_placed = 1
            amount_wagered = float(bet_amount)
            payout_received = odds_value * bet_amount
            matched = True
            matched_combo = actual_combo
            matched_odds = odds_value

        rows.append({
            "race_id": str(race_id),
            "race_date": str(race_group["race_date"].iloc[0]),
            "stadium_id": sid,
            "actual_combo": actual_combo,
            "bets_placed": bets_placed,
            "amount_wagered": amount_wagered,
            "payout_received": payout_received,
            "profit": payout_received - amount_wagered,
            "matched": matched,
            "matched_combo": matched_combo,
            "matched_ev": odds_value if matched else 0.0,  # EV = 1.0 × odds
            "matched_odds": matched_odds,
            "top_ev": odds_value,
            "top_combo": actual_combo,
            "top_prob": 1.0,
            "n_alerts": bets_placed,
            "odds_source": "real" if use_real_odds else "synthetic",
            "bet_type": bet_type,
        })

    df_month = pd.DataFrame(rows)
    monthly = {
        "month": f"{test_year}-{test_month:02d}",
        "wagered": float(df_month["amount_wagered"].sum()) if len(df_month) else 0.0,
        "payout": float(df_month["payout_received"].sum()) if len(df_month) else 0.0,
        "n_bets": int(df_month["bets_placed"].sum()) if len(df_month) else 0,
        "wins": int(df_month["matched"].sum()) if len(df_month) else 0,
    }
    logger.info(
        "[oracle] %d-%02d 完了: races=%d skipped=%d bets=%d wins=%d ROI=%+.2f%%",
        test_year, test_month, len(rows), skipped,
        monthly["n_bets"], monthly["wins"],
        (monthly["payout"] / monthly["wagered"] - 1) * 100 if monthly["wagered"] > 0 else 0.0,
    )
    return df_month, monthly


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Perfect-Oracle Upper Bound 計算 (T16 reference)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", type=str, default="2025-05", help="開始月 YYYY-MM")
    parser.add_argument("--end", type=str, default="2026-04", help="終了月 YYYY-MM")
    parser.add_argument("--min-odds", type=float, default=100.0)
    parser.add_argument("--bet-amount", type=int, default=100)
    parser.add_argument(
        "--exclude-stadiums", type=int, nargs="+",
        default=[2, 3, 4, 9, 11, 14, 16, 17, 21, 23],
    )
    parser.add_argument("--no-real-odds", action="store_true",
                        help="合成オッズで実行（smoke 用）")
    parser.add_argument("--trial-id", type=str, default="T16_oracle_upper_bound")
    parser.add_argument("--no-append-results", action="store_true",
                        help="trials/results.jsonl に追記しない（smoke 用）")
    args = parser.parse_args()

    real_odds = not args.no_real_odds
    start_year, start_month = run_walkforward.parse_ym(args.start)
    end_year, end_month = run_walkforward.parse_ym(args.end)
    months = list(run_walkforward.month_range(start_year, start_month, end_year, end_month))

    started_at = datetime.now(timezone.utc)
    logger.info("=" * 62)
    logger.info("  Perfect-Oracle Upper Bound - %s", args.trial_id)
    logger.info("=" * 62)
    logger.info("  期間: %s 〜 %s (%d ヶ月)", args.start, args.end, len(months))
    logger.info("  min_odds: %s, bet_amount: %d 円", args.min_odds, args.bet_amount)
    logger.info("  exclude_stadiums: %s", args.exclude_stadiums)
    logger.info("  real_odds: %s", real_odds)

    all_frames: list[pd.DataFrame] = []
    monthly_rows: list[dict] = []

    for test_year, test_month in months:
        df_month, monthly = run_oracle_month(
            test_year, test_month,
            real_odds=real_odds,
            min_odds=args.min_odds,
            exclude_stadiums=args.exclude_stadiums,
            bet_amount=args.bet_amount,
        )
        if not df_month.empty:
            all_frames.append(df_month)
        monthly_rows.append(monthly)

    finished_at = datetime.now(timezone.utc)

    if not all_frames:
        logger.error("全月でデータが取得できませんでした")
        sys.exit(1)

    all_results = pd.concat(all_frames, ignore_index=True).sort_values(
        ["race_date", "race_id"]
    )

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    csv_path = ARTIFACTS_DIR / f"walkforward_{args.trial_id}.csv"
    all_results.to_csv(csv_path, index=False)
    logger.info("CSV: %s", csv_path)

    kpi = run_model_loop.compute_kpi(all_results, monthly_rows)
    ci = run_model_loop.block_bootstrap_roi_ci(
        monthly_rows, block_length=3, n_resamples=2000, ci_level=0.90, seed=0,
    )
    kpi["roi_ci_low_90"] = ci["roi_ci_low"]
    kpi["roi_ci_high_90"] = ci["roi_ci_high"]

    monthly_roi = {
        row["month"]: round((row["payout"] / row["wagered"] - 1) * 100, 2)
                       if row["wagered"] > 0 else 0.0
        for row in monthly_rows
    }

    summary = {
        "trial_id": args.trial_id,
        "kpi": kpi,
        "monthly_roi": monthly_roi,
        "primary_score": run_model_loop.primary_score(kpi),
        "verdict": run_model_loop.classify_verdict(kpi),
    }
    summary_path = ARTIFACTS_DIR / f"walkforward_{args.trial_id}_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info("Summary: %s", summary_path)

    if not args.no_append_results:
        record = {
            "trial_id": args.trial_id,
            "description": "Perfect-Oracle Upper Bound (actual 1-2-3 trifecta に確率 1.0)",
            "started_at": started_at.astimezone().isoformat(),
            "finished_at": finished_at.astimezone().isoformat(),
            "duration_sec": int((finished_at - started_at).total_seconds()),
            "status": "success",
            "kpi": kpi,
            "monthly_roi": monthly_roi,
            "primary_score": run_model_loop.primary_score(kpi),
            "verdict": run_model_loop.classify_verdict(kpi),
            "csv_path": str(csv_path.relative_to(ROOT))
                         if csv_path.is_relative_to(ROOT) else str(csv_path),
        }
        run_model_loop.write_results_line(record)
        logger.info("results.jsonl 追記: %s", run_model_loop.RESULTS_FILE)

    print()
    print("=" * 62)
    print(f"  Oracle Upper Bound - {args.trial_id}")
    print("=" * 62)
    print(f"  期間            : {args.start} 〜 {args.end}")
    print(f"  対象 race 数    : {len(all_results):,}")
    print(f"  ベット数        : {kpi['total_bets']:,}")
    print(f"  投資 (JPY)      : {kpi['total_wagered']:>14,.0f}")
    print(f"  払戻 (JPY)      : {kpi['total_payout']:>14,.0f}")
    print(f"  ROI             : {kpi['roi_total']:>+8.2f}%")
    print(f"  worst month     : {kpi['worst_month_roi']:>+8.2f}%")
    print(f"  best  month     : {kpi['best_month_roi']:>+8.2f}%")
    print(f"  plus_month_ratio: {kpi['plus_month_ratio']:.4f} ({kpi['plus_months']}/{kpi['total_months']})")
    print(f"  broken_months   : {kpi['broken_months']}")
    print(f"  CI(90%) 下限    : {kpi['roi_ci_low_90']:>+8.2f}%")
    print(f"  CI(90%) 上限    : {kpi['roi_ci_high_90']:>+8.2f}%")
    print(f"  primary_score   : {summary['primary_score']:>+8.2f}")
    print(f"  verdict         : {summary['verdict']}")
    print()
    print("  [月別 ROI]")
    for row in monthly_rows:
        roi = (row["payout"] / row["wagered"] - 1) * 100 if row["wagered"] > 0 else 0.0
        print(f"  {row['month']:>7}  bets={row['n_bets']:>6}  wagered={row['wagered']:>10,.0f}  ROI={roi:>+10.2f}%")
    print("=" * 62)


if __name__ == "__main__":
    main()
