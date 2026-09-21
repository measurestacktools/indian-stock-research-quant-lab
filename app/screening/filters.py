import pandas as pd, numpy as np
from app.data.quality import validate_ohlc
from app.portfolio.budget import BudgetInput, assess_affordability

def stage1_eligibility(df: pd.DataFrame, min_history=60, min_avg_volume=50000):
    if df is None or df.empty: return False, "no data"
    if len(df) < min_history: return False, f"history {len(df)} < {min_history}"
    issues = validate_ohlc(df)
    if any("open outside" in s or "high<low" in s for s in issues): return False, f"OHLC invalid: {issues}"
    avg_vol = df["volume"].tail(20).mean() if "volume" in df.columns else 0
    if avg_vol < min_avg_volume: return False, f"avg vol {avg_vol:.0f} < {min_avg_volume}"
    return True, "passed eligibility"

def stage2_affordability(price, budget: BudgetInput):
    res = assess_affordability(price, budget)
    return res.affordable, res.reason

def stage3_quant(df: pd.DataFrame, min_momentum=0.02, max_vol=0.4):
    if len(df)<60: return False, "insufficient for quant"
    ret_63 = df["close"].pct_change(63).iloc[-1] if len(df)>=64 else np.nan
    vol20 = df["close"].pct_change().rolling(20).std().iloc[-1]* (252**0.5)
    if pd.isna(ret_63): return False, "momentum unknown"
    if ret_63 < min_momentum: return False, f"momentum {ret_63:.2%} < {min_momentum:.2%}"
    if vol20 is not None and vol20>max_vol: return False, f"vol {vol20:.2%} > {max_vol:.2%}"
    return True, f"quant pass mom {ret_63:.2%} vol {vol20:.2%}"

def stage4_fundamental(fund: dict, min_roe=12, max_de=1.0, max_pe=40):
    if not fund: return None, "UNKNOWN insufficient fundamental data"
    roe = fund.get("roe"); de = fund.get("debt_equity"); pe=fund.get("pe")
    if roe is not None and roe < min_roe: return False, f"ROE {roe} < {min_roe}"
    if de is not None and de > max_de: return False, f"D/E {de} > {max_de}"
    if pe is not None and pe > max_pe: return False, f"PE {pe} > {max_pe}"
    return True, "fundamental pass"

def rank_candidates(cands, df_map):
    # transparent percentiles instead of magic score
    def percentile(vals, v):
        if v is None or len(vals)==0: return 50
        return float((np.array(vals) < v).mean()*100)
    moms = []
    roes=[]
    for c in cands:
        df=df_map.get(c["symbol"])
        if df is not None and len(df)>=64: moms.append(float(df["close"].pct_change(63).iloc[-1]))
        if c.get("fund") and c["fund"].get("roe") is not None: roes.append(c["fund"]["roe"])
    ranked=[]
    for c in cands:
        df=df_map.get(c["symbol"])
        mom = float(df["close"].pct_change(63).iloc[-1]) if df is not None and len(df)>=64 else None
        roe = c.get("fund",{}).get("roe") if c.get("fund") else None
        c["momentum_percentile"]= percentile(moms, mom) if mom is not None else None
        c["roe_percentile"]= percentile(roes, roe) if roe is not None else None
        ranked.append(c)
    ranked.sort(key=lambda x: (x["momentum_percentile"] or 0)+(x["roe_percentile"] or 0), reverse=True)
    return ranked
