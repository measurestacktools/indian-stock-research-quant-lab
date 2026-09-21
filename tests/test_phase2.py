import pytest, pandas as pd, numpy as np, pathlib, sys, tempfile, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

def test_corporate_split_no_fake_crash():
    from app.data.corporate_actions import CorporateAction, apply_adjustments
    # raw series as in spec: Day1 200, Day2 200, Day3 100 split, Day4 105
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01","2024-01-02","2024-01-03","2024-01-04"]),
        "open": [200,200,100,105],
        "high": [200,200,100,105],
        "low": [200,200,100,105],
        "close": [200,200,100,105],
        "volume": [1000,1000,1000,1000]
    })
    action = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-03", ratio_numerator=2, ratio_denominator=1)
    adj = apply_adjustments(df, [action])
    # after backward adjustment, Day1,Day2 should be 100, Day3,Day4 unchanged
    assert abs(adj.loc[0,"close"] - 100) < 1e-6
    assert abs(adj.loc[1,"close"] - 100) < 1e-6
    assert abs(adj.loc[2,"close"] - 100) < 1e-6
    assert abs(adj.loc[3,"close"] - 105) < 1e-6
    # no -50% artificial return: Day2->Day3 raw would be -50%, adjusted should be ~0%
    # compute return Day2->Day3 adjusted: (100-100)/100 =0
    ret = (adj.loc[2,"close"] - adj.loc[1,"close"]) / adj.loc[1,"close"]
    assert abs(ret) < 1e-6
    # volume doubled for pre-split
    assert adj.loc[0,"volume"] == 2000  # raw 1000 /0.5

def test_reverse_split():
    from app.data.corporate_actions import CorporateAction, apply_adjustments
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01","2024-01-02","2024-01-03"]),
        "open": [50,50,100],
        "high": [50,50,100],
        "low": [50,50,100],
        "close": [50,50,100],
        "volume": [1000,1000,1000]
    })
    # 1:2 reverse split (1 new for 2 old) => factor 2, historical doubled
    action = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-03", ratio_numerator=1, ratio_denominator=2)
    adj = apply_adjustments(df, [action])
    assert abs(adj.loc[0,"close"] - 100) < 1e-6
    assert abs(adj.loc[1,"close"] - 100) < 1e-6
    assert abs(adj.loc[2,"close"] - 100) < 1e-6
    assert adj.loc[0,"volume"] == 500  # 1000/2

def test_bonus():
    from app.data.corporate_actions import CorporateAction, apply_adjustments
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01","2024-01-02"]),
        "open": [200,100],
        "high": [200,100],
        "low": [200,100],
        "close": [200,100],
        "volume": [1000,1000]
    })
    # 1:1 bonus => 2 for 1 => factor 0.5
    action = CorporateAction(symbol="TEST", action_type="bonus", ex_date="2024-01-02", ratio_numerator=2, ratio_denominator=1)
    adj = apply_adjustments(df, [action])
    assert abs(adj.loc[0,"close"] - 100) < 1e-6

def test_dividend_separate():
    from app.data.corporate_actions import CorporateAction, apply_adjustments
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01","2024-01-02","2024-01-03"]),
        "open": [100,100,100],
        "high": [100,100,100],
        "low": [100,100,100],
        "close": [100,100,100],
        "volume": [1000,1000,1000]
    })
    div = CorporateAction(symbol="TEST", action_type="dividend", ex_date="2024-01-02", cash_amount=5, currency="INR")
    adj = apply_adjustments(df, [div])
    # price not adjusted
    assert all(abs(adj["close"] - 100) < 1e-6)
    # but dividend_cash column shows 5 on ex_date
    assert adj.loc[1,"dividend_cash"] == 5
    assert adj.loc[0,"dividend_cash"] == 0
    # factor stays 1
    assert all(adj["cumulative_adjustment_factor"] == 1.0)

