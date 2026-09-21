"""
Point-in-time fundamentals layer.

Critical rule: availability is determined by available_at, NOT period.
"""
import hashlib, datetime
import pandas as pd
from typing import Optional, Dict, List
from app.database.db import get_conn, init_db

def _hash_fund(symbol, period, available_at, payload: dict) -> str:
    raw = f"{symbol}|{period}|{available_at}|{sorted(payload.items())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def insert_fundamental(symbol: str, period: str, available_at: str, metrics: dict,
                       source="manual", retrieved_at=None, data_version="v1", db_path=None):
    """
    Insert PIT fundamental. Never overwrites history — uses INSERT OR REPLACE
    on PK (symbol, period, available_at) so revisions are preserved as separate rows.
    """
    if retrieved_at is None: retrieved_at = datetime.datetime.utcnow().isoformat()
    h = _hash_fund(symbol, period, available_at, metrics)
    transform_hash = hashlib.sha256(str(metrics).encode()).hexdigest()[:16]
    conn = init_db(db_path)
    conn.execute("""INSERT OR REPLACE INTO fundamentals
                    (symbol, period, available_at, retrieved_at, source, hash, data_version,
                     revenue, profit, eps, roe, roce, debt_equity, pe, pb, market_cap, transform_hash)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (symbol, period, available_at, retrieved_at, source, h, data_version,
                  metrics.get("revenue"), metrics.get("profit"), metrics.get("eps"),
                  metrics.get("roe"), metrics.get("roce"), metrics.get("debt_equity"),
                  metrics.get("pe"), metrics.get("pb"), metrics.get("market_cap"), transform_hash))
    conn.commit()
    return h

def get_fundamentals_as_of(symbol: str, as_of: str, db_path=None) -> Optional[Dict]:
    """
    Return latest PIT record where available_at <= as_of.
    Deterministically selects max(available_at) where available_at <= as_of,
    and if multiple same available_at, latest retrieved_at.
    Returns None if none available (marks unavailable, never fabricates).
    """
    conn = get_conn(db_path)
    # ensure table migrated
    init_db(db_path)
    # normalize as_of to ISO
    try: as_of_norm = pd.to_datetime(as_of).isoformat()[:10]
    except: as_of_norm = as_of
    row = conn.execute("""
        SELECT * FROM fundamentals
        WHERE symbol=? AND available_at <= ?
        ORDER BY available_at DESC, retrieved_at DESC
        LIMIT 1
    """, (symbol, as_of_norm)).fetchone()
    if row is None:
        return None
    return dict(row)

def get_fundamentals_history(symbol: str, db_path=None) -> List[Dict]:
    conn = get_conn(db_path)
    rows = conn.execute("SELECT * FROM fundamentals WHERE symbol=? ORDER BY period, available_at", (symbol,)).fetchall()
    return [dict(r) for r in rows]

def list_pit_coverage(db_path=None) -> Dict:
    conn = get_conn(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM fundamentals").fetchone()["c"]
        symbols = conn.execute("SELECT COUNT(DISTINCT symbol) as c FROM fundamentals").fetchone()["c"]
        latest = conn.execute("SELECT MAX(available_at) as m FROM fundamentals").fetchone()["m"]
        return {"total_records": total, "symbols": symbols, "latest_available_at": latest}
    except: return {"total_records":0,"symbols":0,"latest_available_at":None}
