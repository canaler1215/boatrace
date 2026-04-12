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
    # start_timing は当該レースの実際の ST であり事後情報のため除外
    # 代わりに選手の過去 ST 平均 (racer_avg_st) を使用
    "racer_avg_st",
    "tidal_level",
    "tidal_type_encoded",
    "in_win_rate",
    "wind_direction_encoded",
    "wind_speed",
]


def build_features(
    entries: pd.DataFrame,
    race_meta: pd.DataFrame,
    racer_avg_st: dict[int, float] | None = None,
) -> pd.DataFrame:
    """
    DB から取得した出走表 + レースメタデータから特徴量を生成する。
    (predict.yml / run_predict.py から呼ぶ)

    Parameters
    ----------
    entries      : race_entries テーブルのデータ
    race_meta    : races + stadiums + tidal_data を結合したデータ
    racer_avg_st : {racer_id: 平均ST} の辞書（省略時は全行 0 で代替）
    """
    df = entries.merge(race_meta, on="race_id", how="left")
    df = _encode_grade(df)
    df = add_tidal_features(df)
    df = add_stadium_features(df)

    # 選手の過去 ST 平均（辞書が渡された場合はマッピング、なければ 0）
    if racer_avg_st and "racer_id" in df.columns:
        df["racer_avg_st"] = df["racer_id"].map(racer_avg_st).fillna(0.0)
    else:
        df["racer_avg_st"] = 0.0

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

    # 選手の過去 ST 平均を計算（ルックアヘッドなし）
    df = _add_racer_avg_st(df)

    X = df[FEATURE_COLUMNS].fillna(0)
    y = (df["finish_position"] - 1).astype(int)

    return X, y


def _add_racer_avg_st(df: pd.DataFrame) -> pd.DataFrame:
    """
    各選手の過去 ST 平均を計算して racer_avg_st 列として追加する。

    race_date → race_id の順でソートし、各行より前のデータのみを使うことで
    ルックアヘッドバイアスを排除する。

    - racer_id が利用可能な場合: 選手ごとの expanding mean (shift=1)
    - racer_id がない場合: データセット全体の start_timing 平均で代替
    - 過去レースが存在しない先頭行や start_timing が欠損するレース:
      データセット全体の平均 ST で補完する
    """
    df = df.copy()

    if "start_timing" not in df.columns or df["start_timing"].isna().all():
        df["racer_avg_st"] = 0.0
        return df

    global_mean = df["start_timing"].mean()

    if "racer_id" in df.columns:
        df = df.sort_values(["race_date", "race_id", "boat_no"])
        # shift(1) で当該行自体を含めず、expanding().mean() で過去の累積平均を取る
        df["racer_avg_st"] = (
            df.groupby("racer_id")["start_timing"]
            .transform(lambda s: s.shift(1).expanding().mean())
        )
    else:
        # racer_id がない場合はデータ全体の平均で代替
        df["racer_avg_st"] = global_mean

    df["racer_avg_st"] = df["racer_avg_st"].fillna(global_mean)
    return df


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
