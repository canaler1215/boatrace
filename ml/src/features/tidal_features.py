import pandas as pd


def add_tidal_features(df: pd.DataFrame) -> pd.DataFrame:
    """潮位特徴量を追加（満潮→内有利、干潮→外有利）"""
    df = df.copy()
    df["tidal_type_encoded"] = (df["tidal_type"] == "満潮").astype(int)
    return df
