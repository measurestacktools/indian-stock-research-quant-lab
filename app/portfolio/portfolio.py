import datetime, sqlite3, json
from app.database.db import get_conn, init_db
from app.portfolio.costs import calc_costs, CostAssumptions

def create_portfolio(name="default", initial_capital=150, db_path=None):
    conn=init_db(db_path)
    try: conn.execute("INSERT INTO paper_portfolios(name,initial_capital,created_at) VALUES(?,?,?)", (name, initial_capital, datetime.datetime.utcnow().isoformat()))
    except sqlite3.IntegrityError: pass
    conn.commit()
    row=conn.execute("SELECT * FROM paper_portfolios WHERE name=?", (name,)).fetchone()
    return dict(row)

def get_portfolio(name="default", db_path=None):
    conn=get_conn(db_path)
    row=conn.execute("SELECT * FROM paper_portfolios WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None

def buy(portfolio_name, symbol, qty, price, costs=None, db_path=None, timestamp=None):
    conn=get_conn(db_path)
    port=get_portfolio(portfolio_name, db_path)
    if not port: raise ValueError("portfolio not found")
    if qty<=0: raise ValueError("qty must be >0")
    if timestamp is None: timestamp=datetime.datetime.utcnow().isoformat()
    if costs is None: costs=calc_costs(price,qty)["total"]
    total_cost = price*qty + costs
    # check cash: compute current cash
    cash = get_cash(portfolio_name, db_path)
    if total_cost > cash + 1e-6: raise ValueError(f"Insufficient cash ₹{cash:.2f} for cost ₹{total_cost:.2f}")
    conn.execute("INSERT INTO paper_trades(portfolio_id,symbol,side,qty,price,costs,timestamp) VALUES(?,?,?,?,?,?,?)",
                 (port["id"], symbol, "BUY", qty, price, costs, timestamp))
    # upsert position
    pos=conn.execute("SELECT * FROM paper_positions WHERE portfolio_id=? AND symbol=?", (port["id"], symbol)).fetchone()
    if pos:
        new_qty=pos["qty"]+qty
        new_avg=(pos["avg_price"]*pos["qty"] + price*qty)/new_qty
        conn.execute("UPDATE paper_positions SET qty=?, avg_price=? WHERE id=?", (new_qty, new_avg, pos["id"]))
    else:
        conn.execute("INSERT INTO paper_positions(portfolio_id,symbol,qty,avg_price) VALUES(?,?,?,?)", (port["id"], symbol, qty, price))
    conn.commit()
    return {"symbol":symbol,"qty":qty,"price":price,"costs":costs}

def sell(portfolio_name, symbol, qty, price, db_path=None, timestamp=None):
    conn=get_conn(db_path)
    port=get_portfolio(portfolio_name, db_path)
    if not port: raise ValueError("portfolio not found")
    if timestamp is None: timestamp=datetime.datetime.utcnow().isoformat()
    pos=conn.execute("SELECT * FROM paper_positions WHERE portfolio_id=? AND symbol=?", (port["id"], symbol)).fetchone()
    if not pos or pos["qty"]<qty: raise ValueError("Insufficient shares")
    costs=calc_costs(price,qty)["total"]
    conn.execute("INSERT INTO paper_trades(portfolio_id,symbol,side,qty,price,costs,timestamp) VALUES(?,?,?,?,?,?,?)",
                 (port["id"], symbol, "SELL", qty, price, costs, timestamp))
    new_qty=pos["qty"]-qty
    if new_qty==0: conn.execute("DELETE FROM paper_positions WHERE id=?", (pos["id"],))
    else: conn.execute("UPDATE paper_positions SET qty=? WHERE id=?", (new_qty, pos["id"]))
    conn.commit()
    # realized pnl
    realized=(price - pos["avg_price"])*qty - costs
    return {"realized_pnl":realized,"costs":costs}

def get_cash(portfolio_name, db_path=None):
    conn=get_conn(db_path)
    port=get_portfolio(portfolio_name, db_path)
    if not port: return 0
    trades=conn.execute("SELECT * FROM paper_trades WHERE portfolio_id=?", (port["id"],)).fetchall()
    cash=port["initial_capital"]
    for t in trades:
        if t["side"]=="BUY": cash -= t["price"]*t["qty"] + t["costs"]
        else: cash += t["price"]*t["qty"] - t["costs"]
    return cash

def get_positions(portfolio_name, db_path=None):
    conn=get_conn(db_path)
    port=get_portfolio(portfolio_name, db_path)
    if not port: return []
    rows=conn.execute("SELECT * FROM paper_positions WHERE portfolio_id=?", (port["id"],)).fetchall()
    return [dict(r) for r in rows]

def get_value(portfolio_name, price_map: dict, db_path=None):
    # price_map symbol->current price
    positions=get_positions(portfolio_name, db_path)
    holdings=sum(price_map.get(p["symbol"], p["avg_price"])*p["qty"] for p in positions)
    cash=get_cash(portfolio_name, db_path)
    total=cash+holdings
    port=get_portfolio(portfolio_name, db_path)
    pnl=total - port["initial_capital"] if port else 0
    # drawdown approx from snapshots
    return {"cash":cash,"holdings":holdings,"total":total,"unrealized_pnl":pnl,"positions":positions}

def snapshot(portfolio_name, price_map: dict, db_path=None):
    v=get_value(portfolio_name, price_map, db_path)
    conn=get_conn(db_path)
    port=get_portfolio(portfolio_name, db_path)
    conn.execute("INSERT INTO performance_snapshots(portfolio_id,date,value,cash,pnl) VALUES(?,?,?,?,?)",
                 (port["id"], datetime.datetime.utcnow().isoformat(), v["total"], v["cash"], v["unrealized_pnl"]))
    conn.commit()
    return v
