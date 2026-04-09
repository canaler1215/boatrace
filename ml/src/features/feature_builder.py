"""
特徴量生成メイン
約60次元の特徴量を組み立てる
"""
import pandas as pd
from .tidal_features import add_tidal_features
from .stadium_features import add_stadium_features


FEATURE_COLUMNS = [
    "exhibition_time",
    "motor_win_rate",
    "boat_win_rate",
    "boat_no",
    "racer_win_rate",
    "racer_grade_encoded",
    "start_timing",
    "tidal_level",
    "tidal_type_encoded",
    "in_win_rate",  # 競艇場特性
    "wind_direction_encoded",
    "wind_speed",
]


def build_features(entries: pd.DataFrame, race_meta: pd.DataFrame) -> pd.DataFrame:
    """
    entries: race_entries テーブルのデータ
    race_meta: races + stadiums + tidal_data を結合したデータ
    """
    df = entries.merge(race_meta, on="race_id", how="left")
    df = add_tidal_features(df)
    df = add_stadium_features(df)
    return df[FEATURE_COLUMNS].fillna(0)
