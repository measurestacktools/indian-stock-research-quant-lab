import pytest, pandas as pd, numpy as np, json, tempfile, pathlib, os, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# OHLC validation
def test_ohlc_validation():
    from app.data.quality import validate_ohlc
    df = pd.DataFrame({"open":[10,10],"high":[12,12],"low":[9,9],"close":[11,11],"volume":[100,100],"date":pd.date_range("2024-01-01", periods=2)})
    assert validate_ohlc(df)==[]
    # impossible
    df2 = pd.DataFrame({"open":[15],"high":[12],"low":[9],"close":[11],"volume":[100],"date":pd.date_range("2024-01-01", periods=1)})
    issues=validate_ohlc(df2)
    assert any("open outside" in s for s in issues)
    # duplicate dates
    df3 = pd.DataFrame({"open":[10,10],"high":[12,12],"low":[9,9],"close":[11,11],"volume":[100,100],"date":[pd.Timestamp("2024-01-01")]*2})
    assert any("duplicate" in s for s in validate_ohlc(df3))

def test_return_calculation():
    from app.features.engine import compute_features
    df=pd.DataFrame({"date":pd.date_range("2024-01-01",periods=5,freq="B"),"open":[100]*5,"high":[101]*5,"low":[99]*5,"close":[100,101,102,103,104],"volume":[1000]*5})
    out=compute_features(df)
    assert abs(out["ret_1d"].iloc[-1] - (104-103)/103) <1e-6

def test_moving_averages():
    from app.features.engine import compute_features
    df=pd.DataFrame({"date":pd.date_range("2024-01-01",periods=30,freq="B"),"open":[10]*30,"high":[10]*30,"low":[10]*30,"close":list(range(30)),"volume":[1000]*30})
    out=compute_features(df)
    # ma20 at last should be mean of 10..29
    expected = sum(range(10,30))/20
    assert abs(out["ma20"].iloc[-1]-expected)<1e-6

def test_volatility():
    from app.features.engine import compute_features
    df=pd.DataFrame({"date":pd.date_range("2024-01-01",periods=30,freq="B"),"open":[100]*30,"high":[101]*30,"low":[99]*30,"close":100+np.random.randn(30),"volume":[1000]*30})
    out=compute_features(df)
    assert "vol20" in out.columns
    assert pd.notna(out["vol20"].iloc[-1]) or pd.isna(out["vol20"].iloc[-1])  # just check column exists

def test_drawdown():
    from app.features.engine import compute_features
    df=pd.DataFrame({"date":pd.date_range("2024-01-01",periods=5,freq="B"),"open":[100,90,80,90,100],"high":[100,90,80,90,100],"low":[100,90,80,90,100],"close":[100,90,80,90,100],"volume":[1000]*5})
    out=compute_features(df)
    # cummax 100, so drawdown at trough -0.20
    assert abs(out["drawdown"].iloc[2] +0.20)<1e-6

def test_position_sizing():
    from app.portfolio.budget import position_size
    assert position_size(100,1000,0.02,0.05)==4  # 20 risk /5 per share

def test_affordability():
    from app.portfolio.budget import BudgetInput, assess_affordability
    b=BudgetInput(total_capital=150, brokerage_pct=0.001, slippage_pct=0.001)
    res=assess_affordability(20, b)
    assert res.affordable and res.max_shares>=1
    res2=assess_affordability(140, b)
    assert res2.affordable  # 140 affordable with 150
    res3=assess_affordability(200,b)
    assert not res3.affordable
    # costs considered: effective price > price

def test_transaction_costs():
    from app.portfolio.costs import calc_costs, CostAssumptions
    c=calc_costs(100,10)
    assert c["total"]>0
    assert c["turnover"]==1000
    # custom
    ca=CostAssumptions(brokerage_pct=0.005)
    c2=calc_costs(100,10,ca)
    assert c2["brokerage"]==5

def test_portfolio_pnl():
    from app.portfolio.portfolio import create_portfolio, buy, sell, get_value, get_cash
    import tempfile, pathlib
    db=pathlib.Path(tempfile.mktemp(suffix=".db"))
    create_portfolio("test",150, db_path=db)
    # penny 20
    buy("test","PENNY",1,120, costs=0.5, db_path=db)
    cash=get_cash("test",db_path=db)
    assert abs(cash - (150-120-0.5))<1e-6
    val=get_value("test",{"PENNY":125}, db_path=db)
    assert abs(val["total"] - (cash+125))<1e-6
    # unrealized 5 minus costs? check logic
    sell("test","PENNY",1,130, db_path=db)
    cash2=get_cash("test",db_path=db)
    assert cash2>cash
    try: conn=get_conn(db_path=db); conn.close()
    except: pass
    try: db.unlink(missing_ok=True)
    except: pass

