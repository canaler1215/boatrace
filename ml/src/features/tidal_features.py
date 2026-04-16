"""
潮位特徴量モジュール

- DB由来データ（推論時）: tidal_type 列から直接エンコード
- 歴史データ（学習時）: 月齢×半日周潮モデルで推定
  → 推論時と学習時の乖離（P4問題）を解消する
"""
import math
from datetime import date
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# 会場別潮位振幅（cm, 平均水面からの片振幅）
# 内陸・湖沼は潮汐の影響がほぼないため 0
# ---------------------------------------------------------------------------
_VENUE_TIDAL_AMPLITUDE_CM: dict[int, float] = {
    1:  80.0,   # 桐生（渡良瀬川・内水）
    2:  30.0,   # 戸田（荒川・内水、微小）
    3: 110.0,   # 江戸川（東京湾奥：大きい）
    4: 110.0,   # 平和島（東京湾）
    5:  90.0,   # 多摩川（東京湾奥）
    6:  90.0,   # 浜名湖（遠州灘接続）
    7: 130.0,   # 蒲郡（伊勢湾：大きい）
    8: 130.0,   # 常滑（伊勢湾）
    9: 130.0,   # 津（伊勢湾）
    10: 70.0,   # 三国（九頭竜川・若狭湾）
    11: 10.0,   # びわこ（湖水、潮汐なし）
    12: 70.0,   # 住之江（大阪湾）
    13: 70.0,   # 尼崎（大阪湾）
    14: 90.0,   # 鳴門（鳴門海峡：潮流大）
    15: 90.0,   # 丸亀（燧灘）
    16: 80.0,   # 児島（児島湾）
    17: 90.0,   # 宮島（広島湾）
    18: 70.0,   # 徳山（周防灘）
    19: 80.0,   # 下関（関門海峡）
    20: 70.0,   # 若松（洞海湾）
    21: 70.0,   # 芦屋（遠賀川）
    22: 90.0,   # 福岡（博多湾）
    23: 90.0,   # 唐津（唐津湾）
    24: 100.0,  # 大村（大村湾）
}
_DEFAULT_AMPLITUDE_CM = 80.0

# 基準日：2000年1月6日（朔=新月、J2000.0 直前）
_EPOCH_NEW_MOON = date(2000, 1, 6)
_LUNAR_CYCLE_DAYS = 29.530589  # 朔望月（日）
_SEMIDIURNAL_PERIOD_HOURS = 12.421  # M2 分潮周期（時間）

# 1レースあたりの標準間隔（分）
_RACE_INTERVAL_MIN = 24
# 第1レース標準開始時刻（時）
_FIRST_RACE_HOUR = 9.5


def estimate_tidal_level(
    race_date: str,
    race_no: int,
    stadium_id: int,
) -> tuple[float, int]:
    """
    月齢と半日周潮モデルで潮位を推定する。

    Parameters
    ----------
    race_date : str  "YYYY-MM-DD"
    race_no   : int  レース番号 (1-12)
    stadium_id: int  JCD会場コード

    Returns
    -------
    tidal_level : float  推定潮位 (cm, 平均水面からの偏差)
    tidal_type  : int    1=満潮寄り(↑), 0=干潮寄り(↓)

    アルゴリズム
    ============
    半日周潮（M2分潮）モデル:
        h(t) = A × cos(2π × t / T_M2 + φ_spring)

    - t     : レース開始からの時刻 (時)
    - T_M2  : 12.421 時間（M2分潮周期）
    - A     : 会場別振幅 (cm)
    - φ_spring : 大潮小潮位相 = 2π × 月齢 / 29.53
    """
    try:
        d = date.fromisoformat(race_date)
    except ValueError:
        return 0.0, 0

    # 月齢計算
    days_since_nm = (d - _EPOCH_NEW_MOON).days
    lunar_age = days_since_nm % _LUNAR_CYCLE_DAYS

    # レース開始時刻推定（時）
    race_hour = _FIRST_RACE_HOUR + (race_no - 1) * _RACE_INTERVAL_MIN / 60.0

    # 半日周潮の位相（月齢による大潮/小潮を重畳）
    # 月齢 0 / 14.77 が大潮（新月・満月）→ cos(2π × lunar_age / 29.53) が最大
    spring_phase = 2 * math.pi * lunar_age / _LUNAR_CYCLE_DAYS
    time_phase = 2 * math.pi * race_hour / _SEMIDIURNAL_PERIOD_HOURS

    amplitude = _VENUE_TIDAL_AMPLITUDE_CM.get(stadium_id, _DEFAULT_AMPLITUDE_CM)
    # 大潮係数: 1.0（新月・満月）〜 0.5（小潮）で振幅を変調
    spring_factor = 0.75 + 0.25 * math.cos(spring_phase)
    tidal_level = amplitude * spring_factor * math.cos(time_phase + spring_phase / 2)

    # 潮位が上昇中（満潮寄り）かどうかの判定
    tidal_type = 1 if tidal_level >= 0 else 0

    return round(tidal_level, 1), tidal_type


def add_tidal_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    推論時（DB由来データ）用: tidal_type 列からエンコード。
    tidal_level 列はすでに DB から入っている想定。
    """
    df = df.copy()
    df["tidal_type_encoded"] = (df["tidal_type"] == "満潮").astype(int)
    return df


def add_tidal_features_estimated(df: pd.DataFrame) -> pd.DataFrame:
    """
    学習時（Kファイル由来データ）用: race_date + race_no + stadium_id から潮位を推定。

    tidal_level / tidal_type_encoded の両列を上書きする。
    stadium_id 列が存在しない場合は全行 0 で代替する。
    """
    df = df.copy()

    required = {"race_date", "race_no", "stadium_id"}
    if not required.issubset(df.columns):
        df["tidal_level"] = 0.0
        df["tidal_type_encoded"] = 0
        return df

    levels = []
    types = []
    for _, row in df.iterrows():
        lvl, typ = estimate_tidal_level(
            str(row["race_date"]),
            int(row.get("race_no", 1)),
            int(row["stadium_id"]),
        )
        levels.append(lvl)
        types.append(typ)

    df["tidal_level"] = levels
    df["tidal_type_encoded"] = types
    return df
