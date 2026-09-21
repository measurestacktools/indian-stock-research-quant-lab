import logging, sys
def setup_logging(level=logging.INFO):
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", stream=sys.stdout)
    return logging.getLogger("stock_lab")
logger = setup_logging()
