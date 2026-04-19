"""
競艇予想モデル 月次予想・結果検証スクリプト

指定月の全レースを現行モデルで予測し、実際の結果と照合して
1ベット1行形式の CSV を出力する。

使い方:
  python run_predict_check.py --year 2026 --month 4
  python run_predict_check.py --year 2026 --month 4 --real-odds

出力 CSV 列（必須）:
  日付, 会場, レース, 予想着順, 実オッズ, レース結果, 返金額
出力 CSV 列（追加）:
  予想確率(%), 期待値, 的中, 投資額, 損益, オッズソース, race_id
"""
import argparse
import calendar
import logging
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.history_downloader import (
    DATA_DIR,
    download_day_data,
    extract_lzh,
    parse_result_file,
)
from collector.odds_downloader import load_or_download_month_odds
from collector.program_downloader import (
    load_program_month,
    merge_program_data,
)
from features.feature_builder import build_features_from_history
from model.predictor import calc_expected_values, calc_trifecta_probs, predict_win_prob
from backtest.engine import get_actual_combo
from backtest.odds_simulator import SYNTHETIC_ODDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"

STADIUM_NAMES: dict[int, str] = {
    1: "桐生", 2: "戸田", 3: "江戸川", 4: "平和島", 5: "多摩川", 6: "浜名湖",
    7: "蒲郡", 8: "常滑", 9: "津", 10: "三国", 11: "びわこ", 12: "住之江",
    13: "尼崎", 14: "鳴門", 15: "丸亀", 16: "児島", 17: "宮島", 18: "徳山",
    19: "下関", 20: "若松", 21: "芦屋", 22: "福岡", 23: "唐津", 24: "大村",
}

# CSV 列順
_CSV_COLUMNS = [
    "日付", "会場", "レース",
    "予想着順", "予想確率(%)", "期待値",
    "実オッズ", "レース結果", "的中",
    "投資額", "返金額", "損益",
    "オッズソース", "race_id",
]


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def load_month_data(year: int, month: int, max_workers: int = 8) -> pd.DataFrame:
    """指定月の K/B ファイルをダウンロードしてマージした DataFrame を返す。"""
    days_in_month = calendar.monthrange(year, month)[1]
    save_dir = DATA_DIR
    tmpdir = Path(tempfile.mkdtemp(prefix="boatrace_pc_"))

    days = [
        d for d in range(1, days_in_month + 1)
        if date(year, month, d) <= date.today()
    ]
    logger.info(
        "Downloading %d-%02d K-files (%d days, %d workers)...",
        year, month, len(days), max_workers,
    )

    def _fetch_day(day: int) -> list[dict]:
        try:
            lzh = download_day_data(year, month, day, dest_dir=save_dir)
            if lzh is None:
                return []
            extract_dir = tmpdir / lzh.stem
            files = extract_lzh(lzh, extract_dir)
            return [rec for f in files for rec in parse_result_file(f)]
        except Exception as exc:
            logger.debug("Skip %d-%02d-%02d: %s", year, month, day, exc)
            return []

    all_records: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_day, d): d for d in days}
            for future in as_completed(futures):
                all_records.extend(future.result())
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    df_k = pd.DataFrame(all_records) if all_records else pd.DataFrame()
    logger.info("K-file: %d records for %d-%02d", len(df_k), year, month)

    logger.info("Downloading %d-%02d B-files (program data)...", year, month)
    df_b = load_program_month(year, month, max_workers=max_workers)
    return merge_program_data(df_k, df_b)


# ---------------------------------------------------------------------------
# 予想・照合バッチ処理
# ---------------------------------------------------------------------------

