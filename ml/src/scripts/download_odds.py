"""
過去の 3 連単最終オッズを boatrace.jp からダウンロードしてキャッシュする

使い方:
  # 2025 年 12 月分のオッズをダウンロード
  python download_odds.py --year 2025 --month 12

  # キャッシュが既にあれば上書きしない（デフォルト）
  python download_odds.py --year 2025 --month 12

  # 強制再ダウンロード
  python download_odds.py --year 2025 --month 12 --force

事前要件:
  - 対象月の K ファイルが data/history/ にキャッシュ済みであること
    （未取得の場合は自動ダウンロード）
  - boatrace.jp の過去データ保持期間: 約 2018 年以降

出力:
  data/odds/odds_{YYYYMM}.parquet

所要時間の目安:
  1 ヶ月 ≒ 3,600 レース × 1.5 秒 ≒ 90 分
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from collector.history_downloader import DATA_DIR
from collector.odds_downloader import ODDS_DIR, _cache_path, load_or_download_month_odds
from scripts.run_backtest import load_month_data   # K ファイル取得を再利用

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="競艇 3 連単オッズをダウンロード・キャッシュする",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--year",  type=int, required=True, help="対象年")
    parser.add_argument("--month", type=int, required=True, help="対象月（1–12）")
    parser.add_argument(
        "--force",
        action="store_true",
        help="キャッシュが存在しても再ダウンロードする",
    )
    args = parser.parse_args()

    cache_path = _cache_path(args.year, args.month)

    if cache_path.exists() and not args.force:
        logger.info(
            "Cache already exists: %s  (use --force to re-download)",
            cache_path,
        )
        sys.exit(0)

    if args.force and cache_path.exists():
        cache_path.unlink()
        logger.info("Removed existing cache: %s", cache_path)

    # ── 1. K ファイルを取得してレース一覧を作成 ─────────────
    logger.info("Loading K-file data for %d-%02d...", args.year, args.month)
    race_df = load_month_data(args.year, args.month)

    if race_df.empty:
        logger.error("No K-file data found for %d-%02d. Exiting.", args.year, args.month)
        sys.exit(1)

    logger.info("K-file records: %d", len(race_df))

    # ── 2. オッズダウンロード ────────────────────────────────
    odds_map = load_or_download_month_odds(args.year, args.month, race_df)

    if not odds_map:
        logger.error("Failed to download any odds data.")
        sys.exit(1)

    # ── 3. サマリー ──────────────────────────────────────────
    races_with_odds = len(odds_map)
    combos_total = sum(len(v) for v in odds_map.values())
    print()
    print(f"  対象: {args.year}-{args.month:02d}")
    print(f"  取得レース数 : {races_with_odds:,}")
    print(f"  取得オッズ数 : {combos_total:,}  (平均 {combos_total / max(races_with_odds,1):.1f} 組/レース)")
    print(f"  保存先       : {cache_path}")
    print()


if __name__ == "__main__":
    main()
