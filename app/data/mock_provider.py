import pandas as pd, numpy as np
from datetime import date, timedelta
from .provider import DataProvider, Company

MOCK_UNIVERSE = [
    Company("RELIANCE", "Reliance Industries", sector="Energy", industry="Oil & Gas"),
    Company("TCS", "Tata Consultancy", sector="IT", industry="Software"),
    Company("INFY", "Infosys", sector="IT", industry="Software"),
    Company("HDFCBANK", "HDFC Bank", sector="Financial", industry="Bank"),
    Company("ICICIBANK", "ICICI Bank", sector="Financial", industry="Bank"),
    Company("SBIN", "State Bank of India", sector="Financial", industry="Bank"),
    Company("BHARTIARTL", "Bharti Airtel", sector="Telecom", industry="Telecom"),
    Company("ITC", "ITC Ltd", sector="FMCG", industry="Tobacco"),
    Company("LT", "Larsen & Toubro", sector="Construction", industry="Infra"),
    Company("MARUTI", "Maruti Suzuki", sector="Auto", industry="Auto"),
    Company("PENNY", "Penny Stock Ltd", sector="SmallCap", industry="Misc"),
    Company("MIDCAP", "Midcap Example", sector="MidCap", industry="Misc"),
]

class MockProvider(DataProvider):
    def get_universe(self): return MOCK_UNIVERSE
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
