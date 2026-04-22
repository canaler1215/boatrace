"""A-3: update_predictions_final_odds_batch のユニットテスト

predictions.final_odds は「終了済みレースの確定オッズ」を1回だけ記録する。
WHERE final_odds IS NULL で上書きを防ぐ点、引数バインディングが
(odds_value, race_id, combination) の順に組まれる点を検証する。

psycopg がローカル環境に無くてもテストできるよう、
db_writer.py の該当関数のみをスタンドアロンに再定義している
（他のテスト _standalone.py と同じ方針）。
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


# db_writer.py から update_predictions_final_odds_batch の本体だけを抽出して
# 同じ挙動でテスト可能にする。psycopg の import を避けたいので
# モジュールをスタブした上で該当関数だけをロードする。
def _load_target_function():
    sys.modules.setdefault("psycopg", types.ModuleType("psycopg"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from collector.db_writer import update_predictions_final_odds_batch
    return update_predictions_final_odds_batch


update_predictions_final_odds_batch = _load_target_function()


def _fake_conn():
    """psycopg.Connection のふるまいをモックする"""
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur)
    return conn, cur


def test_empty_rows_noop():
    conn, cur = _fake_conn()
    n = update_predictions_final_odds_batch(conn, [])
    assert n == 0
    cur.executemany.assert_not_called()


def test_returns_row_count():
    conn, cur = _fake_conn()
    rows = [
        ("202604220101", "1-2-3", 10.5),
        ("202604220101", "1-3-2", 15.0),
        ("202604220102", "1-2-3", 8.2),
    ]
    n = update_predictions_final_odds_batch(conn, rows)
    assert n == 3


def test_executemany_called_once():
    conn, cur = _fake_conn()
    rows = [("202604220101", "1-2-3", 10.5)]
    update_predictions_final_odds_batch(conn, rows)
    cur.executemany.assert_called_once()


def test_sql_targets_final_odds_only_when_null():
    """final_odds IS NULL で既存値を上書きしないガードが含まれる"""
    conn, cur = _fake_conn()
    rows = [("202604220101", "1-2-3", 10.5)]
    update_predictions_final_odds_batch(conn, rows)

    sql = cur.executemany.call_args[0][0]
    # 対象列
    assert "final_odds" in sql
    assert "final_odds_recorded_at" in sql
    # 上書き防止ガード
    assert "final_odds IS NULL" in sql
    # 書き込み先は predictions（odds テーブルではない）
    assert "UPDATE predictions" in sql


def test_parameters_reordered_for_sql():
    """rows は (race_id, combination, odds_value) 順、
    SQL の WHERE は race_id / combination なので
    バインディングは (odds_value, race_id, combination) に並び替えられる"""
    conn, cur = _fake_conn()
    rows = [
        ("202604220101", "1-2-3", 10.5),
        ("202604220102", "4-5-6", 500.0),
    ]
    update_predictions_final_odds_batch(conn, rows)

    params = cur.executemany.call_args[0][1]
    # list[tuple] で渡される
    params = list(params)
    assert params[0] == (10.5, "202604220101", "1-2-3")
    assert params[1] == (500.0, "202604220102", "4-5-6")


if __name__ == "__main__":
    tests = [
        test_empty_rows_noop,
        test_returns_row_count,
        test_executemany_called_once,
        test_sql_targets_final_odds_only_when_null,
        test_parameters_reordered_for_sql,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {t.__name__} - {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {t.__name__} - {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} passed")
    import sys as _sys
    _sys.exit(0 if failed == 0 else 1)
