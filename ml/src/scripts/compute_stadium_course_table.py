"""
24 場 × 6 コースの 1 着率テーブルを K ファイル履歴から集計する。

PoC b（場×コース交互作用）用。出力テーブルを stadium_features.py に
定数として埋め込み、学習時はそれを map で適用する（ルックアヘッド回避）。

集計期間: train 期間と同じ範囲を引数で指定。

使い方:
  py -3.12 ml/src/scripts/compute_stadium_course_table.py \
      --start-year 2023 --start-month 1 --end-year 2025 --end-month 11
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from collector.history_downloader import load_history_range  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--start-month", type=int, default=1)
    p.add_argument("--end-year", type=int, required=True)
    p.add_argument("--end-month", type=int, default=12)
    p.add_argument("--out", type=str,
                   default=str(ROOT / "artifacts" / "stadium_course_win_rate.json"))
    args = p.parse_args()

    print(f"loading history {args.start_year}-{args.start_month:02d} "
          f"~ {args.end_year}-{args.end_month:02d}")
    df = load_history_range(
        start_year=args.start_year, start_month=args.start_month,
        end_year=args.end_year, end_month=args.end_month,
    )
    print(f"  rows: {len(df):,}")

    df = df.dropna(subset=["finish_position"])
    df = df[df["finish_position"].between(1, 6)]

    # boat_no がコース番号（1〜6）と一致
    df["is_first"] = (df["finish_position"] == 1).astype(int)
    grp = df.groupby(["stadium_id", "boat_no"]).agg(
        wins=("is_first", "sum"),
        races=("is_first", "count"),
    ).reset_index()
    grp["win_rate"] = grp["wins"] / grp["races"].clip(lower=1)

    table = {}
    for _, row in grp.iterrows():
        stadium = int(row["stadium_id"])
        course = int(row["boat_no"])
        wr = float(row["win_rate"])
        table.setdefault(stadium, {})[course] = round(wr, 4)

    # 全国平均（フォールバック）
    overall = (
        df.groupby("boat_no")["is_first"].mean()
        .round(4).to_dict()
    )
    overall_mean = float(df["is_first"].mean())
    print(f"  overall mean (1st rate): {overall_mean:.4f}")
    print(f"  per-course overall: {overall}")

    out = {
        "period": f"{args.start_year}-{args.start_month:02d}~{args.end_year}-{args.end_month:02d}",
        "n_rows": int(len(df)),
        "by_stadium": {str(k): {str(c): v for c, v in d.items()}
                        for k, d in table.items()},
        "overall_per_course": {str(c): float(v) for c, v in overall.items()},
        "overall_mean": overall_mean,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"saved → {out_path}")


if __name__ == "__main__":
    main()
