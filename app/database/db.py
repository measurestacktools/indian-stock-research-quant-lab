import sqlite3, hashlib
from pathlib import Path
from app.config.settings import get_db_path

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS companies(symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, isin TEXT, sector TEXT, industry TEXT, security_type TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS securities(id INTEGER PRIMARY KEY, company_id TEXT, symbol TEXT, exchange TEXT, type TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS prices_daily(id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, source TEXT, retrieved_at TEXT, hash TEXT, UNIQUE(symbol,date));
CREATE TABLE IF NOT EXISTS fundamentals(symbol TEXT, period TEXT, available_at TEXT, retrieved_at TEXT, source TEXT, hash TEXT, data_version TEXT, revenue REAL, profit REAL, eps REAL, roe REAL, roce REAL, debt_equity REAL, pe REAL, pb REAL, market_cap REAL, transform_hash TEXT, PRIMARY KEY(symbol, period, available_at));
CREATE TABLE IF NOT EXISTS corporate_actions(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, action_type TEXT, ex_date TEXT, record_date TEXT, payment_date TEXT, ratio_numerator REAL, ratio_denominator REAL, cash_amount REAL, currency TEXT DEFAULT 'INR', adjustment_factor REAL, source TEXT, retrieved_at TEXT, raw_hash TEXT, data_version TEXT DEFAULT 'v1', UNIQUE(symbol, action_type, ex_date, ratio_numerator, ratio_denominator, cash_amount));
CREATE TABLE IF NOT EXISTS news_items(id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, title TEXT, source TEXT, url TEXT, retrieved_at TEXT);
CREATE TABLE IF NOT EXISTS features_daily(symbol TEXT, date TEXT, ret_1d REAL, ret_5d REAL, ret_21d REAL, ret_63d REAL, ret_126d REAL, ret_252d REAL, ma20 REAL, ma50 REAL, ma200 REAL, vol20 REAL, atr14 REAL, drawdown REAL, vol_chg REAL, rel_vol REAL, dist_52w_high REAL, dist_52w_low REAL, PRIMARY KEY(symbol,date));
CREATE TABLE IF NOT EXISTS screening_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, config_json TEXT, dataset_version TEXT, universe_count INTEGER);
CREATE TABLE IF NOT EXISTS screening_results(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, symbol TEXT, stage TEXT, passed INTEGER, reason_json TEXT, FOREIGN KEY(run_id) REFERENCES screening_runs(id));
CREATE TABLE IF NOT EXISTS ai_analyses(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, date TEXT, model TEXT, prompt_version TEXT, input_hash TEXT, output_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS ai_critiques(id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, output_json TEXT, created_at TEXT, FOREIGN KEY(analysis_id) REFERENCES ai_analyses(id));
CREATE TABLE IF NOT EXISTS backtests(id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT, start TEXT, end TEXT, config_json TEXT, metrics_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS paper_portfolios(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, initial_capital REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS paper_positions(id INTEGER PRIMARY KEY AUTOINCREMENT, portfolio_id INTEGER, symbol TEXT, qty INTEGER, avg_price REAL, UNIQUE(portfolio_id,symbol), FOREIGN KEY(portfolio_id) REFERENCES paper_portfolios(id));
CREATE TABLE IF NOT EXISTS paper_trades(id INTEGER PRIMARY KEY AUTOINCREMENT, portfolio_id INTEGER, symbol TEXT, side TEXT, qty INTEGER, price REAL, costs REAL, timestamp TEXT, FOREIGN KEY(portfolio_id) REFERENCES paper_portfolios(id));
CREATE TABLE IF NOT EXISTS performance_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, portfolio_id INTEGER, date TEXT, value REAL, cash REAL, pnl REAL, FOREIGN KEY(portfolio_id) REFERENCES paper_portfolios(id));
CREATE TABLE IF NOT EXISTS system_events(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, level TEXT, message TEXT, context_json TEXT);
CREATE INDEX IF NOT EXISTS idx_prices_sym_date ON prices_daily(symbol,date);
CREATE INDEX IF NOT EXISTS idx_feat_sym_date ON features_daily(symbol,date);
CREATE INDEX IF NOT EXISTS idx_screen_run ON screening_results(run_id);
CREATE INDEX IF NOT EXISTS idx_fund_symbol_avail ON fundamentals(symbol, available_at);
CREATE INDEX IF NOT EXISTS idx_ca_symbol_ex ON corporate_actions(symbol, ex_date);
'''

PIT_VIEW_SQL = '''
CREATE VIEW IF NOT EXISTS fundamentals_pit AS
SELECT symbol, period, available_at, retrieved_at, source, hash, data_version,
       revenue, profit, eps, roe, roce, debt_equity, pe, pb, market_cap, transform_hash
FROM fundamentals;
'''

def get_conn(db_path=None):
    if db_path is None: db_path = get_db_path()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _table_has_column(conn, table, col):
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except: return False

def _migrate_legacy_fundamentals(conn):
    # detect legacy schema with 'date' column
    if not _table_has_column(conn, "fundamentals", "period"):
        # legacy exists — rename and recreate
        # check if legacy table has date column
        try:
            conn.execute("ALTER TABLE fundamentals RENAME TO fundamentals_legacy")
        except Exception:
            pass
        # create new table
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS fundamentals(symbol TEXT, period TEXT, available_at TEXT, retrieved_at TEXT, source TEXT, hash TEXT, data_version TEXT, revenue REAL, profit REAL, eps REAL, roe REAL, roce REAL, debt_equity REAL, pe REAL, pb REAL, market_cap REAL, transform_hash TEXT, PRIMARY KEY(symbol, period, available_at));
        CREATE INDEX IF NOT EXISTS idx_fund_symbol_avail ON fundamentals(symbol, available_at);
        """)
        # migrate data: map legacy date -> period & available_at
        try:
            rows = conn.execute("SELECT * FROM fundamentals_legacy").fetchall()
            for r in rows:
                d = dict(r)
                period = d.get("date") or d.get("period") or ""
                available_at = d.get("date") or ""  # legacy: available_at == period
                h = hashlib.sha256(f"{d.get('symbol')}|{period}|{available_at}".encode()).hexdigest()[:16]
                conn.execute("""INSERT OR IGNORE INTO fundamentals(symbol, period, available_at, retrieved_at, source, hash, data_version, revenue, profit, eps, roe, roce, debt_equity, pe, pb, market_cap)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (d.get("symbol"), period, available_at, d.get("retrieved_at"), d.get("source"), h, "v1",
                              d.get("revenue"), d.get("profit"), d.get("eps"), d.get("roe"), d.get("roce"), d.get("debt_equity"), d.get("pe"), d.get("pb"), d.get("market_cap")))
            conn.commit()
        except Exception as e:
            # if legacy empty or not exists, ignore
            pass

def _migrate_legacy_corporate_actions(conn):
    # old schema had (id, symbol, date, type, ratio, source) — detect by absence of ex_date
    if not _table_has_column(conn, "corporate_actions", "ex_date"):
        try:
            conn.execute("ALTER TABLE corporate_actions RENAME TO corporate_actions_legacy")
        except Exception:
            pass
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS corporate_actions(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, action_type TEXT, ex_date TEXT, record_date TEXT, payment_date TEXT, ratio_numerator REAL, ratio_denominator REAL, cash_amount REAL, currency TEXT DEFAULT 'INR', adjustment_factor REAL, source TEXT, retrieved_at TEXT, raw_hash TEXT, data_version TEXT DEFAULT 'v1', UNIQUE(symbol, action_type, ex_date, ratio_numerator, ratio_denominator, cash_amount));
        CREATE INDEX IF NOT EXISTS idx_ca_symbol_ex ON corporate_actions(symbol, ex_date);
        """)
        try:
            rows = conn.execute("SELECT * FROM corporate_actions_legacy").fetchall()
            for r in rows:
                d = dict(r)
                ex = d.get("date") or ""
                typ = d.get("type") or "split"
                ratio = d.get("ratio")
                num = float(ratio) if ratio is not None else None
                den = 1.0 if num is not None else None
                # for dividend legacy ratio as cash?
                if typ == "dividend" and num is not None:
                    cash = num
                    num = None
                    den = None
                else:
                    cash = None
                adj = (den/num) if (num and den and typ in ("split","bonus")) else 1.0
                h = hashlib.sha256(f"{d.get('symbol')}|{typ}|{ex}|{num}".encode()).hexdigest()[:16]
                conn.execute("""INSERT OR IGNORE INTO corporate_actions(symbol, action_type, ex_date, ratio_numerator, ratio_denominator, cash_amount, adjustment_factor, source, raw_hash, data_version)
                                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                             (d.get("symbol"), typ, ex, num, den, cash, adj, d.get("source"), h, "v1"))
            conn.commit()
        except Exception:
            pass

def init_db(db_path=None):
    conn = get_conn(db_path)
    # run migrations before creating new schema? Check legacy first
    # need to ensure we don't fail if tables already new
    try:
        _migrate_legacy_fundamentals(conn)
    except Exception as e:
        conn.execute("INSERT INTO system_events(timestamp, level, message, context_json) VALUES(datetime('now'),'WARN','fundamentals migration failed','{}')")
    try:
        _migrate_legacy_corporate_actions(conn)
    except Exception:
        pass
    conn.executescript(SCHEMA)
    conn.executescript(PIT_VIEW_SQL)
    conn.commit()
    return conn