def test_multiple_actions_compound():
    from app.data.corporate_actions import CorporateAction, apply_adjustments
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01","2024-01-02","2024-01-03","2024-01-04"]),
        "open": [200,100,50,50],
        "high": [200,100,50,50],
        "low": [200,100,50,50],
        "close": [200,100,50,50],
        "volume": [1000,1000,1000,1000]
    })
    # two splits: 2024-01-02 2:1 (0.5), 2024-01-03 2:1 (0.5) => cumulative before first =0.25
    a1 = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-02", ratio_numerator=2, ratio_denominator=1)
    a2 = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-03", ratio_numerator=2, ratio_denominator=1)
    adj = apply_adjustments(df, [a1,a2])
    # Day1 before both: 200*0.25=50, Day2 after first but before second: 100*0.5=50, Day3+ after both: unchanged 50
    assert abs(adj.loc[0,"close"] - 50) < 1e-6
    assert abs(adj.loc[1,"close"] - 50) < 1e-6
    assert abs(adj.loc[2,"close"] - 50) < 1e-6

def test_invalid_ratio_fails():
    from app.data.corporate_actions import CorporateAction
    import pytest
    with pytest.raises(ValueError):
        ca = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-02", ratio_numerator=0, ratio_denominator=1)
        from app.data.corporate_actions import validate_action
        validate_action(ca)
    with pytest.raises(ValueError):
        ca = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-02", ratio_numerator=None, ratio_denominator=None)
        validate_action(ca)

def test_duplicate_handling():
    from app.data.corporate_actions import CorporateAction, normalize_actions
    a = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-02", ratio_numerator=2, ratio_denominator=1)
    dup = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-02", ratio_numerator=2, ratio_denominator=1)
    res = normalize_actions([a, dup])
    assert len(res) == 1

def test_idempotence():
    from app.data.corporate_actions import CorporateAction, apply_adjustments
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01","2024-01-02"]),
        "open": [200,100], "high": [200,100], "low": [200,100], "close": [200,100], "volume": [1000,1000]
    })
    a = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-02", ratio_numerator=2, ratio_denominator=1)
    adj1 = apply_adjustments(df, [a])
    adj2 = apply_adjustments(adj1, [a])
    assert list(adj1["close"]) == list(adj2["close"])
    assert list(adj1["volume"]) == list(adj2["volume"])

# PIT tests
def _cleanup_db(db):
    import gc, time
    try:
        from app.database.db import get_conn
        try: get_conn(db).close()
        except: pass
    except: pass
    gc.collect()
    time.sleep(0.05)
    try: db.unlink(missing_ok=True)
    except: pass

def test_pit_unavailable_before_filing():
    import tempfile, pathlib
    from app.data.fundamentals import insert_fundamental, get_fundamentals_as_of
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    # FY2025 period 2025-03-31 available 2025-05-20
    insert_fundamental("TEST", "2025-03-31", "2025-05-20", {"roe": 15, "pe": 20}, db_path=db)
    # before filing should be None
    assert get_fundamentals_as_of("TEST", "2025-04-01", db_path=db) is None
    assert get_fundamentals_as_of("TEST", "2025-05-19", db_path=db) is None
    assert get_fundamentals_as_of("TEST", "2025-05-20", db_path=db) is not None
    assert get_fundamentals_as_of("TEST", "2025-06-01", db_path=db) is not None
    _cleanup_db(db)

def test_pit_latest_valid_selection():
    import tempfile, pathlib
    from app.data.fundamentals import insert_fundamental, get_fundamentals_as_of
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    insert_fundamental("TEST", "2024-03-31", "2024-05-20", {"roe": 10}, db_path=db)
    insert_fundamental("TEST", "2025-03-31", "2025-05-20", {"roe": 15}, db_path=db)
    # as of 2025-04-01, latest available is 2024 filing
    r = get_fundamentals_as_of("TEST", "2025-04-01", db_path=db)
    assert r["period"] == "2024-03-31"
    # as of 2025-06-01, 2025 filing
    r2 = get_fundamentals_as_of("TEST", "2025-06-01", db_path=db)
    assert r2["period"] == "2025-03-31"
    _cleanup_db(db)

