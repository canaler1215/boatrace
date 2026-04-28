"""
B-3 拡張 A R2: 複勝実払戻取得 sample（解釈確定用）

`data/odds/place_odds_202512.parquet` から 50 race をランダムサンプリングし、
各レースの実払戻金 (top-2 艇分) を boatrace.jp `raceresult` から取得する。

取得後、`odds_low / odds_mid / odds_high` と実 payout の対応関係を分析する。

出力:
  - artifacts/place_payouts_sample_2025-12.parquet
  - 標準出力に分析サマリー
"""
import logging
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.openapi_client import fetch_place_payouts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[3]
ODDS_DIR = ROOT / "data" / "odds"
ARTIFACTS_DIR = ROOT / "artifacts"


def race_id_to_args(race_id: str) -> tuple[int, str, int]:
    """race_id (12 桁: SSYYYYMMDDRR) → (stadium_id, hd, rno)"""
    sid = int(race_id[:2])
    yyyy = race_id[2:6]
    mm = race_id[6:8]
    dd = race_id[8:10]
    rno = int(race_id[10:12])
    return sid, f"{yyyy}-{mm}-{dd}", rno


def fetch_one(race_id: str) -> tuple[str, dict[str, int]]:
    sid, dt, rno = race_id_to_args(race_id)
    payouts = fetch_place_payouts(sid, dt, rno)
    return race_id, payouts


def main(sample_size: int = 50, seed: int = 42) -> None:
    odds_path = ODDS_DIR / "place_odds_202512.parquet"
    if not odds_path.exists():
        raise FileNotFoundError(odds_path)
    odds_df = pd.read_parquet(odds_path)
    odds_df["race_id"] = odds_df["race_id"].astype(str)

    # 6 艇全揃いのレースから sample
    counts = odds_df.groupby("race_id").size()
    valid_races = counts[counts == 6].index.tolist()
    rng = random.Random(seed)
    sample_races = rng.sample(valid_races, min(sample_size, len(valid_races)))
    logger.info("sample size: %d (from %d valid races)", len(sample_races), len(valid_races))

    results: dict[str, dict[str, int]] = {}
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fetch_one, rid): rid for rid in sample_races}
        for fut in as_completed(futures):
            rid, p = fut.result()
            if p:
                results[rid] = p
            else:
                failed.append(rid)
            if (len(results) + len(failed)) % 10 == 0:
                logger.info("progress: %d / %d", len(results) + len(failed), len(sample_races))

    logger.info("取得成功: %d / %d", len(results), len(sample_races))
    if failed:
        logger.warning("取得失敗: %d races: %s", len(failed), failed[:10])

    # 結果を long-format DataFrame に
    rows = []
    for rid, payouts in results.items():
        for boat_no, yen in payouts.items():
            rows.append({"race_id": rid, "combination": boat_no, "payout_yen": yen})
    if not rows:
        logger.error("結果なし")
        return
    payout_df = pd.DataFrame(rows)
    out_path = ARTIFACTS_DIR / "place_payouts_sample_2025-12.parquet"
    payout_df.to_parquet(out_path, index=False)
    logger.info("saved: %s (%d rows / %d races)", out_path, len(payout_df), payout_df["race_id"].nunique())

    # 分析: payout を odds_low/mid/high と比較
    odds_df["odds_mid"] = (odds_df["odds_low"] + odds_df["odds_high"]) / 2.0
    merged = payout_df.merge(
        odds_df[["race_id", "combination", "odds_low", "odds_mid", "odds_high"]],
        on=["race_id", "combination"],
        how="left",
    )
    merged["payout_x"] = merged["payout_yen"] / 100.0  # 倍率に変換
    merged["in_range"] = (
        (merged["payout_x"] >= merged["odds_low"] - 0.01)
        & (merged["payout_x"] <= merged["odds_high"] + 0.01)
    )
    # payout_x がレンジ内のどこに位置するか (0=low, 1=high)
    rng_size = (merged["odds_high"] - merged["odds_low"]).clip(lower=1e-6)
    merged["pos_in_range"] = (merged["payout_x"] - merged["odds_low"]) / rng_size

    print()
    print("=" * 78)
    print(f"  R2 sample: 実 payout vs odds_low/mid/high (n={len(merged)} hit-boats)")
    print("=" * 78)
    print(f"  in_range (payout in [low, high]): {merged['in_range'].sum()}/{len(merged)} "
          f"({100 * merged['in_range'].mean():.1f}%)")
    print()
    print("  payout_x stats:")
    print(merged["payout_x"].describe().to_string())
    print()
    print("  odds_low / odds_mid / odds_high mean:")
    print(f"    odds_low  mean = {merged['odds_low'].mean():.3f}")
    print(f"    odds_mid  mean = {merged['odds_mid'].mean():.3f}")
    print(f"    odds_high mean = {merged['odds_high'].mean():.3f}")
    print(f"    payout_x  mean = {merged['payout_x'].mean():.3f}")
    print()
    print("  pos_in_range distribution (0=low, 0.5=mid, 1=high):")
    print(merged["pos_in_range"].describe().to_string())
    print()

    # bin 別に集計（odds_low ベース implied で 4 bin）
    merged["implied_low"] = 0.80 / merged["odds_low"]
    merged["bin"] = pd.cut(
        merged["implied_low"],
        bins=[0, 0.1, 0.3, 0.6, 1.0],
        labels=["[0,0.1)", "[0.1,0.3)", "[0.3,0.6)", "[0.6,1.0)"],
        right=False,
    )
    print("  By implied_low bin:")
    bin_summary = merged.groupby("bin", observed=True).agg(
        n=("payout_x", "count"),
        odds_low_mean=("odds_low", "mean"),
        odds_mid_mean=("odds_mid", "mean"),
        odds_high_mean=("odds_high", "mean"),
        payout_x_mean=("payout_x", "mean"),
        pos_in_range_mean=("pos_in_range", "mean"),
        in_range_pct=("in_range", lambda s: s.mean() * 100),
    )
    print(bin_summary.to_string())
    print()
    print("=" * 78)


if __name__ == "__main__":
    sample_size = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    main(sample_size=sample_size)
