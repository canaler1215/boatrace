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
            ON CONFLICT DO NOTHING
            """,
            (race_id, combination, odds_value),
        )


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
                expected_value = EXCLUDED.expected_value,
                alert_flag = EXCLUDED.alert_flag,
                predicted_at = now()
            """,
            prediction,
        )
