"""
特徴量生成
約12次元 (MVP) の特徴量を組み立てる
"""
import pandas as pd
from .tidal_features import add_tidal_features, add_tidal_features_estimated
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
    df = _encode_wind(df)
    df = add_tidal_features(df)
    df = add_stadium_features(df)

    # 選手の過去 ST 平均（辞書が渡された場合はマッピング、なければ 0）
    if racer_avg_st and "racer_id" in df.columns:
        df["racer_avg_st"] = df["racer_id"].map(racer_avg_st).fillna(0.0)
    else:
        df["racer_avg_st"] = 0.0

    return df[FEATURE_COLUMNS].fillna(0)


def build_features_from_history(
    df: pd.DataFrame,
    *,
    return_dates: bool = False,
):
    """
    history_downloader で取得した生データから特徴量とラベルを生成する。
    (retrain.yml / run_retrain.py から呼ぶ)

    Parameters
    ----------
    df : history_downloader.load_history_range() の返り値
    return_dates : bool
        True の場合、(X, y, race_dates) を返す。race_dates は X と同じ行順・同じ長さの
        pd.Series（dtype=datetime64[ns]、インデックスは X と一致）。
        sample_weight 生成（recency 重み付け）のために使う。
        False（デフォルト）は従来通り (X, y)。

    Returns
    -------
    (X, y) または (X, y, race_dates)
    """
    # 着順が欠損しているレコードは除外
    df = df.dropna(subset=["finish_position"]).copy()
    df = df[df["finish_position"].between(1, 6)]

    # 特徴量エンコーディング
    df = _encode_grade(df)
    df = _encode_wind(df)
    df = add_stadium_features(df)

    # 潮位データは Kファイルには含まれないため月齢モデルで推定する（P4修正）
    # race_date + race_no + stadium_id が揃っていれば推定値を使用し、
    # 推論時（DB由来）との乖離を解消する。
    df = add_tidal_features_estimated(df)

    # racer_win_rate の列名を統一
    if "racer_win_rate" not in df.columns and "win_rate" in df.columns:
        df["racer_win_rate"] = df["win_rate"]

    # racer_win_rate を直近3ヶ月加重平均に更新（ルックアヘッドなし）
    # B ファイルの全国勝率（年度集計）より直近の実績を反映させる
    df = _add_rolling_racer_win_rate(df, window_months=3, min_weighted_races=3)

    # 選手の過去 ST 平均を計算（ルックアヘッドなし）
    df = _add_racer_avg_st(df)

    X = df[FEATURE_COLUMNS].fillna(0)
    y = (df["finish_position"] - 1).astype(int)

    if return_dates:
        race_dates = pd.to_datetime(df["race_date"]) if "race_date" in df.columns else pd.Series(pd.NaT, index=df.index)
        race_dates.index = df.index
        return X, y, race_dates
    return X, y


def _add_rolling_racer_win_rate(
    df: pd.DataFrame,
    window_months: int = 3,
    min_weighted_races: int = 3,
) -> pd.DataFrame:
    """
    Kファイルの finish_position を使い、直近 window_months ヶ月の加重平均勝率を計算して
    racer_win_rate 列を更新する。

    重み: 1ヶ月前 × window_months, 2ヶ月前 × (window_months-1), ..., N ヶ月前 × 1

    ルックアヘッドなし:
      - 当月のレース結果は参照しない（前月以前のみ）
      - 加重レース数 < min_weighted_races の場合は既存の racer_win_rate（B ファイル値）を維持

    Parameters
    ----------
    df                 : K+B マージ済みの DataFrame (finish_position, racer_id, race_date 必須)
    window_months      : ルックバック月数（デフォルト 3）
    min_weighted_races : この加重レース数を下回る場合 B ファイル値を使用（デフォルト 3）
    """
    required = {"racer_id", "race_date", "finish_position"}
    if not required.issubset(df.columns):
        return df

    df = df.copy()
    df["_race_date_dt"] = pd.to_datetime(df["race_date"])
    df["_ym"] = df["_race_date_dt"].dt.to_period("M")
    df["_ym_ord"] = df["_ym"].apply(lambda p: p.ordinal)

    # 月別集計: (racer_id, ym_ordinal) → (wins, races)
    monthly = (
        df.groupby(["racer_id", "_ym_ord"])
        .agg(
            wins=("finish_position", lambda x: (x == 1).sum()),
            races=("finish_position", lambda x: x.notna().sum()),
        )
        .reset_index()
    )

    # 重みテーブル: lag 1 → weight=window_months, ..., lag N → weight=1
    weights = {lag: window_months + 1 - lag for lag in range(1, window_months + 1)}

    # 各ラグ月の勝ち数・レース数をマージ
    rolling_wins = None
    rolling_weighted_races = None
    for lag, w in weights.items():
        m = monthly.copy()
        m["_ym_ord"] = m["_ym_ord"] + lag  # 参照先を lag ヶ月分前倒し
        m = m.rename(columns={"wins": f"_wins_{lag}", "races": f"_races_{lag}"})

        df = df.merge(
            m[["racer_id", "_ym_ord", f"_wins_{lag}", f"_races_{lag}"]],
            on=["racer_id", "_ym_ord"],
            how="left",
        )
        w_wins = w * df[f"_wins_{lag}"].fillna(0.0)
        w_races = w * df[f"_races_{lag}"].fillna(0.0)

        rolling_wins = w_wins if rolling_wins is None else rolling_wins + w_wins
        rolling_weighted_races = w_races if rolling_weighted_races is None else rolling_weighted_races + w_races

        df = df.drop(columns=[f"_wins_{lag}", f"_races_{lag}"])

    # 加重平均勝率
    has_enough = rolling_weighted_races >= min_weighted_races
    rolling_rate = rolling_wins / rolling_weighted_races.clip(lower=1)

    # 既存の racer_win_rate (B ファイル値) がある場合は不足行に使用
    fallback = df["racer_win_rate"].fillna(0.0) if "racer_win_rate" in df.columns else 0.0
    df["racer_win_rate"] = rolling_rate.where(has_enough, other=fallback)

    df = df.drop(columns=["_race_date_dt", "_ym", "_ym_ord"])
    return df


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