def run_predict_check_batch(
    df_test: pd.DataFrame,
    model,
    odds_by_race: dict[str, dict[str, float]],
    prob_threshold: float,
    ev_threshold: float,
    max_bets_per_race: int,
    bet_amount: int,
    exclude_courses: list[int] | None,
    min_odds: float | None,
    exclude_stadiums: list[int] | None,
) -> list[dict]:
    """
    全レースを一括予測し、購入条件を満たす組み合わせごとに 1 行の record を返す。

    run_backtest_batch と同様に model.predict を全データ分まとめて 1 回だけ呼ぶ。
    戻り値は 1ベット1行形式（race 集約なし）でCSV出力向け。
    """
    try:
        X_all, _ = build_features_from_history(df_test)
    except Exception as exc:
        logger.error("Feature build failed: %s", exc)
        return []

    if X_all.empty:
        logger.warning("No valid rows for feature build")
        return []

    df_valid = df_test.loc[X_all.index].copy()

    raw_probs = predict_win_prob(model, X_all)
    first_place_probs = raw_probs[:, 0] if raw_probs.ndim == 2 else raw_probs
    df_valid["_fp"] = first_place_probs

    records: list[dict] = []
    total_races = 0
    skipped = 0

    for race_id, race_group in df_valid.groupby("race_id"):
        total_races += 1

        if len(race_group) != 6:
            skipped += 1
            continue

        if exclude_stadiums and "stadium_id" in race_group.columns:
            if int(race_group["stadium_id"].iloc[0]) in exclude_stadiums:
                skipped += 1
                continue

        actual_combo = get_actual_combo(race_group)
        if actual_combo is None:
            skipped += 1
            continue

        race_odds = odds_by_race.get(str(race_id))
        use_real_odds = race_odds is not None and len(race_odds) >= 60
        effective_odds = race_odds if use_real_odds else SYNTHETIC_ODDS

        fp = race_group.sort_values("boat_no")["_fp"].values
        trifecta_probs = calc_trifecta_probs(fp)
        ev_results = calc_expected_values(trifecta_probs, effective_odds)

        alerts = [
            r for r in ev_results
            if r["win_probability"] >= prob_threshold
            and r["expected_value"] >= ev_threshold
        ]
        if exclude_courses:
            alerts = [
                r for r in alerts
                if int(r["combination"].split("-")[0]) not in exclude_courses
            ]
        if min_odds is not None:
            alerts = [
                r for r in alerts
                if effective_odds.get(r["combination"], 0.0) >= min_odds
            ]
        alerts = alerts[:max_bets_per_race]

        race_date  = str(race_group["race_date"].iloc[0])
        stadium_id = int(race_group["stadium_id"].iloc[0]) if "stadium_id" in race_group.columns else 0
        race_no    = int(race_group["race_no"].iloc[0]) if "race_no" in race_group.columns else 0
        venue_name = STADIUM_NAMES.get(stadium_id, f"場{stadium_id:02d}")

        for r in alerts:
            combo    = r["combination"]
            odds_val = effective_odds.get(combo, 0.0)
            is_hit   = combo == actual_combo
            payout   = round(odds_val * bet_amount, 1) if is_hit else 0.0

            records.append({
                "日付":        race_date,
                "会場":        venue_name,
                "レース":      race_no,
                "予想着順":    combo,
                "予想確率(%)": round(r["win_probability"] * 100, 2),
                "期待値":      round(r["expected_value"], 3),
                "実オッズ":    odds_val,
                "レース結果":  actual_combo,
                "的中":        is_hit,
                "投資額":      bet_amount,
                "返金額":      payout,
                "損益":        round(payout - bet_amount, 1),
                "オッズソース": "実" if use_real_odds else "合成",
                "race_id":     str(race_id),
            })

    logger.info(
        "Done: %d races total, %d skipped, %d bets generated",
        total_races, skipped, len(records),
    )
    return records


# ---------------------------------------------------------------------------
# サマリー出力
# ---------------------------------------------------------------------------

