import pandas as pd


# 競艇場別1コース勝率（全国平均55.9%）
STADIUM_IN_WIN_RATE = {
    4: 0.689,   # 尼崎
    22: 0.683,  # 大村
    3: 0.435,   # 江戸川（荒れやすい）
}
DEFAULT_IN_WIN_RATE = 0.559


def add_stadium_features(df: pd.DataFrame) -> pd.DataFrame:
    """競艇場特性特徴量を追加"""
    df = df.copy()
    df["in_win_rate"] = df["stadium_id"].map(STADIUM_IN_WIN_RATE).fillna(DEFAULT_IN_WIN_RATE)
    return df
