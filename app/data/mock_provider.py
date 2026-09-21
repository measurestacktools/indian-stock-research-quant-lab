import pandas as pd, numpy as np
from datetime import date, timedelta
from .provider import DataProvider, Company

MOCK_UNIVERSE = [
    Company("RELIANCE", "Reliance Industries", sector="Energy", industry="Oil & Gas", security_id="RELIANCE", listed_date="2000-01-01", delisted_date=None),
    Company("TCS", "Tata Consultancy", sector="IT", industry="Software", security_id="TCS", listed_date="2000-01-01"),
    Company("INFY", "Infosys", sector="IT", industry="Software", security_id="INFY", listed_date="2000-01-01"),
    Company("HDFCBANK", "HDFC Bank", sector="Financial", industry="Bank", security_id="HDFCBANK", listed_date="2000-01-01"),
    Company("ICICIBANK", "ICICI Bank", sector="Financial", industry="Bank", security_id="ICICIBANK", listed_date="2000-01-01"),
    Company("SBIN", "State Bank of India", sector="Financial", industry="Bank", security_id="SBIN", listed_date="2000-01-01"),
    Company("BHARTIARTL", "Bharti Airtel", sector="Telecom", industry="Telecom", security_id="BHARTIARTL", listed_date="2000-01-01"),
    Company("ITC", "ITC Ltd", sector="FMCG", industry="Tobacco", security_id="ITC", listed_date="2000-01-01"),
    Company("LT", "Larsen & Toubro", sector="Construction", industry="Infra", security_id="LT", listed_date="2000-01-01"),
    Company("MARUTI", "Maruti Suzuki", sector="Auto", industry="Auto", security_id="MARUTI", listed_date="2000-01-01"),
    # survivorship test cases
    Company("PENNY", "Penny Stock Ltd", sector="SmallCap", industry="Misc", security_id="PENNY", listed_date="2022-06-15", delisted_date=None),
    Company("MIDCAP", "Midcap Example", sector="MidCap", industry="Misc", security_id="MIDCAP", listed_date="2000-01-01", delisted_date="2024-08-20"),
    Company("OLDCO", "Old Company Ltd", sector="SmallCap", industry="Misc", security_id="OLDCO", listed_date="2010-01-01", delisted_date="2023-01-15", status="delisted"),
]

class MockProvider(DataProvider):
    def get_universe(self, as_of: str = None):
        if as_of is None:
            return MOCK_UNIVERSE
        # filter by listed/delisted with inclusive listed, exclusive delisted
        import pandas as pd
        try: as_of_dt = pd.to_datetime(as_of).normalize()
        except: return MOCK_UNIVERSE
        out=[]
        for c in MOCK_UNIVERSE:
            # listed_date <= as_of ?
            if c.listed_date:
                try:
                    if pd.to_datetime(c.listed_date).normalize() > as_of_dt:
                        continue
                except: pass
            # delisted_date > as_of (if delisted, not eligible on/after delisted)
            if c.delisted_date:
                try:
                    if pd.to_datetime(c.delisted_date).normalize() <= as_of_dt:
                        continue
                except: pass
            # also respect status if delisted explicitly
            out.append(c)
        return out
    def get_daily_prices(self, symbol, start, end):
        rng = pd.date_range(start, end, freq="B")
        n = len(rng)
        seed = abs(hash(symbol)) % 2**32
        rng_state = np.random.RandomState(seed)
        base = 20 if symbol=="PENNY" else 150 if symbol=="MIDCAP" else 1000 + seed % 500
        rets = rng_state.randn(n)*0.01
        prices = base * np.exp(np.cumsum(rets))
        df = pd.DataFrame({"date": rng, "open": prices* (1+rng_state.randn(n)*0.002), "high": prices*1.015, "low": prices*0.985, "close": prices, "volume": rng_state.randint(100000,5000000,size=n)})
        # ensure OHLC invariants
        df["high"] = df[["open","close","high"]].max(axis=1)*1.005
        df["low"] = df[["open","close","low"]].min(axis=1)*0.995
        df["open"] = df["open"].clip(lower=df["low"], upper=df["high"])
        df["close"] = df["close"].clip(lower=df["low"], upper=df["high"])
        df["symbol"]=symbol
        df["source"]="mock"
        return df
    def get_fundamentals(self, symbol):
        seed = abs(hash(symbol)) % 100
        return {"revenue_growth": 0.12 + seed*0.001, "profit_growth": 0.10+seed*0.002, "roe": 15+seed*0.1, "roce":14+seed*0.1, "debt_equity": 0.3+seed*0.005, "pe": 20+seed*0.2, "pb": 3+seed*0.05, "eps_growth":0.11}
    def get_corporate_actions(self, symbol): return []
