import pandas as pd
def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    df=df.copy()
    df["date"]=pd.to_datetime(df["date"])
    df=df.sort_values("date")
    # ensure numeric
    for c in ["open","high","low","close","volume"]:
        if c in df.columns: df[c]=pd.to_numeric(df[c], errors="coerce")
    df=df.dropna(subset=["open","high","low","close"])
    return df
