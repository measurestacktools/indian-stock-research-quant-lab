from .provider import DataProvider, Company
import pandas as pd
class NSEProvider(DataProvider):
    def get_universe(self): return [Company("RELIANCE","Reliance Industries")]
    def get_daily_prices(self, symbol, start, end): raise NotImplementedError("NSEProvider not fully implemented - use yfinance or mock. Data unavailable")
    def health_check(self): return False
