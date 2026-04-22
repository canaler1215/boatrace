"""
Neon (PostgreSQL) へデータを upsert する
"""
import os
import psycopg
from typing import Any


def get_connection() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def upsert_race(conn: psycopg.Connection, race: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO races (id, stadium_id, race_date, race_no, grade, status)
            VALUES (%(id)s, %(stadium_id)s, %(race_date)s, %(race_no)s, %(grade)s, %(status)s)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                updated_at = now()
            """,
            race,
        )


def upsert_race_entry(conn: psycopg.Connection, entry: dict[str, Any]) -> None:
    # race_entries には (race_id, boat_no) のユニーク制約がないため
    # 既存行を削除してから INSERT する
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM race_entries WHERE race_id = %(race_id)s AND boat_no = %(boat_no)s",
            entry,
        )
        cur.execute(
            """
            INSERT INTO race_entries
                (race_id, boat_no, racer_id, motor_win_rate, boat_win_rate,
                 exhibition_time, start_timing, finish_position)
            VALUES
                (%(race_id)s, %(boat_no)s, %(racer_id)s, %(motor_win_rate)s,
                 %(boat_win_rate)s, %(exhibition_time)s, %(start_timing)s, %(finish_position)s)
            """,
            entry,
        )


def upsert_odds(conn: psycopg.Connection, race_id: str, combination: str, odds_value: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO odds (race_id, combination, odds_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (race_id, combination) DO UPDATE SET
                odds_value  = EXCLUDED.odds_value,
                snapshot_at = now()
            """,
            (race_id, combination, odds_value),
        )


# ---------------------------------------------------------------------------
# バッチ書き込み (executemany でネットワーク往復を削減)
# ---------------------------------------------------------------------------

def upsert_racers_batch(conn: psycopg.Connection, racers: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO racers (id, name, grade)
            VALUES (%(id)s, %(name)s, %(grade)s)
            ON CONFLICT (id) DO UPDATE SET
                name       = EXCLUDED.name,
                grade      = EXCLUDED.grade,
                updated_at = now()
            """,
            racers,
        )


def upsert_races_batch(conn: psycopg.Connection, races: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO races (id, stadium_id, race_date, race_no, grade, status)
            VALUES (%(id)s, %(stadium_id)s, %(race_date)s, %(race_no)s, %(grade)s, %(status)s)
            ON CONFLICT (id) DO UPDATE SET
                status = CASE
                    WHEN races.status = 'finished' THEN 'finished'
                    ELSE EXCLUDED.status
                END,
                updated_at = now()
            """,
            races,
        )


def upsert_race_entries_batch(conn: psycopg.Connection, entries: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "DELETE FROM race_entries WHERE race_id = %(race_id)s AND boat_no = %(boat_no)s",
            entries,
        )
        cur.executemany(
            """
            INSERT INTO race_entries
                (race_id, boat_no, racer_id, motor_win_rate, boat_win_rate,
                 exhibition_time, start_timing, finish_position)
            VALUES
                (%(race_id)s, %(boat_no)s, %(racer_id)s, %(motor_win_rate)s,
                 %(boat_win_rate)s, %(exhibition_time)s, %(start_timing)s, %(finish_position)s)
            """,
            entries,
        )


def upsert_odds_batch(conn: psycopg.Connection, rows: list[tuple[str, str, float]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO odds (race_id, combination, odds_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (race_id, combination) DO UPDATE SET
                odds_value   = EXCLUDED.odds_value,
                snapshot_at  = now()
            """,
            rows,
        )


def update_predictions_final_odds_batch(
    conn: psycopg.Connection,
    rows: list[tuple[str, str, float]],
) -> int:
    """
    終了済みレースの確定オッズを predictions.final_odds に書き込む。

    rows: list of (race_id, combination, odds_value)
    戻り値: 処理した件数（rows の長さ）

    すでに final_odds が入っている行は上書きしない（確定オッズは一度しか記録しないため）。
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE predictions
            SET final_odds              = %s,
                final_odds_recorded_at  = now()
            WHERE race_id     = %s
              AND combination = %s
              AND final_odds IS NULL
            """,
            [(odds_value, race_id, combo) for race_id, combo, odds_value in rows],
        )
    return len(rows)


def register_model_version(
    conn: psycopg.Connection,
    version: str,
    trained_at: str,
    data_range_from: str,
    data_range_to: str,
    rps_score: float,
    release_url: str | None = None,
) -> int:
    """model_versions に新バージョンを登録して id を返す"""
    with conn.cursor() as cur:
        # 既存をすべて非アクティブ化
        cur.execute("UPDATE model_versions SET is_active = false")
        cur.execute(
            """
            INSERT INTO model_versions
                (version, release_url, trained_at, data_range_from, data_range_to,
                 rps_score, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, true)
            RETURNING id
            """,
            (version, release_url, trained_at, data_range_from, data_range_to, rps_score),
        )
        row = cur.fetchone()
        return row[0]


def upsert_prediction(conn: psycopg.Connection, prediction: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO predictions
                (race_id, combination, win_probability, expected_value, alert_flag, model_version_id)
            VALUES
                (%(race_id)s, %(combination)s, %(win_probability)s,
                 %(expected_value)s, %(alert_flag)s, %(model_version_id)s)
            ON CONFLICT (race_id, combination) DO UPDATE SET
                win_probability = EXCLUDED.win_probability,
                expected_value  = CASE
                    WHEN EXCLUDED.expected_value IS NOT NULL THEN EXCLUDED.expected_value
                    ELSE predictions.expected_value
                END,
                alert_flag   = EXCLUDED.alert_flag,
                predicted_at = now()
            """,
            prediction,
        )
