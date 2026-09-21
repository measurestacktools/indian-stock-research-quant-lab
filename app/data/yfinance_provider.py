import pandas as pd
from .provider import DataProvider, Company
import logging
logger = logging.getLogger(__name__)

# Broad NSE universe — symbols without .NS suffix internally, provider adds it
YF_UNIVERSE_SYMBOLS = ["RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN","BHARTIARTL","ITC","LT","MARUTI","WIPRO","AXISBANK","KOTAKBANK","BAJFINANCE","HINDUNILVR","ASIANPAINT","TITAN","ULTRACEMCO","NESTLEIND","POWERGRID"]

class YFinanceProvider(DataProvider):
    def get_universe(self, as_of=None):
        # YFinance has no historical listed/delisted dates; return full universe
        # survivorship handled via DB layer when dates are populated
        return [Company(s, s, exchange="NSE", listed_date="2000-01-01", security_id=s) for s in YF_UNIVERSE_SYMBOLS]
    def get_daily_prices(self, symbol, start, end):
        try:
            import yfinance as yf
            ticker = symbol if symbol.endswith(".NS") else symbol+".NS"
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
            if df.empty: raise ValueError("Data unavailable")
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            # rename
            rename = {"adj close":"adj_close"}
            df = df.rename(columns=rename)
            # ensure date col
            if "date" not in df.columns: df = df.rename(columns={"index":"date"})
            df["symbol"]=symbol
            df["source"]="yfinance"
            # yfinance returns Date, Open, High, Low, Close, Volume
            return df[["date","open","high","low","close","volume","symbol","source"]]
        except Exception as e:
            logger.warning(f"yfinance failed for {symbol}: {e}")
            raise
    def get_fundamentals(self, symbol):
        try:
            import yfinance as yf
            t = yf.Ticker(symbol+".NS" if not symbol.endswith(".NS") else symbol)
            info = t.info
            return {"pe": info.get("trailingPE"), "pb": info.get("priceToBook"), "roe": info.get("returnOnEquity"), "debt_equity": info.get("debtToEquity"), "market_cap": info.get("marketCap")}
        except Exception: return None
