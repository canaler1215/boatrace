"""
回帰防止テスト: 直近 N ランの ROI 中央値の 70% を下回る結果を検出する。

目的:
  agent が閾値を過度に操作して見かけ上の ROI を悪化させるのを防ぐ。
  kpi_history.jsonl に十分な履歴がない場合は SKIP（CI フレンドリー）。

実行:
  pytest ml/tests/test_no_regression.py -v

環境変数:
  KPI_HISTORY_PATH  ... kpi_history.jsonl のパス（デフォルト: artifacts/kpi_history.jsonl）
  REGRESSION_WINDOW ... 参照する直近ラン数（デフォルト: 6）
  REGRESSION_FLOOR  ... 中央値に対する許容下限の割合（デフォルト: 0.70）
"""
import json
import os
import statistics
from pathlib import Path

import pytest

ARTIFACTS_DIR = Path(__file__).parents[2] / "artifacts"

DEFAULT_HISTORY_PATH = ARTIFACTS_DIR / "kpi_history.jsonl"
REGRESSION_WINDOW = int(os.environ.get("REGRESSION_WINDOW", 6))
REGRESSION_FLOOR = float(os.environ.get("REGRESSION_FLOOR", 0.70))
MIN_HISTORY_FOR_TEST = 2  # これ未満の履歴ならスキップ


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def get_history_path() -> Path:
    env_path = os.environ.get("KPI_HISTORY_PATH")
    return Path(env_path) if env_path else DEFAULT_HISTORY_PATH


class TestNoRegression:
    """kpi_history.jsonl の直近 N ランに対して ROI 回帰を検出する。"""

    def setup_method(self):
        self.history_path = get_history_path()
        self.records = load_history(self.history_path)

    def test_history_file_readable(self):
        """kpi_history.jsonl が存在しない場合はスキップ（CI 初回は正常）。"""
        if not self.history_path.exists():
            pytest.skip(f"kpi_history.jsonl not found: {self.history_path}")

    def test_roi_no_regression(self):
        """
        直近 REGRESSION_WINDOW ランの ROI 中央値を基準に、
        最新ラン ROI が中央値の REGRESSION_FLOOR 倍以上であることを検証する。

        例: 中央値 ROI = 800%, floor = 0.70 → 最新ラン ROI >= 560% が必要
        """
        if not self.history_path.exists():
            pytest.skip(f"kpi_history.jsonl not found: {self.history_path}")

        if len(self.records) < MIN_HISTORY_FOR_TEST:
            pytest.skip(
                f"Not enough history ({len(self.records)} runs < {MIN_HISTORY_FOR_TEST}). "
                "Skipping regression check."
            )

        # 直近 N ランを取得（最新が末尾）
        window_records = self.records[-REGRESSION_WINDOW:]
        roi_values = [r["roi_pct"] for r in window_records]

        if len(roi_values) < MIN_HISTORY_FOR_TEST:
            pytest.skip(
                f"Window has too few records ({len(roi_values)}). Skipping."
            )

        # 最新ランを除いた中央値 vs 最新ラン（最新が1件しかないなら全体で比較）
        if len(roi_values) >= 2:
            baseline_values = roi_values[:-1]
            latest_roi = roi_values[-1]
        else:
            baseline_values = roi_values
            latest_roi = roi_values[-1]

        baseline_median = statistics.median(baseline_values)
        threshold = baseline_median * REGRESSION_FLOOR

        latest_period = window_records[-1].get("period", "unknown")
        baseline_periods = [r.get("period", "?") for r in window_records[:-1]]

        print(f"\n  [regression] 最新ラン  : period={latest_period}, ROI={latest_roi:+.1f}%")
        print(f"  [regression] ベースライン: {baseline_periods}")
        print(f"  [regression] 中央値ROI  : {baseline_median:+.1f}%")
        print(f"  [regression] 閾値 ({REGRESSION_FLOOR:.0%}): {threshold:+.1f}%")

        assert latest_roi >= threshold, (
            f"ROI 回帰を検出: 最新ラン {latest_roi:+.1f}% < 閾値 {threshold:+.1f}% "
            f"(直近中央値 {baseline_median:+.1f}% × {REGRESSION_FLOOR:.0%})\n"
            f"  最新期間: {latest_period}\n"
            f"  ベースライン期間: {baseline_periods}\n"
            f"  → run_segment_analysis.py や run_calibration.py で原因を調査してください"
        )

    def test_zone_not_danger(self):
        """最新ランのゾーンが danger（ROI < 0%）でないことを確認する。"""
        if not self.history_path.exists():
            pytest.skip(f"kpi_history.jsonl not found: {self.history_path}")

        if not self.records:
            pytest.skip("No records in kpi_history.jsonl")

        latest = self.records[-1]
        zone = latest.get("zone", "unknown")
        roi = latest.get("roi_pct", 0.0)
        period = latest.get("period", "unknown")

        print(f"\n  [regression] 最新ゾーン: {zone}, ROI={roi:+.1f}%, period={period}")

        assert zone != "danger", (
            f"最新ラン ({period}) のゾーンが danger (ROI={roi:+.1f}%)。\n"
            f"  → 即時停止して run_calibration.py + run_segment_analysis.py で原因分析が必要です"
        )

    def test_consecutive_warning_zones(self):
        """
        直近 2 ラン連続で warning（ROI 0–299%）またはそれ以下の場合に失敗する。
        CLAUDE.md 停止条件: ROI < 300% が 2 ヶ月連続 → 一時停止。
        """
        if not self.history_path.exists():
            pytest.skip(f"kpi_history.jsonl not found: {self.history_path}")

        if len(self.records) < 2:
            pytest.skip("Not enough records for consecutive check")

        recent_two = self.records[-2:]
        bad_zones = {"warning", "danger"}
        consecutive_bad = all(r.get("zone", "normal") in bad_zones for r in recent_two)

        if consecutive_bad:
            periods = [r.get("period", "?") for r in recent_two]
            rois = [r.get("roi_pct", 0.0) for r in recent_two]
            raise AssertionError(
                f"2 ラン連続で warning/danger ゾーン: {list(zip(periods, rois))}\n"
                f"  → run_retrain.py での再学習を検討してください"
            )
