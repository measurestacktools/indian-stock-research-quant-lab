from app.portfolio.portfolio import create_portfolio, buy, sell, get_value
from app.data.registry import get_provider
import datetime
create_portfolio("demo",150)
prov=get_provider("mock")
df=prov.get_daily_prices("PENNY","2024-01-01", datetime.date.today().isoformat())
price=float(df["close"].iloc[-1])
print(buy("demo","PENNY",1,price))
print(get_value("demo", {"PENNY": price+5}))
