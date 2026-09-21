import pandas as pd
import numpy as np

def validate_ohlc(df: pd.DataFrame):
    issues=[]
    if df.empty: return ["empty dataframe"]
    for idx,row in df.iterrows():
        if not (row["low"] <= row["open"] <= row["high"]): issues.append(f"row {idx} open outside low-high")
        if not (row["low"] <= row["close"] <= row["high"]): issues.append(f"row {idx} close outside low-high")
        if row["high"] < row["low"]: issues.append(f"row {idx} high<low")
        if row["volume"] is not None and row["volume"] <0: issues.append(f"row {idx} negative volume")
    # duplicate dates
    if "date" in df.columns and df["date"].duplicated().any(): issues.append("duplicate dates")
    # stale data: same close 10 days?
    if len(df)>=10 and df["close"].iloc[-10:].nunique()==1: issues.append("stale data: flat close 10d")
    # abnormal gaps >20%
    rets = df["close"].pct_change()
    if (rets.abs()>0.2).any(): issues.append("abnormal gap >20%")
    return issues

def quality_score(df): 
    issues=validate_ohlc(df)
    return {"issues": issues, "valid": len(issues)==0, "issue_count": len(issues)}
