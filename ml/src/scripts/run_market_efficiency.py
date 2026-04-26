"""
市場効率の歪み分析（フェーズ B-1 Step 1）

オッズから逆算した暗黙確率と実勝率を比較し、3 連単市場における
体系的な歪み（lift = actual_p / implied_p）を検出する。

モデルは一切使わず、data/odds/ と data/history/ のみで完結する。

採用判定（B-1 PLAN §3）:
  - n ≥ 1,000 のビンで lift ≥ 1.10 または ≤ 0.85
  - 90% bootstrap CI で 1.0 を含まない
  - 前半 6 ヶ月 / 後半 6 ヶ月で同方向

出力:
  artifacts/market_efficiency_<period>_<bet>.csv     全期間ビン別集計
  artifacts/market_efficiency_<half1>_<bet>.csv      前半（split-halves 時）
  artifacts/market_efficiency_<half2>_<bet>.csv      後半
  artifacts/market_efficiency_<period>_<bet>.png     キャリブレーションプロット

使い方:
  py -3.12 ml/src/scripts/run_market_efficiency.py \
    --start 2025-05 --end 2026-04 --bet-type trifecta \
    --split-halves --bootstrap 2000
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.history_downloader import load_history_range

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parents[3]
ARTIFACTS_DIR = ROOT / "artifacts"
ODDS_DIR = ROOT / "data" / "odds"

# 対数等間隔ビン（implied_p_norm 用、右スキュー対策）
LOG_BINS = np.array([
    0.0001, 0.0003, 0.001, 0.003,
    0.01, 0.03, 0.05, 0.10, 0.20, 0.50, 1.0,
])

DEFAULT_TAKEOUT = 0.25  # 公営競技 控除率


# ---------------------------------------------------------------------------
# 期間ユーティリティ
# ---------------------------------------------------------------------------

def parse_year_month(s: str) -> tuple[int, int]:
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"Expected YYYY-MM, got: {s}")
    return int(parts[0]), int(parts[1])


def iter_year_months(start: tuple[int, int], end: tuple[int, int]) -> Iterable[tuple[int, int]]:
    y, m = start
    end_y, end_m = end
    while (y, m) <= (end_y, end_m):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


# ---------------------------------------------------------------------------
# データロード
# ---------------------------------------------------------------------------

def load_odds_period(start: tuple[int, int], end: tuple[int, int]) -> pd.DataFrame:
    """指定期間の trifecta オッズ parquet を結合して返す。"""
    frames = []
    for y, m in iter_year_months(start, end):
        path = ODDS_DIR / f"odds_{y}{m:02d}.parquet"
        if not path.exists():
            logger.warning("オッズキャッシュ欠落: %s", path)
            continue
        df = pd.read_parquet(path)
        df["year_month"] = f"{y}-{m:02d}"
        frames.append(df)
    if not frames:
        raise RuntimeError("オッズデータが見つかりません")
    odds = pd.concat(frames, ignore_index=True)
    odds["race_id"] = odds["race_id"].astype(str)
    logger.info(
        "オッズ読み込み完了: %d 行 / %d レース / %d 月",
        len(odds), odds["race_id"].nunique(), len(frames),
    )
    return odds


def load_winning_combos(start: tuple[int, int], end: tuple[int, int]) -> pd.DataFrame:
    """
    K ファイルから各 race_id の 1-2-3 着 combination（"X-Y-Z"）を抽出。
    Returns: DataFrame with columns race_id, winning_combo
    """
    df_hist = load_history_range(
        start_year=start[0],
        end_year=end[0],
        start_month=start[1],
        end_month=end[1],
    )
    if df_hist.empty:
        raise RuntimeError("履歴データが空です")

    df_top3 = df_hist[df_hist["finish_position"].isin([1, 2, 3])].copy()
    df_top3["race_id"] = df_top3["race_id"].astype(str)

    pivot = df_top3.pivot_table(
        index="race_id",
        columns="finish_position",
        values="boat_no",
        aggfunc="first",
    )
    pivot = pivot.dropna(subset=[1, 2, 3])
    pivot["winning_combo"] = (
        pivot[1].astype(int).astype(str) + "-"
        + pivot[2].astype(int).astype(str) + "-"
        + pivot[3].astype(int).astype(str)
    )
    result = pivot.reset_index()[["race_id", "winning_combo"]]
    logger.info("結果データ: %d レース（1-2-3 着揃い）", len(result))
    return result


# ---------------------------------------------------------------------------
# 暗黙確率 / 結合
# ---------------------------------------------------------------------------

def compute_implied_probs(odds: pd.DataFrame) -> pd.DataFrame:
    """odds に implied_p_raw / implied_p_norm / implied_p_takeout を追加。"""
    df = odds.copy()
    df["implied_p_raw"] = 1.0 / df["odds"]
    df["implied_p_takeout"] = (1.0 - DEFAULT_TAKEOUT) / df["odds"]
    sum_per_race = df.groupby("race_id")["implied_p_raw"].transform("sum")
    df["implied_p_norm"] = df["implied_p_raw"] / sum_per_race
    return df


def attach_hit_label(odds: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """odds に is_hit を付与し、結果のあるレースのみに絞る。"""
    df = odds.merge(results, on="race_id", how="inner")
    df["is_hit"] = (df["combination"] == df["winning_combo"]).astype(int)
    n_races = df["race_id"].nunique()
    n_hits_per_race = df.groupby("race_id")["is_hit"].sum()
    no_hit = (n_hits_per_race == 0).sum()
    multi_hit = (n_hits_per_race > 1).sum()
    if multi_hit > 0:
        logger.warning("複数 winning combo を持つレース: %d 件", multi_hit)
    if no_hit > 0:
        logger.info(
            "オッズに winning combo が存在しないレース: %d 件（中止/欠損）",
            no_hit,
        )
    logger.info("結合後: %d combo / %d レース", len(df), n_races)
    return df


# ---------------------------------------------------------------------------
# ビン集計
# ---------------------------------------------------------------------------

def wilson_ci(n_hits: int, n: int, alpha: float = 0.10) -> tuple[float, float]:
    """Wilson 信頼区間（actual_p 用）"""
    if n == 0:
        return float("nan"), float("nan")
    from scipy import stats
    z = float(stats.norm.ppf(1 - alpha / 2))
    p_hat = n_hits / n
    denom = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    margin = z * np.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / denom
    return float(center - margin), float(center + margin)


def assign_bins(df: pd.DataFrame) -> pd.DataFrame:
    """implied_p_norm に bin_idx を付与し、範囲外行を除外。"""
    df = df.copy()
    df["bin_idx"] = np.digitize(df["implied_p_norm"], LOG_BINS) - 1
    df = df[(df["bin_idx"] >= 0) & (df["bin_idx"] < len(LOG_BINS) - 1)]
    return df


def bin_summary(df: pd.DataFrame) -> pd.DataFrame:
    """ビン別 KPI を計算（lift / Wilson CI / EV 等）。"""
    df = assign_bins(df)
    rows = []
    for b in range(len(LOG_BINS) - 1):
        sub = df[df["bin_idx"] == b]
        if sub.empty:
            continue
        n = len(sub)
        n_hits = int(sub["is_hit"].sum())
        actual_p = n_hits / n
        mean_implied_norm = float(sub["implied_p_norm"].mean())
        mean_implied_raw = float(sub["implied_p_raw"].mean())
        mean_implied_takeout = float(sub["implied_p_takeout"].mean())
        mean_odds = float(sub["odds"].mean())
        lift = actual_p / mean_implied_norm if mean_implied_norm > 0 else float("nan")
        ev_all_buy = mean_odds * actual_p
        wlo, whi = wilson_ci(n_hits, n, alpha=0.10)

        rows.append({
            "bin_lower":              float(LOG_BINS[b]),
            "bin_upper":              float(LOG_BINS[b + 1]),
            "n":                      n,
            "n_races":                int(sub["race_id"].nunique()),
            "n_hits":                 n_hits,
            "mean_implied_p_norm":    mean_implied_norm,
            "mean_implied_p_raw":     mean_implied_raw,
            "mean_implied_p_takeout": mean_implied_takeout,
            "mean_actual_p":          actual_p,
            "lift":                   lift,
            "mean_odds":              mean_odds,
            "ev_all_buy":             ev_all_buy,
            "wilson_lo":              wlo,
            "wilson_hi":              whi,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Bootstrap CI（lift）
# ---------------------------------------------------------------------------

def bootstrap_lift_ci(
    df: pd.DataFrame,
    n_resamples: int = 2000,
    alpha: float = 0.10,
    seed: int = 42,
) -> pd.DataFrame:
    """
    レース単位で復元抽出（月 stratify）し、ビン別 lift の 90% CI を返す。

    高速化: 各 iter で「レース重み配列」を bincount 生成し、bin 毎の
    重み付き集計を np.bincount でベクトル化する（1 iter ~数十 ms）。
    """
    rng = np.random.default_rng(seed)
    df = assign_bins(df).reset_index(drop=True)

    race_ids = df["race_id"].drop_duplicates().reset_index(drop=True)
    race_id_to_idx = {rid: i for i, rid in enumerate(race_ids)}
    n_races = len(race_ids)
    df["race_idx"] = df["race_id"].map(race_id_to_idx)

    # 月別レース index 配列
    race_month = df.drop_duplicates("race_id").set_index("race_id")["year_month"]
    month_to_race_indices: dict[str, np.ndarray] = {}
    for ym, ids in race_month.groupby(race_month):
        idx_arr = np.array([race_id_to_idx[rid] for rid in ids.index], dtype=np.int64)
        month_to_race_indices[ym] = idx_arr

    bin_idx_arr = df["bin_idx"].values.astype(np.int64)
    is_hit_arr = df["is_hit"].values.astype(np.float64)
    implied_norm_arr = df["implied_p_norm"].values.astype(np.float64)
    combo_race_idx = df["race_idx"].values.astype(np.int64)
    n_bins = len(LOG_BINS) - 1

    lifts = np.full((n_resamples, n_bins), np.nan)

    for it in range(n_resamples):
        race_weights = np.zeros(n_races, dtype=np.float64)
        for ym, race_indices in month_to_race_indices.items():
            sampled = rng.choice(race_indices, size=len(race_indices), replace=True)
            np.add.at(race_weights, sampled, 1.0)
        combo_weights = race_weights[combo_race_idx]
        bin_n = np.bincount(bin_idx_arr, weights=combo_weights, minlength=n_bins)
        bin_hits = np.bincount(bin_idx_arr, weights=combo_weights * is_hit_arr, minlength=n_bins)
        bin_implied_sum = np.bincount(
            bin_idx_arr, weights=combo_weights * implied_norm_arr, minlength=n_bins
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            actual_p = np.where(bin_n > 0, bin_hits / bin_n, np.nan)
            mean_implied = np.where(bin_n > 0, bin_implied_sum / bin_n, np.nan)
            lift = np.where(mean_implied > 0, actual_p / mean_implied, np.nan)
        lifts[it] = lift

        if (it + 1) % 200 == 0:
            logger.info("bootstrap %d / %d", it + 1, n_resamples)

    rows = []
    for k in range(n_bins):
        col = lifts[:, k]
        col = col[~np.isnan(col)]
        if len(col) == 0:
            continue
        lo = float(np.quantile(col, alpha / 2))
        hi = float(np.quantile(col, 1 - alpha / 2))
        rows.append({
            "bin_lower":    float(LOG_BINS[k]),
            "bin_upper":    float(LOG_BINS[k + 1]),
            "lift_boot_lo": lo,
            "lift_boot_hi": hi,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# プロット
# ---------------------------------------------------------------------------

def plot_calibration(summary: pd.DataFrame, out_path: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    x = summary["mean_implied_p_norm"].values
    y = summary["mean_actual_p"].values
    yerr_lo = np.maximum(y - summary["wilson_lo"].values, 0)
    yerr_hi = np.maximum(summary["wilson_hi"].values - y, 0)

    ax.errorbar(
        x, y,
        yerr=[yerr_lo, yerr_hi],
        fmt="o", color="C0", capsize=3,
        label="actual_p (Wilson 90% CI)",
    )
    line_lo = max(min(x.min(), y.min()), 1e-5)
    line_hi = max(x.max(), y.max())
    ax.plot([line_lo, line_hi], [line_lo, line_hi], "k--", alpha=0.5, label="y = x (perfect)")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Implied probability (normalized, (1/o) / Σ(1/o))")
    ax.set_ylabel("Actual hit rate")
    ax.set_title(title)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    logger.info("プロット保存: %s", out_path)


# ---------------------------------------------------------------------------
# 採用判定
# ---------------------------------------------------------------------------

def evaluate_distortion(summary: pd.DataFrame, min_n: int = 1000) -> list[dict]:
    """B-1 PLAN §3 採用基準で歪みビンを抽出。"""
    flagged = []
    for _, row in summary.iterrows():
        if row["n"] < min_n:
            continue
        lift = row["lift"]
        lo = row.get("lift_boot_lo", np.nan)
        hi = row.get("lift_boot_hi", np.nan)
        ci_excludes_one = (
            (not np.isnan(lo) and not np.isnan(hi))
            and (lo > 1.0 or hi < 1.0)
        )
        magnitude_ok = (lift >= 1.10) or (lift <= 0.85)
        if magnitude_ok and ci_excludes_one:
            flagged.append({
                "bin_lower":    row["bin_lower"],
                "bin_upper":    row["bin_upper"],
                "n":            int(row["n"]),
                "lift":         lift,
                "lift_boot_lo": lo,
                "lift_boot_hi": hi,
                "direction":    "underpriced (lift>=1.10)" if lift >= 1.10 else "overpriced (lift<=0.85)",
            })
    return flagged


# ---------------------------------------------------------------------------
# Step 2: サブセグメント分析（focus 帯内 group_by）
# ---------------------------------------------------------------------------

# 場名マッピング（run_segment_analysis.py から流用）
STADIUM_NAMES: dict[int, str] = {
    1: "Kiryu",  2: "Toda",   3: "Edogawa", 4: "Heiwajima", 5: "Tamagawa",
    6: "Hamanako", 7: "Gamagori", 8: "Tokoname", 9: "Tsu",   10: "Mikuni",
    11: "Biwako", 12: "Suminoe", 13: "Amagasaki", 14: "Naruto", 15: "Marugame",
    16: "Kojima", 17: "Miyajima", 18: "Tokuyama", 19: "Shimonoseki", 20: "Wakamatsu",
    21: "Ashiya", 22: "Fukuoka", 23: "Karatsu",  24: "Omura",
}

ODDS_BAND_BINS = [1.0, 5.0, 10.0, 50.0, 200.0, 1000.0, float("inf")]
ODDS_BAND_LABELS = ["[1,5)", "[5,10)", "[10,50)", "[50,200)", "[200,1000)", "[1000+)"]


def add_group_column(df: pd.DataFrame, group_by: str) -> pd.DataFrame:
    """group_by に応じたグルーピング列 _group を付与。"""
    df = df.copy()
    if group_by == "stadium":
        df["_group"] = df["race_id"].str[:2].astype(int)
    elif group_by == "course":
        df["_group"] = df["combination"].str.split("-").str[0].astype(int)
    elif group_by == "odds_band":
        df["_group"] = pd.cut(
            df["odds"], bins=ODDS_BAND_BINS, labels=ODDS_BAND_LABELS, right=False,
        ).astype(str)
    elif group_by == "month":
        df["_group"] = df["year_month"]
    else:
        raise ValueError(f"Unknown group_by: {group_by}")
    return df


def add_2axis_group_column(df: pd.DataFrame, axis1: str, axis2: str) -> pd.DataFrame:
    """2 軸組合せ '<a1>|<a2>' 形式の _group 列を付与。"""
    df1 = add_group_column(df, axis1).rename(columns={"_group": "_g1"})
    df2 = add_group_column(df1, axis2).rename(columns={"_group": "_g2"})
    df2["_group"] = df2["_g1"].astype(str) + "|" + df2["_g2"].astype(str)
    df2 = df2.drop(columns=["_g1", "_g2"])
    return df2


def segment_summary_within_focus(df: pd.DataFrame, group_by: str) -> pd.DataFrame:
    """focus 帯内でグループ別 KPI を計算。"""
    rows = []
    for gval, sub in df.groupby("_group", observed=True):
        n = len(sub)
        n_hits = int(sub["is_hit"].sum())
        if n == 0:
            continue
        actual_p = n_hits / n
        mean_implied = float(sub["implied_p_norm"].mean())
        mean_odds = float(sub["odds"].mean())
        lift = actual_p / mean_implied if mean_implied > 0 else float("nan")
        ev_all_buy = mean_odds * actual_p
        wlo, whi = wilson_ci(n_hits, n, alpha=0.10)
        rows.append({
            group_by:              gval,
            "n":                   n,
            "n_races":             int(sub["race_id"].nunique()),
            "n_hits":              n_hits,
            "mean_implied_p_norm": mean_implied,
            "mean_actual_p":       actual_p,
            "lift":                lift,
            "mean_odds":           mean_odds,
            "ev_all_buy":          ev_all_buy,
            "wilson_lo":           wlo,
            "wilson_hi":           whi,
        })
    return pd.DataFrame(rows)


def bootstrap_segment_lift_ci(
    df: pd.DataFrame,
    group_by: str,
    n_resamples: int = 2000,
    alpha: float = 0.10,
    seed: int = 42,
) -> pd.DataFrame:
    """
    focus 帯内のグループ別 lift と ev_all_buy の bootstrap 90% CI。
    レース単位復元抽出 × 月 stratify。
    """
    rng = np.random.default_rng(seed)
    df = df.reset_index(drop=True)

    # group → int idx
    groups = sorted(df["_group"].unique().tolist())
    group_to_idx = {g: i for i, g in enumerate(groups)}
    n_groups = len(groups)
    g_arr = df["_group"].map(group_to_idx).values.astype(np.int64)

    # race_id → int idx
    race_ids = df["race_id"].drop_duplicates().reset_index(drop=True)
    race_id_to_idx = {rid: i for i, rid in enumerate(race_ids)}
    n_races = len(race_ids)
    combo_race_idx = df["race_id"].map(race_id_to_idx).values.astype(np.int64)

    # 月別レース index
    race_month = df.drop_duplicates("race_id").set_index("race_id")["year_month"]
    month_to_race_indices: dict[str, np.ndarray] = {}
    for ym, ids in race_month.groupby(race_month):
        idx_arr = np.array([race_id_to_idx[rid] for rid in ids.index], dtype=np.int64)
        month_to_race_indices[ym] = idx_arr

    is_hit_arr = df["is_hit"].values.astype(np.float64)
    implied_arr = df["implied_p_norm"].values.astype(np.float64)
    odds_arr = df["odds"].values.astype(np.float64)

    lifts = np.full((n_resamples, n_groups), np.nan)
    evs = np.full((n_resamples, n_groups), np.nan)

    for it in range(n_resamples):
        race_weights = np.zeros(n_races, dtype=np.float64)
        for ym, race_indices in month_to_race_indices.items():
            sampled = rng.choice(race_indices, size=len(race_indices), replace=True)
            np.add.at(race_weights, sampled, 1.0)
        combo_w = race_weights[combo_race_idx]
        n_g = np.bincount(g_arr, weights=combo_w, minlength=n_groups)
        h_g = np.bincount(g_arr, weights=combo_w * is_hit_arr, minlength=n_groups)
        i_g = np.bincount(g_arr, weights=combo_w * implied_arr, minlength=n_groups)
        o_g = np.bincount(g_arr, weights=combo_w * odds_arr, minlength=n_groups)
        with np.errstate(divide="ignore", invalid="ignore"):
            actual = np.where(n_g > 0, h_g / n_g, np.nan)
            implied = np.where(n_g > 0, i_g / n_g, np.nan)
            mean_o = np.where(n_g > 0, o_g / n_g, np.nan)
            lift = np.where(implied > 0, actual / implied, np.nan)
            ev = mean_o * actual
        lifts[it] = lift
        evs[it] = ev

        if (it + 1) % 200 == 0:
            logger.info("[%s] bootstrap %d / %d", group_by, it + 1, n_resamples)

    rows = []
    for k, g in enumerate(groups):
        lcol = lifts[:, k]
        lcol = lcol[~np.isnan(lcol)]
        ecol = evs[:, k]
        ecol = ecol[~np.isnan(ecol)]
        if len(lcol) == 0 or len(ecol) == 0:
            continue
        rows.append({
            group_by:        g,
            "lift_boot_lo":  float(np.quantile(lcol, alpha / 2)),
            "lift_boot_hi":  float(np.quantile(lcol, 1 - alpha / 2)),
            "ev_boot_lo":    float(np.quantile(ecol, alpha / 2)),
            "ev_boot_hi":    float(np.quantile(ecol, 1 - alpha / 2)),
        })
    return pd.DataFrame(rows)


def evaluate_segment_distortion(
    seg_df: pd.DataFrame, group_by: str, min_n: int = 1000,
) -> list[dict]:
    """
    Step 2 採用基準（B-1 PLAN §3 + ev > 1.0）:
      - n >= min_n
      - lift_boot_lo > 1.0（CI 下限が 1.0 を超える = 確信を持って割安）
      - ev_all_buy > 1.0 かつ ev_boot_lo > 1.0（控除率を破る確信あり）
    """
    flagged = []
    for _, row in seg_df.iterrows():
        if row["n"] < min_n:
            continue
        lift_lo = row.get("lift_boot_lo", np.nan)
        ev = row.get("ev_all_buy", np.nan)
        ev_lo = row.get("ev_boot_lo", np.nan)
        if (
            not np.isnan(lift_lo) and lift_lo > 1.0
            and not np.isnan(ev) and ev > 1.0
            and not np.isnan(ev_lo) and ev_lo > 1.0
        ):
            flagged.append({
                group_by:       row[group_by],
                "n":            int(row["n"]),
                "lift":         row["lift"],
                "lift_boot_lo": lift_lo,
                "ev_all_buy":   ev,
                "ev_boot_lo":   ev_lo,
                "ev_boot_hi":   row.get("ev_boot_hi", np.nan),
            })
    return flagged


# ---------------------------------------------------------------------------
# パイプライン
# ---------------------------------------------------------------------------

def run_segment(
    df: pd.DataFrame,
    label: str,
    n_bootstrap: int,
    output_dir: Path,
) -> pd.DataFrame:
    """1 期間分: ビン集計 + bootstrap CI + CSV 保存。"""
    summary = bin_summary(df)
    if n_bootstrap > 0:
        boot = bootstrap_lift_ci(df, n_resamples=n_bootstrap)
        summary = summary.merge(boot, on=["bin_lower", "bin_upper"], how="left")
    out_csv = output_dir / f"market_efficiency_{label}.csv"
    summary.to_csv(out_csv, index=False)
    logger.info("CSV 保存: %s", out_csv)
    return summary


def run_subsegment_group(
    df_focus: pd.DataFrame,
    group_by: str,
    label: str,
    n_bootstrap: int,
    output_dir: Path,
    min_n: int,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    focus 帯内で 1 group 軸の集計 + bootstrap + CSV 保存 + 採用判定。
    """
    df_g = add_group_column(df_focus, group_by)
    seg = segment_summary_within_focus(df_g, group_by)
    if n_bootstrap > 0:
        boot = bootstrap_segment_lift_ci(df_g, group_by, n_resamples=n_bootstrap)
        seg = seg.merge(boot, on=group_by, how="left")
    seg = seg.sort_values("ev_all_buy", ascending=False).reset_index(drop=True)
    out_csv = output_dir / f"market_efficiency_segment_{group_by}_{label}.csv"
    seg.to_csv(out_csv, index=False)
    logger.info("[%s] CSV 保存: %s", group_by, out_csv)
    flagged = evaluate_segment_distortion(seg, group_by, min_n=min_n)
    return seg, flagged


