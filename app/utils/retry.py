import time, random, logging
logger=logging.getLogger(__name__)
def with_retry(fn, retries=3, backoff=1.0, *a, **kw):
    for i in range(retries):
        try: return fn(*a, **kw)
        except Exception as e:
            if i==retries-1: raise
            sleep = backoff * (2**i) + random.uniform(0,0.5)
            logger.warning(f"Retry {i+1}/{retries} after {e}, sleep {sleep:.1f}s")
            time.sleep(sleep)