def print_summary(records: list[dict], prob_threshold: float, ev_threshold: float) -> None:
    if not records:
        print("\n購入対象なし（条件を満たすベットがありませんでした）")
        return

    df = pd.DataFrame(records)
    total_bets    = len(df)
    total_wagered = float(df["投資額"].sum())
    total_payout  = float(df["返金額"].sum())
    total_profit  = float(df["損益"].sum())
    hits          = int(df["的中"].sum())
    roi           = (total_payout / total_wagered - 1) * 100 if total_wagered > 0 else 0.0
    hit_rate      = hits / total_bets * 100 if total_bets > 0 else 0.0
    avg_odds      = float(df[df["的中"]]["実オッズ"].mean()) if hits > 0 else 0.0

    print()
    print("=" * 62)
    print("  月次予想・結果検証サマリー")
    print("=" * 62)
    print(f"  対象期間    : {df['日付'].min()} 〜 {df['日付'].max()}")
    print(f"  的中確率閾値: {prob_threshold * 100:.1f}%")
    print(f"  EV閾値      : {ev_threshold:.2f}")
    print(f"  ベット数    : {total_bets:,} 点")
    print("-" * 62)
    print(f"  投資合計    : ¥{total_wagered:>12,.0f}")
    print(f"  払戻合計    : ¥{total_payout:>12,.0f}")
    print(f"  損益        : ¥{total_profit:>+12,.0f}")
    print(f"  ROI         : {roi:>+.1f}%")
    print("-" * 62)
    print(f"  的中        : {hits} / {total_bets} 点  ({hit_rate:.2f}%)")
    print(f"  平均配当    : {avg_odds:.1f}x  (的中時)")

    # 会場別集計
    by_venue = (
        df.groupby("会場")
        .agg(ベット=("投資額", "count"), 投資=("投資額", "sum"),
             払戻=("返金額", "sum"), 的中=("的中", "sum"))
        .assign(ROI=lambda x: (x["払戻"] / x["投資"] - 1) * 100)
        .sort_values("ROI", ascending=False)
    )
    if not by_venue.empty:
        print()
        print("  [会場別集計]")
        print(f"  {'会場':>6}  {'ベット':>6}  {'投資':>10}  {'払戻':>10}  {'ROI':>7}  {'的中'}")
        print("  " + "-" * 52)
        for venue, row in by_venue.iterrows():
            print(
                f"  {venue:>6}  {int(row['ベット']):>6,}  "
                f"¥{row['投資']:>9,.0f}  ¥{row['払戻']:>9,.0f}  "
                f"{row['ROI']:>+6.1f}%  {int(row['的中'])}"
            )

    # オッズソース内訳
    real_cnt = int((df["オッズソース"] == "実").sum())
    syn_cnt  = int((df["オッズソース"] == "合成").sum())
    print()
    if syn_cnt > 0:
        print(f"  ※ 実オッズ: {real_cnt:,}点  合成オッズ（理論値）: {syn_cnt:,}点")
        print("  ※ 合成オッズ使用分は実際の配当と異なります")
    else:
        print(f"  ※ 全 {real_cnt:,} 点が実オッズ使用")
    print("=" * 62)
    print()


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="競艇予想モデル 月次予想・結果検証",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--year",              type=int,   required=True,          help="対象年")
    parser.add_argument("--month",             type=int,   required=True,          help="対象月（1–12）")
    parser.add_argument("--prob-threshold",    type=float, default=0.07,           help="的中確率閾値（例: 0.07 = 7%%）")
    parser.add_argument("--ev-threshold",      type=float, default=2.0,            help="EV閾値（例: 2.0）")
    parser.add_argument("--bet-amount",        type=int,   default=100,            help="1点賭け金（円）")
    parser.add_argument("--max-bets",          type=int,   default=5,              help="1レース最大賭け点数")
    parser.add_argument("--exclude-courses",   type=int,   nargs="+", default=[2, 4, 5], help="除外する1着艇番")
    parser.add_argument("--min-odds",          type=float, default=100.0,          help="購入オッズ下限（例: 100.0 → 100倍未満除外）")
    parser.add_argument("--exclude-stadiums",  type=int,   nargs="+", default=[11], help="除外場ID（例: 11=びわこ）")
    parser.add_argument("--real-odds",         action="store_true",               help="boatrace.jp の実オッズを使用（初回 ~90 分）")
    parser.add_argument("--model-path",        type=str,   default=None,           help="モデルファイルパス（省略時は最新モデルを自動検索）")
    parser.add_argument("--output",            type=str,   default=None,           help="出力 CSV パス（省略時は artifacts/predict_check_YYYYMM.csv）")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(exist_ok=True)

    # ── モデルロード ──────────────────────────────────────────────
    if args.model_path:
        model_path = Path(args.model_path)
        if not model_path.exists():
            logger.error("Model not found: %s", model_path)
            sys.exit(1)
    else:
        existing = sorted(ARTIFACTS_DIR.glob("model_*.pkl"), reverse=True)
        if not existing:
            logger.error("No model found in %s. Run download_model.py first.", ARTIFACTS_DIR)
            sys.exit(1)
        model_path = existing[0]

    logger.info("Loading model: %s", model_path)
    model = joblib.load(model_path)

    if not args.real_odds:
        logger.warning(
            "--real-odds 未指定のため合成オッズ（艇番ベース理論値）を使用します。\n"
            "  実際のROI・配当とは大きく異なる場合があります。\n"
            "  正確な検証には --real-odds を指定してください（初回 ~90 分）。"
        )

    # ── データ取得 ──────────────────────────────────────────────
    df_test = load_month_data(args.year, args.month)
    if df_test.empty:
        logger.error("No data for %d-%02d.", args.year, args.month)
        sys.exit(1)

    # ── 実オッズ取得 ────────────────────────────────────────────
    odds_by_race: dict[str, dict[str, float]] = {}
    if args.real_odds:
        logger.info("Fetching real odds for %d-%02d...", args.year, args.month)
        odds_by_race = load_or_download_month_odds(args.year, args.month, df_test)
        logger.info("Real odds loaded for %d races", len(odds_by_race))

    # ── 予想・照合バッチ ────────────────────────────────────────
    records = run_predict_check_batch(
        df_test=df_test,
        model=model,
        odds_by_race=odds_by_race,
        prob_threshold=args.prob_threshold,
        ev_threshold=args.ev_threshold,
        max_bets_per_race=args.max_bets,
        bet_amount=args.bet_amount,
        exclude_courses=args.exclude_courses,
        min_odds=args.min_odds,
        exclude_stadiums=args.exclude_stadiums,
    )

    # ── CSV 出力 ────────────────────────────────────────────────
    output_path = Path(
        args.output or ARTIFACTS_DIR / f"predict_check_{args.year}{args.month:02d}.csv"
    )

    if not records:
        logger.warning("No bets generated for %d-%02d.", args.year, args.month)
        pd.DataFrame(columns=_CSV_COLUMNS).to_csv(
            output_path, index=False, encoding="utf-8-sig"
        )
        logger.info("Empty CSV saved to %s", output_path)
        return

    df_out = (
        pd.DataFrame(records)
        .sort_values(["日付", "race_id", "予想着順"])
        .reset_index(drop=True)
    )
    df_out = df_out[_CSV_COLUMNS]
    df_out.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("Results saved to %s (%d bets)", output_path, len(df_out))

    print_summary(records, args.prob_threshold, args.ev_threshold)


if __name__ == "__main__":
    main()
