import hashlib, json, time, pathlib, pickle
from pathlib import Path
CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def cache_key(*parts): return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]

def get_cache(key, ttl_seconds=86400):
    p = CACHE_DIR / f"{key}.pkl"
    if not p.exists(): return None
    if time.time() - p.stat().st_mtime > ttl_seconds: return None
    try: return pickle.loads(p.read_bytes())
    except: return None

def set_cache(key, value):
    p = CACHE_DIR / f"{key}.pkl"
    p.write_bytes(pickle.dumps(value))

def clear_cache(): [f.unlink() for f in CACHE_DIR.glob("*.pkl")]
