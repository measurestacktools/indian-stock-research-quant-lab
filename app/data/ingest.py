import argparse, logging, datetime, hashlib, sqlite3
import pandas as pd
from pathlib import Path
from app.database.db import init_db, get_conn
from app.data.registry import get_provider
from app.utils.hashing import data_hash
from app.config.settings import get_db_path

logger = logging.getLogger(__name__)

def ingest(provider_name="mock", symbols=None, start="2023-01-01", end=None, db_path=None):
    if end is None: end = datetime.date.today().isoformat()
    provider = get_provider(provider_name)
    conn = init_db(db_path)
    universe = provider.get_universe()
    if symbols: universe = [c for c in universe if c.symbol in symbols]
    # upsert companies with lifecycle
    for c in universe:
        conn.execute("""
            INSERT OR REPLACE INTO companies(symbol,name,exchange,isin,sector,industry,security_type,status,security_id,company_id,listed_date,delisted_date,source,retrieved_at,data_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (c.symbol,c.name,c.exchange,c.isin,c.sector,c.industry,c.security_type,c.status,
              getattr(c,'security_id',c.symbol), getattr(c,'company_id',c.symbol), getattr(c,'listed_date',None), getattr(c,'delisted_date',None),
              getattr(c,'source','manual'), getattr(c,'retrieved_at',datetime.datetime.utcnow().isoformat()), getattr(c,'data_version','v1')))
    conn.commit()
    total=0
    for c in universe:
        try:
            df = provider.get_daily_prices(c.symbol, start, end)
            if df is None or df.empty: continue
            for _, row in df.iterrows():
                d = pd.to_datetime(row["date"]).date().isoformat()
                h = data_hash(f"{c.symbol}{d}{row['close']}".encode())
                conn.execute("INSERT OR REPLACE INTO prices_daily(symbol,date,open,high,low,close,volume,source,retrieved_at,hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (c.symbol,d,float(row["open"]),float(row["high"]),float(row["low"]),float(row["close"]),int(row["volume"]),provider.name,datetime.datetime.utcnow().isoformat(),h))
                total+=1
            # save raw parquet immutable
            raw_dir = Path("data/raw")/provider.name/c.symbol
            raw_dir.mkdir(parents=True, exist_ok=True)
            parquet_path = raw_dir / f"{start}_{end}.parquet"
            try: df.to_parquet(parquet_path)
            except: df.to_csv(raw_dir / f"{start}_{end}.csv", index=False)
        except Exception as e:
            logger.warning(f"Ingest failed {c.symbol}: {e}")
            conn.execute("INSERT INTO system_events(timestamp,level,message,context_json) VALUES(?,?,?,?)",
                         (datetime.datetime.utcnow().isoformat(),"WARN",f"Ingest failed {c.symbol}: {e}", "{}"))
    conn.commit()
    logger.info(f"Ingested {total} price rows from {provider.name}")
    return total

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--mock", action="store_true")
    args=ap.parse_args()
    prov = "mock" if args.mock else args.provider
    ingest(prov, start=args.start, end=args.end)
