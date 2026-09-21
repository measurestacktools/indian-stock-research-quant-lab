import pandas as pd, numpy as np

def atr(df, n=14):
    hl = df["high"]-df["low"]
    hc = (df["high"]-df["close"].shift(1)).abs()
    lc = (df["low"]-df["close"].shift(1)).abs()
    tr = pd.concat([hl,hc,lc],axis=1).max(axis=1)
    return tr.rolling(n).mean()

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    df=df.sort_values("date").copy()
    c=df["close"]
    df["ret_1d"]=c.pct_change(1)
    df["ret_5d"]=c.pct_change(5)
    df["ret_21d"]=c.pct_change(21)
    df["ret_63d"]=c.pct_change(63)
    df["ret_126d"]=c.pct_change(126)
    df["ret_252d"]=c.pct_change(252)
    df["ma20"]=c.rolling(20).mean()
    df["ma50"]=c.rolling(50).mean()
    df["ma200"]=c.rolling(200).mean()
    df["vol20"]=df["ret_1d"].rolling(20).std()* (252**0.5)
    df["atr14"]=atr(df,14)
    # drawdown
    roll_max = c.cummax()
    df["drawdown"]=(c-roll_max)/roll_max
    df["vol_chg"]=df["volume"].pct_change()
    df["rel_vol"]=df["volume"]/df["volume"].rolling(20).mean()
    # 52w
    roll_high = c.rolling(252).max()
    roll_low = c.rolling(252).min()
    df["dist_52w_high"]=(c-roll_high)/roll_high
    df["dist_52w_low"]=(c-roll_low)/roll_low
    return df

def fundamental_features(f: dict):
    if not f: return {}
    out={}
    # map raw keys if present
    for k in ["revenue_growth","profit_growth","eps_growth","roe","roce","debt_equity","pe","pb"]:
        v=f.get(k)
        out[k]= v if v is not None else None
    # don't invent ratios if missing
    return out
