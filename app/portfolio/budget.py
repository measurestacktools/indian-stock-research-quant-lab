from dataclasses import dataclass
from typing import Optional

@dataclass
class BudgetInput:
    total_capital: float
    max_per_position: Optional[float]=None
    min_shares: int =1
    max_shares: Optional[int]=None
    brokerage_pct: float=0.001
    slippage_pct: float=0.001
    min_cash_buffer: float=0

@dataclass
class Affordability:
    affordable: bool
    max_shares: int
    estimated_cost: float
    reason: str
    attractive: Optional[bool]=None

def assess_affordability(price: float, budget: BudgetInput, liquidity_ok=True) -> Affordability:
    if price<=0 or budget.total_capital<=0:
        return Affordability(False,0,0,"Invalid price/capital")
    costs_per_share = price * (budget.brokerage_pct + budget.slippage_pct)
    effective_price = price + costs_per_share
    max_cap = budget.max_per_position if budget.max_per_position else budget.total_capital - budget.min_cash_buffer
    max_shares = int(max_cap // effective_price)
    if budget.max_shares is not None: max_shares = min(max_shares, budget.max_shares)
    if max_shares < budget.min_shares:
        return Affordability(False, max_shares, max_shares*effective_price if max_shares>0 else 0, f"Need ₹{effective_price:.2f} per share incl. costs, capital ₹{budget.total_capital} insufficient for {budget.min_shares} share(s)")
    # affordability != attractiveness
    return Affordability(True, max_shares, max_shares*effective_price, f"Affordable: up to {max_shares} shares @ ₹{price:.2f} incl. costs {budget.brokerage_pct+budget.slippage_pct:.2%}", attractive=None)

def position_size(price, capital, risk_pct=0.02, stop_loss_pct=0.05):
    # simple risk-based sizing
    risk_amount = capital * risk_pct
    risk_per_share = price * stop_loss_pct
    if risk_per_share<=0: return 0
    return int(risk_amount // risk_per_share)
