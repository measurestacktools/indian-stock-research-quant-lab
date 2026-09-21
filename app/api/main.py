from fastapi import FastAPI, Query
from app.screening.run import run_screen
from app.data.registry import get_provider
from app.features.engine import compute_features
from app.backtesting.run import run_backtest
from app.portfolio.portfolio import create_portfolio, get_value, buy, sell, get_positions, get_cash
from app.database.db import init_db, get_conn
import datetime

app=FastAPI(title="Stock Lab API")

@app.get("/health")
def health(): return {"status":"ok","time":datetime.datetime.utcnow().isoformat()}

@app.get("/universe")
def universe(provider: str="mock"):
    p=get_provider(provider); return [{"symbol":c.symbol,"name":c.name,"sector":c.sector} for c in p.get_universe()]

@app.get("/screen")
def screen(budget: float=150, provider: str="mock"):
    return run_screen(budget, provider)

@app.get("/prices/{symbol}")
def prices(symbol: str, provider: str="mock", start: str="2023-01-01"):
    p=get_provider(provider)
    df=p.get_daily_prices(symbol, start, datetime.date.today().isoformat())
    return df.tail(100).to_dict(orient="records")

@app.get("/backtest/{symbol}")
def backtest(symbol: str, provider: str="mock"):
    return run_backtest(symbol, provider)

@app.post("/portfolio/{name}/buy")
def api_buy(name: str, symbol: str, qty: int, price: float):
    create_portfolio(name,150); return buy(name,symbol,qty,price)

@app.get("/portfolio/{name}/value")
def api_value(name: str, prices: str=""):
    # prices as symbol:price comma separated - simplified
    m={}
    if prices:
        for pair in prices.split(","):
            if ":" in pair: k,v=pair.split(":"); m[k]=float(v)
    return get_value(name, m)
