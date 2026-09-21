import argparse, json, datetime, pandas as pd
from app.data.registry import get_provider
from app.features.engine import compute_features
from app.backtesting.engine import BacktestConfig, backtest_symbol, walk_forward
from app.backtesting.benchmark import benchmark_buy_hold
from app.database.db import init_db

def run_backtest(symbol="RELIANCE", provider="mock", walk=False):
    prov=get_provider(provider)
    df=prov.get_daily_prices(symbol,"2022-01-01", datetime.date.today().isoformat())
    df=compute_features(df)
    cfg=BacktestConfig()
    res=backtest_symbol(df,cfg)
    bench=benchmark_buy_hold(df)
    wf=walk_forward(df,cfg) if walk else []
    # persist
    try:
        conn=init_db(); conn.execute("INSERT INTO backtests(strategy,start,end,config_json,metrics_json,created_at) VALUES(?,?,?,?,?,?)",
            ("baseline_momentum", str(df["date"].iloc[0]), str(df["date"].iloc[-1]), json.dumps(cfg.__dict__), json.dumps(res["metrics"]), datetime.datetime.utcnow().isoformat()))
        conn.commit()
    except Exception as e: print("persist fail",e)
    return {"symbol":symbol,"metrics":res["metrics"],"benchmark":bench,"walk_forward":wf,"trades":res["trades"]}

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--symbol", default="RELIANCE")
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--walk", action="store_true")
    args=ap.parse_args()
    print(json.dumps(run_backtest(args.symbol, args.provider, args.walk), indent=2, default=str))
