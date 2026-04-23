"""
run_predict.extract_bet_candidates のユニットテスト。

pandas / DB 等の重い依存を避けるため、run_predict.py の冒頭 import を
パッチしてから対象関数だけを取り出す。
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_extract_fn():
    """run_predict.py の冒頭 import を捌きつつ対象関数だけロードする"""
    root = Path(__file__).resolve().parents[1] / "src"
    script_path = root / "scripts" / "run_predict.py"

    # run_predict.py の冒頭で pandas / collector / features / model / notifier を
    # import するため、それらをダミーモジュールに差し替えてから exec する。
    stubs = {
        "pandas": types.ModuleType("pandas"),
        "collector.db_writer": types.ModuleType("collector.db_writer"),
        "features.feature_builder": types.ModuleType("features.feature_builder"),
        "model.predictor": types.ModuleType("model.predictor"),
    }
    # スタブに必要なシンボルを埋める
    stubs["collector.db_writer"].get_connection = lambda *a, **k: None
    stubs["collector.db_writer"].upsert_prediction = lambda *a, **k: None
    stubs["features.feature_builder"].build_features = lambda *a, **k: None
    stubs["model.predictor"].calc_expected_values = lambda *a, **k: None
    stubs["model.predictor"].calc_trifecta_probs = lambda *a, **k: None
    stubs["model.predictor"].load_model = lambda *a, **k: None
    stubs["model.predictor"].predict_win_prob = lambda *a, **k: None

    # notifier はテスト対象でも間接依存にはなるので実モジュールをロードできるよう
    # src をパスに通しておく。
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    saved = {}
    for name, mod in stubs.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod
        # 親パッケージも必要なら stub
        parent = name.split(".")[0]
        if parent not in sys.modules:
            sys.modules[parent] = types.ModuleType(parent)

    try:
        spec = importlib.util.spec_from_file_location("run_predict_for_test", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.extract_bet_candidates
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


extract_bet_candidates = _load_extract_fn()


def _make_results(entries: list[tuple[str, float, float]]) -> list[dict]:
    """(combination, win_probability, expected_value) のタプル列から results dict を作る"""
    return [
        {"combination": c, "win_probability": p, "expected_value": ev}
        for c, p, ev in entries
    ]


BASE_ODDS = {
    "1-2-3": 150.0,
    "1-3-4": 50.0,     # オッズ<100 で除外
    "2-3-1": 200.0,    # 1着=2 で除外
    "3-4-5": 300.0,
    "4-5-6": 400.0,    # 1着=4 で除外
    "5-6-1": 500.0,    # 1着=5 で除外
    "6-1-2": 600.0,    # オッズ閾値OK・コース対象
    "1-4-5": 120.0,
}


class ExtractBetCandidatesTests(unittest.TestCase):
    def _call(self, results, **overrides):
        kwargs = dict(
            race_id="R1",
            stadium_id=1,
            race_no=12,
            prob_threshold=0.07,
            ev_threshold=2.0,
            min_odds=100.0,
            exclude_courses={2, 4, 5},
            exclude_stadiums={11},
            odds_dict=BASE_ODDS,
        )
        kwargs.update(overrides)
        return extract_bet_candidates(results, **kwargs)

    def test_happy_path_passes_thresholds(self):
        results = _make_results([
            ("1-2-3", 0.08, 2.5),   # pass
            ("3-4-5", 0.09, 3.0),   # pass
        ])
        got = self._call(results)
        combos = [c["combination"] for c in got]
        self.assertEqual(sorted(combos), ["1-2-3", "3-4-5"])
        # odds が埋め込まれている
        self.assertEqual(got[0]["stadium_id"], 1)
        self.assertEqual(got[0]["race_no"], 12)
        self.assertIn("odds", got[0])

    def test_prob_threshold_filters(self):
        results = _make_results([("1-2-3", 0.06, 5.0)])
        self.assertEqual(self._call(results), [])

    def test_ev_threshold_filters(self):
        results = _make_results([("1-2-3", 0.1, 1.5)])
        self.assertEqual(self._call(results), [])

    def test_min_odds_filters(self):
        # 1-3-4 は odds=50 で min_odds=100 未満
        results = _make_results([("1-3-4", 0.1, 3.0)])
        self.assertEqual(self._call(results), [])

    def test_exclude_courses_filters_first_boat(self):
        results = _make_results([
            ("2-3-1", 0.1, 3.0),   # 1着=2 除外
            ("4-5-6", 0.1, 3.0),   # 1着=4 除外
            ("5-6-1", 0.1, 3.0),   # 1着=5 除外
            ("6-1-2", 0.1, 3.0),   # 1着=6 許容（exclude=2,4,5）
        ])
        got = self._call(results)
        self.assertEqual([c["combination"] for c in got], ["6-1-2"])

    def test_exclude_stadium_returns_empty(self):
        results = _make_results([("1-2-3", 0.1, 3.0)])
        got = self._call(results, stadium_id=11)
        self.assertEqual(got, [])

    def test_skip_when_ev_is_none(self):
        results = [
            {"combination": "1-2-3", "win_probability": 0.1, "expected_value": None},
        ]
        self.assertEqual(self._call(results), [])

    def test_skip_when_combo_missing_from_odds(self):
        results = _make_results([("9-9-9", 0.1, 3.0)])  # 存在しない combo
        self.assertEqual(self._call(results), [])

    def test_min_odds_none_does_not_filter(self):
        results = _make_results([("1-3-4", 0.1, 3.0)])  # odds=50
        got = self._call(results, min_odds=None)
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()