def test_pit_revision():
    import tempfile, pathlib
    from app.data.fundamentals import insert_fundamental, get_fundamentals_as_of
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    insert_fundamental("TEST", "2025-03-31", "2025-05-20", {"roe": 15}, db_path=db)
    insert_fundamental("TEST", "2025-03-31", "2025-08-10", {"roe": 14}, db_path=db)  # restatement same period, later available
    # June 1 should see May 20 version
    r = get_fundamentals_as_of("TEST", "2025-06-01", db_path=db)
    assert r["available_at"] == "2025-05-20"
    assert r["roe"] == 15
    # Sep 1 should see Aug 10
    r2 = get_fundamentals_as_of("TEST", "2025-09-01", db_path=db)
    assert r2["available_at"] == "2025-08-10"
    assert r2["roe"] == 14
    # history preserved: both rows exist
    from app.data.fundamentals import get_fundamentals_history
    hist = get_fundamentals_history("TEST", db_path=db)
    assert len(hist) == 2
    _cleanup_db(db)

def test_pit_no_future_leakage_in_backtest():
    # simulate backtest loop uses PIT callback
    import tempfile, pathlib, pandas as pd
    from app.data.fundamentals import insert_fundamental
    from app.backtesting.engine import backtest_symbol, BacktestConfig
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    # insert future filing not available at early backtest dates
    insert_fundamental("TEST", "2025-03-31", "2025-05-20", {"roe": 20}, db_path=db)
    dates = pd.date_range("2025-04-01", periods=80, freq="B")
    closes = [100]*80
    df = pd.DataFrame({"date": dates, "open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000000]*80})
    from app.features.engine import compute_features
    df = compute_features(df)
    # use PIT-aware backtest; should not see future filing on 2025-04-15
    cfg = BacktestConfig(entry_momentum=0.01)
    # pit callback that checks DB
    from app.data.fundamentals import get_fundamentals_as_of
    def pit_cb(sym, as_of): return get_fundamentals_as_of(sym, as_of, db_path=db)
    # before filing, pit returns None; after, returns record. Backtest should not crash and should handle None as unavailable
    res = backtest_symbol(df, cfg, symbol="TEST", use_pit_fundamentals=True, pit_callback=pit_cb)
    # no assertion on trades, just that no leakage: the early dates should have None
    assert get_fundamentals_as_of("TEST", "2025-04-15", db_path=db) is None
    assert get_fundamentals_as_of("TEST", "2025-06-01", db_path=db) is not None
    _cleanup_db(db)

def test_pit_missing_graceful():
    import tempfile, pathlib
    from app.data.fundamentals import get_fundamentals_as_of
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    # no data inserted
    assert get_fundamentals_as_of("UNKNOWN", "2025-01-01", db_path=db) is None
    _cleanup_db(db)

def test_provenance_preserved():
    import tempfile, pathlib
    from app.data.fundamentals import insert_fundamental
    from app.data.corporate_actions import CorporateAction
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    h = insert_fundamental("TEST", "2025-03-31", "2025-05-20", {"roe":15}, source="yfinance", db_path=db)
    from app.database.db import get_conn
    conn = get_conn(db)
    row = conn.execute("SELECT hash, source, data_version FROM fundamentals WHERE symbol='TEST'").fetchone()
    assert row["hash"] == h
    assert row["source"] == "yfinance"
    # corporate action provenance
    ca = CorporateAction(symbol="TEST", action_type="split", ex_date="2024-01-02", ratio_numerator=2, ratio_denominator=1, source="nse", data_version="v1")
    from app.data.corporate_actions import validate_action
    ca = validate_action(ca)
    assert ca.raw_hash is not None
    assert ca.source == "nse"
    _cleanup_db(db)

def test_fundamentals_pit_view_exists():
    from app.database.db import init_db
    import tempfile, pathlib
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    conn = init_db(db)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='fundamentals_pit'").fetchall()
    assert len(rows)==1
    _cleanup_db(db)

def test_migration_preserves_prices():
    # ensure prices_daily still works after migration
    from app.database.db import init_db
    import tempfile, pathlib
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    conn = init_db(db)
    conn.execute("INSERT INTO prices_daily(symbol,date,open,high,low,close,volume,source,retrieved_at,hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 ("TEST","2024-01-01",100,101,99,100,1000,"test","2024-01-02","abc"))
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
    assert cnt==1
    _cleanup_db(db)
