"""
Symbol history — stable security_id, ticker changes.

Current data sources (YFinance/Mock) lack historical symbol mappings.
This module provides abstraction and documents limitation.

Table security_symbols(security_id, symbol, start_date, end_date, source)
- security_id stable (e.g., INE... or internal)
- symbol is ticker at that period
- start_date inclusive, end_date exclusive (next symbol starts)

Example:
  security_id=RELIANCE, symbol=RELIANCE, start 2000-01-01, end NULL (current)
  After rename: security_id=OLDCO, old symbol OLD, new symbol NEW, start/end split.

Limitation: Mock/YFinance currently supply only current symbol; history must be
provided manually or via future NSE archival source. The abstraction is ready,
but no inventing of mappings.
"""
from typing import Optional, List, Dict
from app.database.db import get_conn, init_db
import datetime

def add_symbol_mapping(security_id: str, symbol: str, start_date: str, end_date: Optional[str] = None, source="manual", db_path=None):
    conn = init_db(db_path)
    conn.execute("INSERT OR REPLACE INTO security_symbols(security_id, symbol, start_date, end_date, source) VALUES(?,?,?,?,?)",
                 (security_id, symbol, start_date, end_date, source))
    conn.commit()

def get_symbol_at(security_id: str, as_of: str, db_path=None) -> Optional[str]:
    conn = get_conn(db_path)
    row = conn.execute("""
        SELECT symbol FROM security_symbols
        WHERE security_id=? AND start_date <= ? AND (end_date IS NULL OR end_date > ?)
        ORDER BY start_date DESC LIMIT 1
    """, (security_id, as_of, as_of)).fetchone()
    return row["symbol"] if row else None

def get_security_id_for_symbol(symbol: str, as_of: str, db_path=None) -> Optional[str]:
    conn = get_conn(db_path)
    row = conn.execute("""
        SELECT security_id FROM security_symbols
        WHERE symbol=? AND start_date <= ? AND (end_date IS NULL OR end_date > ?)
        ORDER BY start_date DESC LIMIT 1
    """, (symbol, as_of, as_of)).fetchone()
    if row: return row["security_id"]
    # fallback: security_id == symbol if no history
    return symbol

def list_history(security_id: str, db_path=None) -> List[Dict]:
    conn = get_conn(db_path)
    rows = conn.execute("SELECT * FROM security_symbols WHERE security_id=? ORDER BY start_date", (security_id,)).fetchall()
    return [dict(r) for r in rows]
