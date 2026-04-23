"""C-1: insert_odds_history_batch のユニットテスト

odds_history は INSERT ONLY で時系列のオッズスナップショットを蓄積する。
- 空入力は no-op
- SQL が odds_history テーブルへの INSERT になっていること
- rows の順序と executemany のパラメータ順が一致すること
- snapshot_at はサーバ側の DEFAULT now() に任せ、バインドパラメータに含まれないこと

psycopg をローカルに入れずに検証したいので
test_final_odds_writer.py と同様に psycopg をスタブしてから対象関数のみロードする。
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_target_function():
    sys.modules.setdefault("psycopg", types.ModuleType("psycopg"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from collector.db_writer import insert_odds_history_batch
    return insert_odds_history_batch


insert_odds_history_batch = _load_target_function()


def _fake_conn():
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur)
    return conn, cur


def test_empty_rows_noop():
    conn, cur = _fake_conn()
    n = insert_odds_history_batch(conn, [])
    assert n == 0
    cur.executemany.assert_not_called()


def test_returns_row_count():
    conn, cur = _fake_conn()
    rows = [
        ("202604240101", "1-2-3", 10.5),
        ("202604240101", "1-3-2", 15.0),
        ("202604240102", "1-2-3", 8.2),
    ]
    n = insert_odds_history_batch(conn, rows)
    assert n == 3


def test_executemany_called_once():
    conn, cur = _fake_conn()
    rows = [("202604240101", "1-2-3", 10.5)]
    insert_odds_history_batch(conn, rows)
    cur.executemany.assert_called_once()


def test_sql_inserts_into_odds_history():
    """SQL 本体が odds_history への INSERT で、snapshot_at は DEFAULT に任せること"""
    conn, cur = _fake_conn()
    rows = [("202604240101", "1-2-3", 10.5)]
    insert_odds_history_batch(conn, rows)

    sql = cur.executemany.call_args[0][0]
    assert "INSERT INTO odds_history" in sql
    assert "race_id" in sql
    assert "combination" in sql
    assert "odds_value" in sql
    # snapshot_at はサーバ側 DEFAULT now() に任せるためカラム列挙にも値プレースホルダにも含めない
    assert "snapshot_at" not in sql


def test_parameters_preserved_in_order():
    """rows のタプルがそのまま executemany に渡ること（並び替えなし）"""
    conn, cur = _fake_conn()
    rows = [
        ("202604240101", "1-2-3", 10.5),
        ("202604240102", "4-5-6", 500.0),
    ]
    insert_odds_history_batch(conn, rows)

    params = cur.executemany.call_args[0][1]
    assert params is rows or list(params) == rows


if __name__ == "__main__":
    tests = [
        test_empty_rows_noop,
        test_returns_row_count,
        test_executemany_called_once,
        test_sql_inserts_into_odds_history,
        test_parameters_preserved_in_order,
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
