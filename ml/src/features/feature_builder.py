"""
特徴量生成
約12次元 (MVP) の特徴量を組み立てる
"""
import pandas as pd
from .tidal_features import add_tidal_features
from .stadium_features import add_stadium_features

# 級別エンコーディング (高いほど上位)
GRADE_ENCODE = {"A1": 3, "A2": 2, "B1": 1, "B2": 0}

# 風向エンコーディング (1-16 の整数をそのまま使用)
# 1=北, 2=北北東, ..., 8=南, ..., 16=北北西

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
    "in_win_rate",
    "wind_direction_encoded",
    "wind_speed",
]


def build_features(entries: pd.DataFrame, race_meta: pd.DataFrame) -> pd.DataFrame:
    """
    DB から取得した出走表 + レースメタデータから特徴量を生成する。
    (predict.yml / run_predict.py から呼ぶ)

    Parameters
    ----------
    entries   : race_entries テーブルのデータ
    race_meta : races + stadiums + tidal_data を結合したデータ
    """
    df = entries.merge(race_meta, on="race_id", how="left")
    df = _encode_grade(df)
    df = add_tidal_features(df)
    df = add_stadium_features(df)
    return df[FEATURE_COLUMNS].fillna(0)


def build_features_from_history(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    history_downloader で取得した生データから特徴量とラベルを生成する。
    (retrain.yml / run_retrain.py から呼ぶ)

    Parameters
    ----------
    df : history_downloader.load_history_range() の返り値

    Returns
    -------
    X : pd.DataFrame  特徴量 (FEATURE_COLUMNS)
    y : pd.Series     ラベル (finish_position - 1, 0=1着 ... 5=6着)
    """
    # 着順が欠損しているレコードは除外
    df = df.dropna(subset=["finish_position"]).copy()
    df = df[df["finish_position"].between(1, 6)]

    # 特徴量エンコーディング
    df = _encode_grade(df)
    df = _encode_wind(df)
    df = add_stadium_features(df)

    # 潮位データは歴史 CSV には含まれないため 0 で埋める
    if "tidal_level" not in df.columns:
        df["tidal_level"] = 0.0
    if "tidal_type_encoded" not in df.columns:
        df["tidal_type_encoded"] = 0

    # racer_win_rate の列名を統一
    if "racer_win_rate" not in df.columns and "win_rate" in df.columns:
        df["racer_win_rate"] = df["win_rate"]

    X = df[FEATURE_COLUMNS].fillna(0)
    y = (df["finish_position"] - 1).astype(int)

    return X, y


def _encode_grade(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    grade_col = "racer_grade" if "racer_grade" in df.columns else "grade"
    if grade_col in df.columns:
        df["racer_grade_encoded"] = df[grade_col].map(GRADE_ENCODE).fillna(0).astype(int)
    else:
        df["racer_grade_encoded"] = 0
    return df


def _encode_wind(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "wind_direction" in df.columns:
        df["wind_direction_encoded"] = pd.to_numeric(df["wind_direction"], errors="coerce").fillna(0).astype(int)
    else:
        df["wind_direction_encoded"] = 0
    if "wind_speed" not in df.columns:
        df["wind_speed"] = 0.0
    return df
