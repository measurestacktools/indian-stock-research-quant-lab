import pandas as pd, numpy as np
def benchmark_buy_hold(df: pd.DataFrame):
    if df.empty: return {"total_return":0}
    start=df["close"].iloc[0]; end=df["close"].iloc[-1]
    return {"total_return": float((end-start)/start), "start":float(start), "end":float(end)}