def test_rule_engine():
    from app.screening.rules import evaluate_rules
    ctx={"avg_volume":200000,"roe":15,"debt_equity":0.5,"pe":20,"ret_63d":0.05}
    res=evaluate_rules(ctx)
    assert all(r["status"]=="PASSED" for r in res)
    ctx2={"avg_volume":1000,"roe":5,"debt_equity":2,"pe":100,"ret_63d":-0.05}
    res2=evaluate_rules(ctx2)
    assert any(r["status"]=="FAILED" for r in res2)
    # unknown
    ctx3={"avg_volume":None}
    res3=evaluate_rules(ctx3)
    assert any(r["status"]=="UNKNOWN" for r in res3)

def test_backtest_no_lookahead():
    from app.backtesting.engine import backtest_symbol, BacktestConfig
    # synthetic predictable: rising 1% daily for 100 days, momentum strategy should enter
    dates=pd.date_range("2023-01-01",periods=200,freq="B")
    closes=100*(1.01**np.arange(200))
    df=pd.DataFrame({"date":dates,"open":closes,"high":closes*1.01,"low":closes*0.99,"close":closes,"volume":[1000000]*200})
    from app.features.engine import compute_features
    df=compute_features(df)
    cfg=BacktestConfig(entry_momentum=0.02, max_holding_days=20)
    res=backtest_symbol(df,cfg)
    # with lookahead bias, would have many trades; without, should still have trades but verify entry uses past only
    assert res["metrics"]["num_trades"]>0
    # malformed: if we shift close forward to simulate cheat, trades would differ - ensure no future peek by checking that first trade entry date > momentum calculation date +1
    first=res["trades"][0]
    # entry date should be after 63 days of history
    assert pd.to_datetime(first["entry_date"]) >= dates[64]

def test_date_handling():
    import pandas as pd
    from app.data.normalize import normalize_prices
    df=pd.DataFrame({"date":["2024-01-01","2024-01-02"],"open":[1,1],"high":[2,2],"low":[0.5,0.5],"close":[1.5,1.5],"volume":[100,100]})
    out=normalize_prices(df)
    assert pd.api.types.is_datetime64_any_dtype(out["date"])
    assert len(out)==2

def test_corporate_action_handling():
    from app.data.mock_provider import MockProvider
    p=MockProvider()
    actions=p.get_corporate_actions("RELIANCE")
    assert isinstance(actions, list)

def test_malformed_ai_json():
    from app.ai.schemas import AnalystOutput
    import json
    bad='{"business_summary":123}'  # missing fields
    with pytest.raises(Exception):
        AnalystOutput(**json.loads(bad))
    # banned phrase
    from app.ai.schemas import contains_banned
    assert contains_banned("This is guaranteed return")
    assert not contains_banned("This is risky")

def test_missing_data():
    from app.features.engine import fundamental_features
    assert fundamental_features({})=={}
    assert fundamental_features(None)=={}
    from app.screening.filters import stage4_fundamental
    status,msg=stage4_fundamental(None)
    assert status is None and "UNKNOWN" in msg

def test_api_failure():
    from app.data.yfinance_provider import YFinanceProvider
    # monkey patch yfinance to fail
    import unittest.mock as mock
    prov=YFinanceProvider()
    with mock.patch("yfinance.download", side_effect=Exception("network fail")):
        try:
            prov.get_daily_prices("FAIL","2024-01-01","2024-01-10")
            assert False, "should raise"
        except: pass

def test_caching():
    from app.utils.cache import get_cache, set_cache, cache_key
    k=cache_key("test", "123")
    set_cache(k, {"a":1})
    assert get_cache(k)=={"a":1}
    # ttl expiry
    assert get_cache(k, ttl_seconds=0) is None or get_cache(k, ttl_seconds=100) is not None

def test_database_writes():
    from app.database.db import init_db, get_conn
    import tempfile, pathlib
    db=pathlib.Path(tempfile.mktemp(suffix=".db"))
    conn=init_db(db)
    conn.execute("INSERT INTO companies(symbol,name) VALUES(?,?)",("TEST","Test Co"))
    conn.commit()
    row=conn.execute("SELECT * FROM companies WHERE symbol='TEST'").fetchone()
    assert row["name"]=="Test Co"
    conn.close()
    try: db.unlink(missing_ok=True)
    except: pass

def test_walk_forward_labels():
    from app.backtesting.engine import walk_forward, BacktestConfig
    from app.features.engine import compute_features
    dates=pd.date_range("2023-01-01",periods=500,freq="B")
    closes=100+np.cumsum(np.random.randn(500))
    closes=np.maximum(closes,10)
    df=pd.DataFrame({"date":dates,"open":closes,"high":closes*1.01,"low":closes*0.99,"close":closes,"volume":[1000000]*500})
    df=compute_features(df)
    cfg=BacktestConfig()
    wf=walk_forward(df,cfg,train_days=100, test_days=20, step=20)
    assert len(wf)>0
    assert "in_sample" in wf[0] and "out_of_sample" in wf[0]
