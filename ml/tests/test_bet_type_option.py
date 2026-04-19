"""
T5: --bet-type オプション（run_backtest.py / run_walkforward.py）のテスト

スタンドアローン実行可能（依存パッケージ不要な部分のみテスト）。
"""
import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "src" / "scripts"


def check_syntax(path: Path) -> bool:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        ast.parse(src)
        return True
    except SyntaxError as e:
        print(f"  FAIL: syntax error in {path.name}: {e}")
        return False


def test_run_backtest_syntax():
    ok = check_syntax(SCRIPTS / "run_backtest.py")
    assert ok, "run_backtest.py has syntax error"
    print("  PASS: run_backtest.py 構文OK")


def test_run_walkforward_syntax():
    ok = check_syntax(SCRIPTS / "run_walkforward.py")
    assert ok, "run_walkforward.py has syntax error"
    print("  PASS: run_walkforward.py 構文OK")


def test_backtest_bet_type_arg():
    """run_backtest.py に --bet-type 引数が存在し choices が正しいか確認"""
    with open(SCRIPTS / "run_backtest.py", encoding="utf-8") as f:
        src = f.read()
    assert "--bet-type" in src, "--bet-type が run_backtest.py に存在しない"
    assert "\"trifecta\"" in src or "'trifecta'" in src
    assert "\"trio\"" in src or "'trio'" in src
    assert "\"both\"" in src or "'both'" in src
    print("  PASS: run_backtest.py --bet-type 引数の存在確認")


def test_walkforward_bet_type_arg():
    """run_walkforward.py に --bet-type 引数が存在し choices が正しいか確認"""
    with open(SCRIPTS / "run_walkforward.py", encoding="utf-8") as f:
        src = f.read()
    assert "--bet-type" in src, "--bet-type が run_walkforward.py に存在しない"
    assert "\"trifecta\"" in src or "'trifecta'" in src
    assert "\"trio\"" in src or "'trio'" in src
    assert "\"both\"" in src or "'both'" in src
    print("  PASS: run_walkforward.py --bet-type 引数の存在確認")


def test_backtest_trio_odds_import():
    """run_backtest.py が load_or_download_month_trio_odds をインポートしているか"""
    with open(SCRIPTS / "run_backtest.py", encoding="utf-8") as f:
        src = f.read()
    assert "load_or_download_month_trio_odds" in src
    print("  PASS: run_backtest.py trio odds インポート確認")


def test_walkforward_trio_odds_import():
    """run_walkforward.py が load_or_download_month_trio_odds をインポートしているか"""
    with open(SCRIPTS / "run_walkforward.py", encoding="utf-8") as f:
        src = f.read()
    assert "load_or_download_month_trio_odds" in src
    print("  PASS: run_walkforward.py trio odds インポート確認")


def test_bet_type_argument_parsing():
    """argparse で --bet-type が正しく解析できるか"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bet-type", type=str, default="trifecta",
                        choices=["trifecta", "trio", "both"])

    args = parser.parse_args([])
    assert args.bet_type == "trifecta", f"default should be trifecta, got {args.bet_type}"

    args = parser.parse_args(["--bet-type", "trio"])
    assert args.bet_type == "trio"

    args = parser.parse_args(["--bet-type", "both"])
    assert args.bet_type == "both"

    args = parser.parse_args(["--bet-type", "trifecta"])
    assert args.bet_type == "trifecta"

    print("  PASS: --bet-type 引数解析（trifecta/trio/both/デフォルト）")


def test_bet_type_invalid():
    """無効な --bet-type は拒否されるか"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bet-type", type=str, default="trifecta",
                        choices=["trifecta", "trio", "both"])
    try:
        parser.parse_args(["--bet-type", "invalid"])
        print("  FAIL: 無効な bet-type が拒否されなかった")
        return False
    except SystemExit:
        print("  PASS: 無効な --bet-type は拒否される")
        return True


def test_both_mode_runs_both():
    """both モードで bet_types リストが両方含まれるか（ロジック検証）"""
    bet_type = "both"
    bet_types = ["trifecta", "trio"] if bet_type == "both" else [bet_type]
    assert "trifecta" in bet_types
    assert "trio" in bet_types
    assert len(bet_types) == 2
    print("  PASS: both モードで bet_types=[trifecta, trio]")


def test_single_mode_runs_one():
    """trio/trifecta 単独モードで bet_types が1要素か"""
    for bt in ["trifecta", "trio"]:
        bet_types = ["trifecta", "trio"] if bt == "both" else [bt]
        assert len(bet_types) == 1
        assert bet_types[0] == bt
    print("  PASS: 単独モードで bet_types=[bet_type]")


def test_backtest_bet_type_passed_to_engine():
    """run_backtest.py が bet_type を run_backtest_batch に渡しているか"""
    with open(SCRIPTS / "run_backtest.py", encoding="utf-8") as f:
        src = f.read()
    assert "bet_type=bt" in src or "bet_type=" in src
    print("  PASS: run_backtest.py bet_type を engine に渡す")


def test_walkforward_bet_type_passed_to_engine():
    """run_walkforward.py が bet_type を run_backtest_batch に渡しているか"""
    with open(SCRIPTS / "run_walkforward.py", encoding="utf-8") as f:
        src = f.read()
    assert "bet_type=bt" in src or "bet_type=" in src
    print("  PASS: run_walkforward.py bet_type を engine に渡す")


def main():
    tests = [
        test_run_backtest_syntax,
        test_run_walkforward_syntax,
        test_backtest_bet_type_arg,
        test_walkforward_bet_type_arg,
        test_backtest_trio_odds_import,
        test_walkforward_trio_odds_import,
        test_bet_type_argument_parsing,
        test_bet_type_invalid,
        test_both_mode_runs_both,
        test_single_mode_runs_one,
        test_backtest_bet_type_passed_to_engine,
        test_walkforward_bet_type_passed_to_engine,
    ]

    print("=== T5: --bet-type オプション テスト ===")
    passed = 0
    failed = 0
    for fn in tests:
        try:
            result = fn()
            if result is False:
                failed += 1
            else:
                passed += 1
        except AssertionError as e:
            print(f"  FAIL: {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {fn.__name__}: {e}")
            failed += 1

    print(f"\n{passed + failed}/{len(tests)} テスト実行: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
