import argparse, json, datetime
import pandas as pd
from app.data.registry import get_provider
from app.data.quality import validate_ohlc
from app.features.engine import compute_features
from app.portfolio.budget import BudgetInput
from app.screening.filters import stage1_eligibility, stage2_affordability, stage3_quant, stage4_fundamental, rank_candidates
from app.database.db import init_db
from app.config.settings import settings

def run_screen(budget_capital=150, provider_name="mock", min_history=60):
    provider=get_provider(provider_name)
    universe=provider.get_universe()
    budget=BudgetInput(total_capital=budget_capital, max_per_position=budget_capital)
    results=[]
    df_map={}
    fund_map={}
    for c in universe:
        try:
            df=provider.get_daily_prices(c.symbol,"2023-01-01", datetime.date.today().isoformat())
            df=compute_features(df)
            df_map[c.symbol]=df
            fund=provider.get_fundamentals(c.symbol)
            fund_map[c.symbol]=fund
            s1, r1 = stage1_eligibility(df, min_history=min_history)
            if not s1: results.append({"symbol":c.symbol,"stage":"eligibility","passed":False,"reason":r1}); continue
            price=float(df["close"].iloc[-1])
            s2, r2 = stage2_affordability(price, budget)
            if not s2: results.append({"symbol":c.symbol,"stage":"affordability","passed":False,"reason":r2}); continue
            s3, r3 = stage3_quant(df)
            if not s3: results.append({"symbol":c.symbol,"stage":"quant","passed":False,"reason":r3}); continue
            s4, r4 = stage4_fundamental(fund)
            if s4 is False: results.append({"symbol":c.symbol,"stage":"fundamental","passed":False,"reason":r4}); continue
            if s4 is None: reason = r4 + " but passing to candidate (flagged unknown)"
            else: reason = r3+"; "+r4
            results.append({"symbol":c.symbol,"stage":"candidate","passed":True,"reason":reason,"fund":fund})
        except Exception as e:
            results.append({"symbol":c.symbol,"stage":"error","passed":False,"reason":str(e)})
    cands=[r for r in results if r["stage"]=="candidate" and r["passed"]]
    ranked=rank_candidates(cands, df_map)
    # persist
    try:
        conn=init_db()
        cur=conn.execute("INSERT INTO screening_runs(timestamp,config_json,dataset_version,universe_count) VALUES(?,?,?,?)",
                         (datetime.datetime.utcnow().isoformat(), json.dumps({"budget":budget_capital,"provider":provider_name}), "v1", len(universe)))
        run_id=cur.lastrowid
        for r in results:
            conn.execute("INSERT INTO screening_results(run_id,symbol,stage,passed,reason_json) VALUES(?,?,?,?,?)",
                         (run_id, r["symbol"], r["stage"], int(r["passed"]), json.dumps(r)))
        conn.commit()
    except Exception as e: print("DB persist failed",e)
    return {"universe":len(universe),"candidates":ranked,"all_results":results}

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=150)
    ap.add_argument("--provider", default="mock")
    args=ap.parse_args()
    out=run_screen(args.budget, args.provider)
    print(f"Universe {out['universe']}, candidates {len(out['candidates'])}")
    for c in out["candidates"][:10]: print(c["symbol"], c["reason"])
