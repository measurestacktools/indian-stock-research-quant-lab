from dataclasses import dataclass

@dataclass
class CostAssumptions:
    brokerage_pct: float=0.001  # 0.1%
    exchange_charges_pct: float=0.00005
    stamp_duty_pct: float=0.00015
    gst_on_brokerage: float=0.18
    slippage_pct: float=0.001

def calc_costs(price, qty, assumptions: CostAssumptions = None):
    if assumptions is None: assumptions=CostAssumptions()
    turnover = price*qty
    brokerage = turnover*assumptions.brokerage_pct
    exch = turnover*assumptions.exchange_charges_pct
    stamp = turnover*assumptions.stamp_duty_pct
    gst = brokerage*assumptions.gst_on_brokerage
    slippage = turnover*assumptions.slippage_pct
    total = brokerage+exch+stamp+gst+slippage
    return {"turnover":turnover,"brokerage":brokerage,"exchange":exch,"stamp":stamp,"gst":gst,"slippage":slippage,"total":total}

def net_return(gross_pnl, costs_buy, costs_sell):
    return gross_pnl - costs_buy - costs_sell
