import pytest, pandas as pd, pathlib, sys, tempfile, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

def _cleanup(db):
    import gc, time
    try:
        from app.database.db import get_conn
        try: get_conn(db).close()
        except: pass
    except: pass
    gc.collect(); time.sleep(0.05)
    try: db.unlink(missing_ok=True)
    except: pass

def test_listed_inclusive():
    from app.data.universe import get_universe
    # PENNY listed 2022-06-15
    assert "PENNY" not in [c.symbol for c in get_universe("2021-12-31", provider_name="mock", use_db=False)]
    assert "PENNY" not in [c.symbol for c in get_universe("2022-06-14", provider_name="mock", use_db=False)]
    assert "PENNY" in [c.symbol for c in get_universe("2022-06-15", provider_name="mock", use_db=False)]
    assert "PENNY" in [c.symbol for c in get_universe("2022-06-16", provider_name="mock", use_db=False)]

def test_delisted_exclusive():
    from app.data.universe import get_universe
    # MIDCAP delisted 2024-08-20 exclusive: not eligible on 2024-08-20
    assert "MIDCAP" in [c.symbol for c in get_universe("2024-08-19", provider_name="mock", use_db=False)]
    assert "MIDCAP" not in [c.symbol for c in get_universe("2024-08-20", provider_name="mock", use_db=False)]
    assert "MIDCAP" not in [c.symbol for c in get_universe("2024-08-21", provider_name="mock", use_db=False)]
    # OLDCO delisted 2023-01-15
    assert "OLDCO" in [c.symbol for c in get_universe("2023-01-14", provider_name="mock", use_db=False)]
    assert "OLDCO" not in [c.symbol for c in get_universe("2023-01-15", provider_name="mock", use_db=False)]

def test_snapshot_determinism():
    import tempfile, pathlib
    from app.data.universe import create_snapshot, get_snapshot
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    sid1 = create_snapshot("2022-06-15", provider_name="mock", db_path=db)
    sid2 = create_snapshot("2022-06-15", provider_name="mock", db_path=db)
    assert sid1 == sid2
    snaps = get_snapshot("2022-06-15", db_path=db)
    symbols = [r["symbol"] for r in snaps]
    assert "PENNY" in symbols
    assert "RELIANCE" in symbols
    # different as_of -> different hash
    sid3 = create_snapshot("2021-12-31", provider_name="mock", db_path=db)
    assert sid1 != sid3
    assert "PENNY" not in [r["symbol"] for r in get_snapshot("2021-12-31", db_path=db)]
    _cleanup(db)

def test_universe_avoids_lookahead():
    from app.data.universe import get_universe
    # as_of 2021 should not include 2022 listing even though we know today it exists
    uni_2021 = get_universe("2021-06-01", provider_name="mock", use_db=False)
    assert "PENNY" not in [c.symbol for c in uni_2021]
    uni_2023 = get_universe("2023-06-01", provider_name="mock", use_db=False)
    assert "PENNY" in [c.symbol for c in uni_2023]

