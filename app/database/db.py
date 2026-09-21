import sqlite3
from pathlib import Path
from app.config.settings import get_db_path

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS companies(symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, isin TEXT, sector TEXT, industry TEXT, security_type TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS securities(id INTEGER PRIMARY KEY, company_id TEXT, symbol TEXT, exchange TEXT, type TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS prices_daily(id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, source TEXT, retrieved_at TEXT, hash TEXT, UNIQUE(symbol,date));
CREATE TABLE IF NOT EXISTS fundamentals(symbol TEXT, date TEXT, revenue REAL, profit REAL, eps REAL, roe REAL, roce REAL, debt_equity REAL, pe REAL, pb REAL, market_cap REAL, source TEXT, retrieved_at TEXT, PRIMARY KEY(symbol,date));
CREATE TABLE IF NOT EXISTS corporate_actions(id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, type TEXT, ratio REAL, source TEXT);
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
'''

def get_conn(db_path=None):
    if db_path is None: db_path = get_db_path()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=None):
    conn = get_conn(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