def run_subsegment_group_2axis(
    df_focus_with_group: pd.DataFrame,
    group_col_name: str,
    label: str,
    n_bootstrap: int,
    output_dir: Path,
    min_n: int,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    2 軸組合せ版（_group 列が既に付与されたフレームを受け取る）。
    既存の segment_summary_within_focus / bootstrap_segment_lift_ci を再利用。
    """
    seg = segment_summary_within_focus(df_focus_with_group, group_col_name)
    if n_bootstrap > 0:
        boot = bootstrap_segment_lift_ci(
            df_focus_with_group, group_col_name, n_resamples=n_bootstrap,
        )
        seg = seg.merge(boot, on=group_col_name, how="left")
    seg = seg.sort_values("ev_all_buy", ascending=False).reset_index(drop=True)
    out_csv = output_dir / f"market_efficiency_segment_{group_col_name}_{label}.csv"
    seg.to_csv(out_csv, index=False)
    logger.info("[%s] CSV 保存: %s", group_col_name, out_csv)
    flagged = evaluate_segment_distortion(seg, group_col_name, min_n=min_n)
    return seg, flagged


def _format_2axis_group_value(gval: str, axis1: str, axis2: str) -> str:
    """'<v1>|<v2>' を可読形式に整形。stadium 部分があれば名前付与。"""
    parts = gval.split("|", 1)
    if len(parts) != 2:
        return gval
    v1, v2 = parts
    if axis1 == "stadium":
        try:
            v1 = f"{int(v1)}.{STADIUM_NAMES.get(int(v1), '?')}"
        except ValueError:
            pass
    if axis2 == "stadium":
        try:
            v2 = f"{int(v2)}.{STADIUM_NAMES.get(int(v2), '?')}"
        except ValueError:
            pass
    return f"{v1} | {v2}"


def print_segment_table(seg: pd.DataFrame, group_by: str, min_n: int) -> None:
    """サブセグメント集計テーブルを print。"""
    print()
    print(f"  [group_by = {group_by}] (focus bin only, sorted by ev_all_buy desc)")
    name_col_w = max(len(group_by), 12)
    header = (
        f"  {group_by:>{name_col_w}}  {'n':>6}  {'lift':>5}  "
        f"{'lift CI':>16}  {'ev':>5}  {'ev CI':>16}  flag"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for _, r in seg.iterrows():
        if r["n"] < min_n:
            continue
        lift_ci = (
            f"[{r.get('lift_boot_lo', float('nan')):.2f}, "
            f"{r.get('lift_boot_hi', float('nan')):.2f}]"
        )
        ev_ci = (
            f"[{r.get('ev_boot_lo', float('nan')):.2f}, "
            f"{r.get('ev_boot_hi', float('nan')):.2f}]"
        )
        flag = (
            "*"
            if (
                not np.isnan(r.get("lift_boot_lo", np.nan))
                and r.get("lift_boot_lo", 0) > 1.0
                and r["ev_all_buy"] > 1.0
                and r.get("ev_boot_lo", 0) > 1.0
            )
            else ""
        )
        gval_str = (
            f"{int(r[group_by])}.{STADIUM_NAMES.get(int(r[group_by]), '?')}"
            if group_by == "stadium"
            else str(r[group_by])
        )
        print(
            f"  {gval_str:>{name_col_w}}  {int(r['n']):>6}  "
            f"{r['lift']:>5.2f}  {lift_ci:>16}  "
            f"{r['ev_all_buy']:>5.2f}  {ev_ci:>16}  {flag}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="フェーズ B-1 Step 1/2: 市場効率の歪み分析",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", type=str, required=True, help="開始 YYYY-MM")
    parser.add_argument("--end",   type=str, required=True, help="終了 YYYY-MM (inclusive)")
    parser.add_argument("--bet-type", choices=["trifecta"], default="trifecta")
    parser.add_argument("--split-halves", action="store_true",
                        help="Step 1: 期間を前半/後半 2 分割して個別集計")
    parser.add_argument("--bootstrap", type=int, default=2000,
                        help="Bootstrap 回数（0 で無効化）")
    parser.add_argument("--min-bin-n", type=int, default=1000,
                        help="採用判定の最小ビン件数")
    # Step 2 用引数
    parser.add_argument(
        "--group-by", type=str, nargs="*", default=[],
        choices=["stadium", "course", "odds_band", "month"],
        help="Step 2: focus 帯内のサブセグメント分析（複数指定可）",
    )
    parser.add_argument(
        "--group-by-2axis", type=str, nargs="*", default=[],
        help="Step 2: 2 軸組合せサブセグメント分析（'stadium,odds_band' 形式、複数指定可）",
    )
    parser.add_argument(
        "--focus-bin-lower", type=float, default=0.10,
        help="Step 2: focus 帯の implied_p_norm 下限（デフォルト 0.10）",
    )
    parser.add_argument(
        "--focus-bin-upper", type=float, default=0.50,
        help="Step 2: focus 帯の implied_p_norm 上限（デフォルト 0.50）",
    )
    parser.add_argument(
        "--skip-step1", action="store_true",
        help="Step 1（全期間ビン集計とプロット）をスキップ",
    )
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else ARTIFACTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    start = parse_year_month(args.start)
    end = parse_year_month(args.end)

    # ── 1. データロード ────────────────────────────────
    odds = load_odds_period(start, end)
    results = load_winning_combos(start, end)

    # ── 2. 暗黙確率計算 + hit ラベル付与 ───────────────
    odds = compute_implied_probs(odds)
    df = attach_hit_label(odds, results)

    full_label = f"{args.start}_{args.end}_{args.bet_type}"

    # ── 3. 全期間ビン集計（Step 1）─────────────────────
    if not args.skip_step1:
        full_summary = run_segment(df, full_label, args.bootstrap, output_dir)
    else:
        full_summary = bin_summary(df)
        logger.info("Step 1 をスキップ（--skip-step1）")

    # ── 4. プロット（全期間のみ、Step 1 実行時のみ）─────
    if not args.skip_step1:
        plot_calibration(
            full_summary,
            output_dir / f"market_efficiency_{full_label}.png",
            title=f"Market efficiency calibration ({args.start} to {args.end}, {args.bet_type})",
        )

    # ── 5. 前半 / 後半 ─────────────────────────────────
    half_results: dict[str, pd.DataFrame] = {}
    if args.split_halves:
        all_months = sorted(df["year_month"].unique())
        if len(all_months) < 2:
            logger.warning("split-halves: 月数不足のためスキップ")
        else:
            mid = len(all_months) // 2
            first_months = all_months[:mid]
            second_months = all_months[mid:]
            df_h1 = df[df["year_month"].isin(first_months)]
            df_h2 = df[df["year_month"].isin(second_months)]
            label_h1 = f"{first_months[0]}_{first_months[-1]}_{args.bet_type}"
            label_h2 = f"{second_months[0]}_{second_months[-1]}_{args.bet_type}"
            half_results[label_h1] = run_segment(df_h1, label_h1, args.bootstrap, output_dir)
            half_results[label_h2] = run_segment(df_h2, label_h2, args.bootstrap, output_dir)

    # ── 6. 採用判定レポート ────────────────────────────
    flagged = evaluate_distortion(full_summary, min_n=args.min_bin_n)

    print()
    print("=" * 78)
    print(f"  Market efficiency distortion report [{args.start} to {args.end}, {args.bet_type}]")
    print("=" * 78)
    print(f"  total bins: {len(full_summary)}, "
          f"flagged (n>={args.min_bin_n}, |lift-1|>=0.10/0.15, CI excl. 1): "
          f"{len(flagged)}")

    print()
    print(f"  {'bin':>22}  {'n':>8}  {'actual_p':>9}  {'implied':>9}  "
          f"{'lift':>6}  {'90% boot CI':>20}")
    print("  " + "-" * 78)
    for _, r in full_summary.iterrows():
        bin_str = f"[{r['bin_lower']:.4f}, {r['bin_upper']:.4f})"
        ci = f"[{r.get('lift_boot_lo', float('nan')):.3f}, {r.get('lift_boot_hi', float('nan')):.3f}]"
        print(f"  {bin_str:>22}  {int(r['n']):>8}  {r['mean_actual_p']:>9.4f}  "
              f"{r['mean_implied_p_norm']:>9.4f}  {r['lift']:>6.3f}  {ci:>20}")

    if flagged:
        print()
        print("  >> Flagged bins (meets criteria):")
        for f in flagged:
            bin_str = f"[{f['bin_lower']:.4f}, {f['bin_upper']:.4f})"
            ci_str = f"[{f['lift_boot_lo']:.3f}, {f['lift_boot_hi']:.3f}]"
            print(f"    {bin_str}  n={f['n']:>6}  lift={f['lift']:.3f}  "
                  f"CI={ci_str}  {f['direction']}")
    else:
        print()
        print("  >> No bin meets adoption criteria -> B-1 retreat candidate")

    if args.split_halves and len(half_results) == 2:
        labels = list(half_results.keys())
        h1_summary = half_results[labels[0]]
        h2_summary = half_results[labels[1]]
        print()
        print(f"  [first half ({labels[0]}) vs second half ({labels[1]}) same-direction check]")
        print(f"  {'bin':>22}  {'n_h1':>6}  {'lift_h1':>8}  {'n_h2':>6}  "
              f"{'lift_h2':>8}  {'same dir?'}")
        print("  " + "-" * 70)
        for _, r in full_summary.iterrows():
            if r["n"] < args.min_bin_n:
                continue
            h1 = h1_summary[
                (h1_summary["bin_lower"] == r["bin_lower"])
                & (h1_summary["bin_upper"] == r["bin_upper"])
            ]
            h2 = h2_summary[
                (h2_summary["bin_lower"] == r["bin_lower"])
                & (h2_summary["bin_upper"] == r["bin_upper"])
            ]
            if h1.empty or h2.empty:
                continue
            lift_h1 = float(h1["lift"].iloc[0])
            lift_h2 = float(h2["lift"].iloc[0])
            same_dir = (
                (lift_h1 > 1.0 and lift_h2 > 1.0)
                or (lift_h1 < 1.0 and lift_h2 < 1.0)
            )
            bin_str = f"[{r['bin_lower']:.4f}, {r['bin_upper']:.4f})"
            print(f"  {bin_str:>22}  {int(h1['n'].iloc[0]):>6}  {lift_h1:>8.3f}  "
                  f"{int(h2['n'].iloc[0]):>6}  {lift_h2:>8.3f}  "
                  f"{'YES' if same_dir else 'NO'}")

    # ── 7. Step 2: focus 帯内サブセグメント分析 ────────
    if args.group_by or args.group_by_2axis:
        focus_lo = args.focus_bin_lower
        focus_hi = args.focus_bin_upper
        df_focus = df[
            (df["implied_p_norm"] >= focus_lo)
            & (df["implied_p_norm"] < focus_hi)
        ]
        n_focus = len(df_focus)
        n_focus_races = df_focus["race_id"].nunique()
        n_focus_hits = int(df_focus["is_hit"].sum())

        print()
        print("=" * 78)
        print(f"  Step 2: Sub-segment analysis (focus implied_p_norm in [{focus_lo}, {focus_hi}))")
        print("=" * 78)
        print(f"  focus combos: {n_focus:,} / {n_focus_races:,} races / "
              f"{n_focus_hits:,} hits, mean odds = {df_focus['odds'].mean():.2f}")

        focus_label = f"focus_{focus_lo:.2f}-{focus_hi:.2f}_{full_label}"
        all_flagged: dict[str, list[dict]] = {}

        # 単軸
        for gb in args.group_by:
            seg, flagged = run_subsegment_group(
                df_focus,
                group_by=gb,
                label=focus_label,
                n_bootstrap=args.bootstrap,
                output_dir=output_dir,
                min_n=args.min_bin_n,
            )
            print_segment_table(seg, gb, args.min_bin_n)
            all_flagged[gb] = flagged

        # 2 軸組合せ
        valid_axes = {"stadium", "course", "odds_band", "month"}
        for spec in args.group_by_2axis:
            parts = [p.strip() for p in spec.split(",")]
            if len(parts) != 2 or parts[0] not in valid_axes or parts[1] not in valid_axes:
                logger.warning("Invalid 2axis spec: %s (expected 'axis1,axis2')", spec)
                continue
            ax1, ax2 = parts
            combined_name = f"{ax1}X{ax2}"
            df_2axis = add_2axis_group_column(df_focus, ax1, ax2)
            seg, flagged = run_subsegment_group_2axis(
                df_2axis,
                group_col_name=combined_name,
                label=focus_label,
                n_bootstrap=args.bootstrap,
                output_dir=output_dir,
                min_n=args.min_bin_n,
            )
            # 上位/採用 cell をハイライト表示
            print()
            print(f"  [group_by = {combined_name}] (focus bin only, n>=%d, sorted by ev_all_buy desc, top 15)" % args.min_bin_n)
            valid_seg = seg[seg["n"] >= args.min_bin_n]
            print(f"  cells with n>={args.min_bin_n}: {len(valid_seg)} / {len(seg)} total")
            if not valid_seg.empty:
                head_w = max(len(combined_name), 28)
                print(
                    f"  {combined_name:>{head_w}}  {'n':>5}  {'lift':>5}  "
                    f"{'lift CI':>14}  {'ev':>5}  {'ev CI':>14}  flag"
                )
                print("  " + "-" * (head_w + 60))
                for _, r in valid_seg.head(15).iterrows():
                    lift_ci = (
                        f"[{r.get('lift_boot_lo', float('nan')):.2f},"
                        f"{r.get('lift_boot_hi', float('nan')):.2f}]"
                    )
                    ev_ci = (
                        f"[{r.get('ev_boot_lo', float('nan')):.2f},"
                        f"{r.get('ev_boot_hi', float('nan')):.2f}]"
                    )
                    flag = (
                        "*"
                        if (
                            not np.isnan(r.get("lift_boot_lo", np.nan))
                            and r.get("lift_boot_lo", 0) > 1.0
                            and r["ev_all_buy"] > 1.0
                            and r.get("ev_boot_lo", 0) > 1.0
                        )
                        else ""
                    )
                    label_str = _format_2axis_group_value(str(r[combined_name]), ax1, ax2)
                    print(
                        f"  {label_str:>{head_w}}  {int(r['n']):>5}  "
                        f"{r['lift']:>5.2f}  {lift_ci:>14}  "
                        f"{r['ev_all_buy']:>5.2f}  {ev_ci:>14}  {flag}"
                    )
            all_flagged[combined_name] = flagged

        # 採用判定サマリー
        print()
        print("  >> Step 2 adoption summary (n>=%d, lift_boot_lo>1.0, ev_all_buy>1.0, ev_boot_lo>1.0):" % args.min_bin_n)
        for gb, flist in all_flagged.items():
            if flist:
                print(f"    [{gb}] {len(flist)} flagged segment(s):")
                for f in flist:
                    val = f[gb]
                    if "X" in gb:
                        ax1, ax2 = gb.split("X", 1)
                        val = _format_2axis_group_value(str(val), ax1, ax2)
                    print(
                        f"      {gb}={val}, n={f['n']}, lift={f['lift']:.3f} "
                        f"(CI lo={f['lift_boot_lo']:.3f}), "
                        f"ev={f['ev_all_buy']:.3f} (CI=[{f['ev_boot_lo']:.3f}, {f['ev_boot_hi']:.3f}])"
                    )
            else:
                print(f"    [{gb}] no flagged segment")

        any_flagged = any(len(v) > 0 for v in all_flagged.values())
        print()
        if any_flagged:
            print("  ====> Step 3 (strategy backtest) candidate found.")
        else:
            print("  ====> No subsegment beats takeout. B-1 retreat candidate.")

    print()
    print(f"  output: {output_dir}/market_efficiency_*.csv / .png")
    print("=" * 78)
    print()


if __name__ == "__main__":
    main()
