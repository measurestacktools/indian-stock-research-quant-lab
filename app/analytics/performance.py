import pandas as pd, numpy as np
def performance_metrics(returns: pd.Series):
    if returns.empty: return {}
    total=(1+returns).prod()-1
    cagr=(1+total)**(252/len(returns))-1 if len(returns)>0 else 0
    vol=returns.std()* (252**0.5)
    sharpe= returns.mean()/returns.std()* (252**0.5) if returns.std()!=0 else 0
    roll_max=(1+returns).cumprod().cummax()
    dd=((1+returns).cumprod()-roll_max)/roll_max
    return {"total_return":float(total),"cagr":float(cagr),"volatility":float(vol),"sharpe":float(sharpe),"max_drawdown":float(dd.min())}
