import pandas as pd, numpy as np
def classify_regime(df: pd.DataFrame):
    if df is None or df.empty or len(df)<50:
        return {"regime":"insufficient data","metrics":{}}
    c=df["close"]
    ma50=c.rolling(50).mean().iloc[-1]
    ma200=c.rolling(200).mean().iloc[-1] if len(df)>=200 else np.nan
    vol20 = c.pct_change().rolling(20).std().iloc[-1] * (252**0.5)
    trend = "bullish trend" if c.iloc[-1] > ma50 else "bearish trend"
    # check sideways: if within 2% of ma50
    if abs(c.iloc[-1]-ma50)/ma50 <0.02: trend="sideways"
    vol_regime = "high volatility" if vol20>0.25 else "low volatility" if vol20<0.15 else "normal volatility"
    metrics = {"ma50":float(ma50) if pd.notna(ma50) else None, "ma200":float(ma200) if pd.notna(ma200) else None, "vol20":float(vol20) if pd.notna(vol20) else None, "last_close":float(c.iloc[-1])}
    return {"regime": trend, "vol_regime": vol_regime, "metrics": metrics}