def test_backtest_respects_survivorship():
    import pandas as pd
    from app.data.universe import get_universe
    from app.backtesting.engine import backtest_symbol, BacktestConfig
    # create df for PENNY with tradable prices, but backtest before listing should block signals
    dates = pd.date_range("2022-06-01", periods=100, freq="B")
    closes = [100]*100
    df = pd.DataFrame({"date": dates, "open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000000]*100})
    from app.features.engine import compute_features
    df = compute_features(df)
    # make df have momentum so would normally trade, but force rising to trigger entries
    df["close"] = 100 * (1 + pd.Series(range(100))*0.005)
    df["open"] = df["close"]
    df["high"] = df["close"]*1.01
    df["low"] = df["close"]*0.99
    cfg = BacktestConfig(entry_momentum=0.001, max_holding_days=5)
    # universe callback: only PENNY eligible after 2022-06-15
    def uni_cb(as_of): return get_universe(as_of, provider_name="mock", use_db=False)
    # backtest for PENNY over period that includes pre-listing: first 10 days before listed
    res = backtest_symbol(df, cfg, symbol="PENNY", universe_callback=uni_cb)
    # check that first trade entry date is >= 2022-06-15
    if res["trades"]:
        first_entry = pd.to_datetime(res["trades"][0]["entry_date"])
        assert first_entry >= pd.to_datetime("2022-06-15")
    # also test MIDCAP delisted: after delisted no new entries
    dates2 = pd.date_range("2024-08-10", periods=30, freq="B")
    df2 = pd.DataFrame({"date": dates2, "open": [100]*30, "high": [100]*30, "low": [100]*30, "close": [100]*30, "volume": [1000000]*30})
    df2 = compute_features(df2)
    df2["close"] = 100 * (1 + pd.Series(range(30))*0.01)
    df2["open"]=df2["close"]; df2["high"]=df2["close"]*1.01; df2["low"]=df2["close"]*0.99
    def uni_cb2(as_of): return get_universe(as_of, provider_name="mock", use_db=False)
    res2 = backtest_symbol(df2, cfg, symbol="MIDCAP", universe_callback=uni_cb2)
    # after delisted 2024-08-20, no entries should be after that
    for t in res2["trades"]:
        assert pd.to_datetime(t["entry_date"]) < pd.to_datetime("2024-08-20")

def test_delisted_forces_exit():
    import pandas as pd
    from app.backtesting.engine import backtest_symbol, BacktestConfig
    from app.data.universe import get_universe
    # enter before delist, hold through delist -> should force exit at delist
    dates = pd.date_range("2024-08-01", periods=30, freq="B")
    df = pd.DataFrame({"date": dates, "open": [100]*30, "high": [101]*30, "low": [99]*30, "close": [100]*30, "volume": [1000000]*30})
    # make rising so entry triggers early
    df["close"] = 100 + pd.Series(range(30))*2
    df["open"]=df["close"]; df["high"]=df["close"]+1; df["low"]=df["close"]-1
    from app.features.engine import compute_features
    df = compute_features(df)
    cfg = BacktestConfig(entry_momentum=0.001, max_holding_days=100)  # long hold, would not exit by time
    def uni_cb(as_of): return get_universe(as_of, provider_name="mock", use_db=False)
    res = backtest_symbol(df, cfg, symbol="MIDCAP", universe_callback=uni_cb)
    # if any trade entered before delist, it should have exit_reason delisted or exit before delist+hold
    # at least check that no holding extends beyond delisted date+1
    for t in res["trades"]:
        exit_d = pd.to_datetime(t["exit_date"])
        # exit should be <= delisted date (since delisted exclusive, forced exit on delisted)
        # we force exit on the delisted bar itself
        assert exit_d <= pd.to_datetime("2024-08-20") or t.get("exit_reason")=="delisted" or exit_d < pd.to_datetime("2024-08-21")

def test_missing_listed_date_always_eligible():
    from app.data.provider import Company
    from app.data.universe import get_universe
    # company with no listed_date should be always eligible (treat as listed long ago)
    # mock fallback: RELIANCE has listed 2000, but test a custom provider?
    # Instead test that get_universe with db containing null listed_date includes it
    import tempfile, pathlib
    from app.database.db import init_db
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    conn = init_db(db)
    conn.execute("INSERT OR REPLACE INTO companies(symbol, name, listed_date, delisted_date, status) VALUES(?,?,?,?,?)", ("NODATE","No Date Co", None, None, "active"))
    conn.commit()
    from app.data.universe import get_universe as gu
    uni = gu("1990-01-01", provider_name="mock", db_path=db)  # DB has NODATE with null listed, should be included
    assert "NODATE" in [c.symbol for c in uni]
    _cleanup(db)

def test_symbol_history_abstraction():
    import tempfile, pathlib
    from app.data.symbol_history import add_symbol_mapping, get_symbol_at, get_security_id_for_symbol
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    add_symbol_mapping("SEC123", "OLD", "2020-01-01", "2022-01-01", db_path=db)
    add_symbol_mapping("SEC123", "NEW", "2022-01-01", None, db_path=db)
    assert get_symbol_at("SEC123", "2021-06-01", db_path=db) == "OLD"
    assert get_symbol_at("SEC123", "2022-06-01", db_path=db) == "NEW"
    assert get_security_id_for_symbol("OLD", "2021-06-01", db_path=db) == "SEC123"
    assert get_security_id_for_symbol("NEW", "2022-06-01", db_path=db) == "SEC123"
    _cleanup(db)

def test_ingest_preserves_lifecycle():
    import tempfile, pathlib
    from app.data.universe import ingest_universe_to_db
    from app.database.db import get_conn
    db = pathlib.Path(tempfile.mktemp(suffix=".db"))
    n = ingest_universe_to_db(provider_name="mock", db_path=db)
    conn = get_conn(db)
    row = conn.execute("SELECT listed_date, delisted_date FROM companies WHERE symbol='PENNY'").fetchone()
    assert row["listed_date"] == "2022-06-15"
    row2 = conn.execute("SELECT listed_date, delisted_date FROM companies WHERE symbol='MIDCAP'").fetchone()
    assert row2["delisted_date"] == "2024-08-20"
    _cleanup(db)
