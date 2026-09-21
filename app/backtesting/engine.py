import pandas as pd, numpy as np, json, datetime
from dataclasses import dataclass
from typing import Dict

@dataclass
class BacktestConfig:
    entry_momentum: float=0.02
    max_holding_days: int=63
    stop_loss_pct: float=0.08
    brokerage_pct: float=0.001
    slippage_pct: float=0.001

def _is_in_universe(symbol: str, as_of: str, universe_callback) -> bool:
    if universe_callback is None: return True
    try:
        eligible = universe_callback(as_of)
        # callback may return List[Company] or List[str] or List[dict]
        if not eligible: return False
        # normalize to symbols
        syms = set()
        for e in eligible:
            if isinstance(e, str): syms.add(e)
            elif isinstance(e, dict): syms.add(e.get("symbol") or e.get("security_id"))
            else: syms.add(getattr(e, "symbol", str(e)))
        return symbol in syms
    except: return True

def backtest_symbol(df: pd.DataFrame, config: BacktestConfig, symbol: str = None, use_pit_fundamentals: bool = False, pit_callback=None, universe_callback=None):
    """
    Backtest at time T uses only data <=T.
    If use_pit_fundamentals True, fundamental signal at T uses get_fundamentals_as_of(T)
    (available_at <= T), never period <= T.

    Survivorship: if universe_callback provided, symbol must be in get_universe(as_of=T) to generate signal/execution.
    inclusive listed_date, exclusive delisted_date handled by universe layer.

    Args:
        df: price dataframe with date, open, high, low, close, volume (already corporate-action adjusted if needed)
        symbol: required when use_pit_fundamentals True or survivorship to query PIT/universe
        pit_callback: optional function (symbol, as_of_str) -> dict | None. Defaults to app.data.fundamentals.get_fundamentals_as_of
        universe_callback: optional function (as_of_str) -> List[Company] (e.g., lambda d: get_universe(as_of=d))
    """
    # NO LOOKAHEAD: at date T, only use data <=T
    df=df.sort_values("date").copy().reset_index(drop=True)
    trades=[]
    position=None
    entry_price=None
    entry_date=None
    if use_pit_fundamentals and pit_callback is None and symbol:
        try:
            from app.data.fundamentals import get_fundamentals_as_of
            pit_callback = get_fundamentals_as_of
        except Exception:
            pit_callback = lambda s, d: None
    for i in range(63, len(df)-1):  # need 63d history
        row=df.iloc[i]
        prev=df.iloc[:i+1]  # only up to i
        # signal: momentum > threshold
        mom = (row["close"] - df.iloc[i-63]["close"])/df.iloc[i-63]["close"] if i>=63 else np.nan
        # PIT fundamentals filter: if enabled, require roe >=12 etc. using PIT as_of=row['date']
        pit_ok = True
        pit_fund = None
        if use_pit_fundamentals and symbol and pit_callback:
            as_of = str(row["date"])[:10]
            try:
                pit_fund = pit_callback(symbol, as_of)
            except: pit_fund = None
            if pit_fund is None:
                # mark unavailable — for this baseline, skip entry when PIT unavailable if you want strict PIT
                # For now, we do NOT block momentum-only strategy on missing fundamentals, but we record that pit was missing.
                # If you want fundamental-gated strategy, set pit_ok = pit_fund is not None and pit_fund.get('roe',0) >=12
                pit_ok = True  # change to False to enforce PIT gating
            else:
                # example: if fundamentals show roe <12, could veto signal
                # keep pit_ok True for baseline momentum; fundamental-gated variant can check here
                pass
        # survivorship: symbol must be in universe at as_of
        universe_ok = True
        if symbol and universe_callback:
            as_of_u = str(row["date"])[:10]
            universe_ok = _is_in_universe(symbol, as_of_u, universe_callback)
            if not universe_ok:
                pit_ok = False  # not eligible, cannot signal
        signal = (mom > config.entry_momentum if pd.notna(mom) else False) and pit_ok and universe_ok
        if position is None and signal:
            # also check universe at entry date T+1? Must be eligible at entry
            if symbol and universe_callback:
                entry_as_of = str(df.iloc[i+1]["date"])[:10]
                if not _is_in_universe(symbol, entry_as_of, universe_callback):
                    continue
            # enter next open (T+1)
            nxt = df.iloc[i+1]
            entry_price = nxt["open"] * (1+config.slippage_pct)
            entry_date = nxt["date"]
            position={"entry_idx":i+1,"price":entry_price,"date":entry_date, "mom":mom}
        elif position is not None:
            # if delisted during holding, force exit at delisting
            if symbol and universe_callback:
                cur_as_of = str(row["date"])[:10]
                if not _is_in_universe(symbol, cur_as_of, universe_callback):
                    # delisted — exit at current open
                    exit_price = row["open"] * (1- config.slippage_pct)
                    exit_date = row["date"]
                    buy_cost = position["price"]*config.brokerage_pct
                    sell_cost = exit_price*config.brokerage_pct
                    pnl = exit_price - position["price"] - buy_cost - sell_cost
                    trades.append({"entry_date":str(position["date"]),"exit_date":str(exit_date),"entry_price":float(position["price"]),"exit_price":float(exit_price),"pnl":float(pnl),"return":float(pnl/position["price"]),"holding":int(i - position["entry_idx"]), "exit_reason":"delisted"})
                    position=None
                    continue
            # check exit: holding period or stop
            holding = i - position["entry_idx"]
            cur_close = row["close"]
            ret = (cur_close - position["price"])/position["price"]
            if holding >= config.max_holding_days or ret <= -config.stop_loss_pct:
                exit_price = df.iloc[i+1]["open"] * (1- config.slippage_pct) if i+1<len(df) else cur_close
                exit_date = df.iloc[i+1]["date"] if i+1<len(df) else row["date"]
                # costs
                buy_cost = position["price"]*config.brokerage_pct
                sell_cost = exit_price*config.brokerage_pct
                pnl = exit_price - position["price"] - buy_cost - sell_cost
                ret_pct = pnl/position["price"]
                trades.append({"entry_date":str(position["date"]),"exit_date":str(exit_date),"entry_price":float(position["price"]),"exit_price":float(exit_price),"pnl":float(pnl),"return":float(ret_pct),"holding":int(holding)})
                position=None
    # if still open, close at last close
    if position is not None:
        last=df.iloc[-1]
        exit_price=last["close"]*(1-config.slippage_pct)
        buy_cost=position["price"]*config.brokerage_pct
        sell_cost=exit_price*config.brokerage_pct
        pnl=exit_price-position["price"]-buy_cost-sell_cost
        trades.append({"entry_date":str(position["date"]),"exit_date":str(last["date"]),"entry_price":float(position["price"]),"exit_price":float(exit_price),"pnl":float(pnl),"return":float(pnl/position["price"]),"holding":int(len(df)-1 - position["entry_idx"])})
    # metrics
    if not trades:
        return {"trades":[],"metrics":{"total_return":0,"num_trades":0,"win_rate":0,"avg_win":0,"avg_loss":0,"profit_factor":0,"max_drawdown":0,"volatility":0,"cagr":0,"transaction_costs":0}}
    rets=[t["return"] for t in trades]
    wins=[r for r in rets if r>0]; losses=[r for r in rets if r<=0]
    total_ret = float(np.prod([1+r for r in rets])-1) if rets else 0
    win_rate = len(wins)/len(rets) if rets else 0
    avg_win = float(np.mean(wins)) if wins else 0
    avg_loss = float(np.mean(losses)) if losses else 0
    profit_factor = float(sum(wins)/abs(sum(losses))) if losses and sum(losses)!=0 else float("inf") if wins else 0
    # drawdown of equity curve
    equity=np.cumprod([1+r for r in rets])
    roll_max=np.maximum.accumulate(equity)
    dd=(equity-roll_max)/roll_max
    max_dd=float(dd.min()) if len(dd)>0 else 0
    vol=float(np.std(rets)*(len(rets)**0.5)) if len(rets)>1 else 0
    # cagr approx: total_ret over period
    days=(pd.to_datetime(df["date"].iloc[-1])-pd.to_datetime(df["date"].iloc[0])).days or 252
    cagr= (1+total_ret)**(365/days)-1 if total_ret>-1 else -1
    return {"trades":trades,"metrics":{"total_return":total_ret,"num_trades":len(trades),"win_rate":win_rate,"avg_win":avg_win,"avg_loss":avg_loss,"profit_factor":profit_factor,"max_drawdown":max_dd,"volatility":vol,"cagr":cagr,"transaction_costs": len(trades)*2*config.brokerage_pct}}

def walk_forward(df: pd.DataFrame, config: BacktestConfig, train_days=252, test_days=63, step=63):
    df=df.sort_values("date").reset_index(drop=True)
    results=[]
    start= train_days
    while start+test_days <= len(df):
        train=df.iloc[start-train_days:start]
        test=df.iloc[start:start+test_days]
        # in-sample metrics (train) vs out-of-sample (test)
        train_res=backtest_symbol(train, config)
        test_res=backtest_symbol(test, config)
        results.append({"train_start":str(train["date"].iloc[0]),"train_end":str(train["date"].iloc[-1]),"test_start":str(test["date"].iloc[0]),"test_end":str(test["date"].iloc[-1]),"in_sample":train_res["metrics"],"out_of_sample":test_res["metrics"]})
        start+=step
    return results
