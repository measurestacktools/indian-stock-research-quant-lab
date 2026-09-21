"""
Historical universe with survivorship-bias protection.

- get_universe(as_of) returns securities where listed_date <= as_of and (delisted_date is None or delisted_date > as_of)
  Inclusive listed, exclusive delisted, documented consistently.
- Snapshots are deterministic and hash-based.
- DB-backed when companies table has listed/delisted; falls back to provider.
"""
import hashlib, datetime
from typing import List, Optional
import pandas as pd
from app.data.provider import Company
from app.database.db import get_conn, init_db
from app.data.registry import get_provider

def _as_of_normalize(as_of: Optional[str]) -> Optional[str]:
    if as_of is None: return None
    try: return pd.to_datetime(as_of).strftime("%Y-%m-%d")
    except: return as_of

def get_universe(as_of: Optional[str] = None, provider_name: str = "mock", db_path=None,
                 universe_definition: str = "nse_equities", use_db: bool = True) -> List[Company]:
    """
    Reusable historical universe. Lives behind interface, not hard-coded in backtester.
    """
    as_of_norm = _as_of_normalize(as_of)
    # try DB first if use_db
    if use_db:
        try:
            conn = get_conn(db_path)
            init_db(db_path)
            # check if companies has listed_date data
            rows = None
            if as_of_norm is None:
                rows = conn.execute("SELECT * FROM companies WHERE status != 'delisted' OR status IS NULL").fetchall()
                # also include delisted but not yet? For current, show active only
                # we will filter via query below for historical; for current we return all with delisted_date null or future
                # simpler: for None, return all where delisted_date is null or delisted_date > today
                today = datetime.date.today().isoformat()
                rows = conn.execute("""
                    SELECT * FROM companies
                    WHERE (listed_date IS NULL OR listed_date <= ?)
                      AND (delisted_date IS NULL OR delisted_date > ?)
                """, (today, today)).fetchall()
                # if table empty, fallback to provider
                if not rows:
                    raise ValueError("empty DB, fallback")
            else:
                rows = conn.execute("""
                    SELECT * FROM companies
                    WHERE (listed_date IS NULL OR listed_date <= ?)
                      AND (delisted_date IS NULL OR delisted_date > ?)
                """, (as_of_norm, as_of_norm)).fetchall()
            if rows:
                out=[]
                for r in rows:
                    d=dict(r)
                    out.append(Company(
                        symbol=d["symbol"], name=d.get("name") or d["symbol"], exchange=d.get("exchange") or "NSE",
                        isin=d.get("isin") or "", sector=d.get("sector") or "", industry=d.get("industry") or "",
                        security_type=d.get("security_type") or "EQ", status=d.get("status") or "active",
                        security_id=d.get("security_id") or d["symbol"], company_id=d.get("company_id") or d["symbol"],
                        listed_date=d.get("listed_date"), delisted_date=d.get("delisted_date"),
                        source=d.get("source") or "db", retrieved_at=d.get("retrieved_at"), data_version=d.get("data_version") or "v1"
                    ))
                return out
        except Exception:
            pass
    # fallback to provider
    try:
        prov = get_provider(provider_name)
        # provider now supports as_of
        try: return prov.get_universe(as_of=as_of_norm)
        except TypeError: return prov.get_universe()
    except: return []

def create_snapshot(as_of: str, universe_definition: str = "nse_equities", provider_name="mock", db_path=None, source="system") -> str:
    """Create deterministic snapshot for as_of. Returns snapshot_id (hash)."""
    as_of_norm = _as_of_normalize(as_of)
    universe = get_universe(as_of_norm, provider_name, db_path, universe_definition)
    # deterministic hash
    symbols_sorted = sorted([c.symbol for c in universe])
    data_version = "v1"
    raw = f"{universe_definition}|{as_of_norm}|{','.join(symbols_sorted)}|{data_version}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    snapshot_id = f"{as_of_norm}_{h}"
    conn = init_db(db_path)
    created_at = datetime.datetime.utcnow().isoformat()
    # delete existing for same as_of+definition to keep deterministic (replace)
    conn.execute("DELETE FROM universe_snapshots WHERE as_of=? AND universe_definition=?", (as_of_norm, universe_definition))
    for c in universe:
        conn.execute("""
            INSERT OR IGNORE INTO universe_snapshots(snapshot_id, as_of, universe_definition, security_id, symbol, exchange, listed_date, delisted_date, source, created_at, data_version, hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (snapshot_id, as_of_norm, universe_definition, c.security_id, c.symbol, c.exchange, c.listed_date, c.delisted_date, source, created_at, data_version, h))
    conn.commit()
    return snapshot_id

def get_snapshot(as_of: str, universe_definition="nse_equities", db_path=None):
    as_of_norm = _as_of_normalize(as_of)
    conn = get_conn(db_path)
    rows = conn.execute("SELECT * FROM universe_snapshots WHERE as_of=? AND universe_definition=? ORDER BY symbol", (as_of_norm, universe_definition)).fetchall()
    return [dict(r) for r in rows]

def list_snapshots(db_path=None):
    conn = get_conn(db_path)
    rows = conn.execute("SELECT as_of, universe_definition, hash, COUNT(*) as cnt, MIN(created_at) as created_at FROM universe_snapshots GROUP BY as_of, universe_definition, hash ORDER BY as_of").fetchall()
    return [dict(r) for r in rows]

def ingest_universe_to_db(provider_name="mock", db_path=None):
    """Populate companies table from provider with lifecycle fields."""
    prov = get_provider(provider_name)
    uni = prov.get_universe()
    conn = init_db(db_path)
    for c in uni:
        # upsert
        conn.execute("""
            INSERT OR REPLACE INTO companies(symbol, name, exchange, isin, sector, industry, security_type, status, security_id, company_id, listed_date, delisted_date, source, retrieved_at, data_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (c.symbol, c.name, c.exchange, c.isin, c.sector, c.industry, c.security_type, c.status, c.security_id, c.company_id, c.listed_date, c.delisted_date, c.source, c.retrieved_at or datetime.datetime.utcnow().isoformat(), c.data_version))
    conn.commit()
    return len(uni)
