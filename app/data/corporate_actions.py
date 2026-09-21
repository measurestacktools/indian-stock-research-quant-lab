"""
Corporate-action engine — splits, bonuses, cash dividends.

Adjustment semantics (chosen convention, documented):
----------------------------------------------------
* We use BACKWARD adjustment: historical prices before ex_date are scaled
  to be comparable to prices *on/after* ex_date.

  adjusted_price(t) = raw_price(t) * cumulative_price_adjustment_factor(t)

  where cumulative_price_adjustment_factor(t) = product of all
  price-adjusting actions (splits, bonuses) with ex_date > t
          AND  adjustment_factor(action) < 1 for price-reducing actions.

  Example 2:1 split, ex_date=2024-01-03:
    adjustment_factor = denominator / numerator = 1/2 = 0.5
    For any price with date < 2024-01-03: adjusted = raw * 0.5
    On ex_date and after: factor not applied (factor=1).
    So Day1 200 -> 100, Day2 200 -> 100, Day3 100 -> 100, Day4 105 ->105.
    No artificial -50% return.

* Volume adjustment is inverse: adjusted_volume = raw_volume / cumulative_factor
  (shares double, price half).

* Cash dividends are NOT price-adjusting: adjustment_factor =1.0.
  They are stored as explicit cash flows for total-return calculations.

* Bonus: same as split, ratio = total_shares_after / shares_before.
  e.g. 1:1 bonus (1 bonus per 1 held) => numerator=2, denominator=1 => factor 0.5.

* Reverse split 1:2 (1 new for 2 old): numerator=1, denominator=2 => factor 2.0
  Historical prices doubled.

* Multiple actions compound multiplicatively in reverse chronological order.

* Factors are applied to ex_date boundary: date < ex_date gets factor,
  date >= ex_date does not (for that action).

Idempotence: apply_adjustments always computes from raw_price, not incrementally.
"""
from dataclasses import dataclass
from typing import List, Optional, Dict
import pandas as pd
import hashlib
from datetime import datetime

VALID_TYPES = {"split", "bonus", "dividend", "cash_dividend"}

@dataclass
class CorporateAction:
    symbol: str
    action_type: str  # split, bonus, dividend/cash_dividend
    ex_date: str  # ISO date YYYY-MM-DD
    record_date: Optional[str] = None
    payment_date: Optional[str] = None
    ratio_numerator: Optional[float] = None  # new shares (for split/bonus)
    ratio_denominator: Optional[float] = None  # old shares
    cash_amount: Optional[float] = None  # for dividends
    currency: str = "INR"
    adjustment_factor: Optional[float] = None  # computed, price multiplier for prior prices
    source: str = "manual"
    retrieved_at: Optional[str] = None
    raw_hash: Optional[str] = None
    data_version: str = "v1"

def _hash_action(ca: CorporateAction) -> str:
    raw = f"{ca.symbol}|{ca.action_type}|{ca.ex_date}|{ca.ratio_numerator}|{ca.ratio_denominator}|{ca.cash_amount}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def compute_adjustment_factor(action_type: str, ratio_num, ratio_den) -> float:
    """Deterministic factor for price adjustment.

    For splits/bonuses: factor = denominator / numerator.
    For dividends: 1.0 (no price adjustment).
    Validates ratios."""
    if action_type in ("dividend", "cash_dividend"):
        return 1.0
    if action_type in ("split", "bonus"):
        if ratio_num is None or ratio_den is None:
            raise ValueError(f"Missing ratio for {action_type}: num={ratio_num} den={ratio_den}")
        if ratio_num <= 0 or ratio_den <= 0:
            raise ValueError(f"Invalid ratio for {action_type}: {ratio_num}/{ratio_den} must be >0")
        return float(ratio_den) / float(ratio_num)
    # extensible: other types default 1.0
    return 1.0

def validate_action(ca: CorporateAction):
    if not ca.symbol or not ca.action_type or not ca.ex_date:
        raise ValueError("Missing required fields symbol/action_type/ex_date")
    if ca.action_type not in VALID_TYPES:
        # allow extensible but warn: require factor computation
        pass
    # validate date parse
    try:
        pd.to_datetime(ca.ex_date)
    except Exception as e:
        raise ValueError(f"Invalid ex_date {ca.ex_date}: {e}")
    # ratios for splits/bonuses must be valid
    if ca.action_type in ("split", "bonus"):
        if ca.ratio_numerator is None or ca.ratio_denominator is None:
            raise ValueError(f"{ca.action_type} requires ratio_numerator/denominator")
        compute_adjustment_factor(ca.action_type, ca.ratio_numerator, ca.ratio_denominator)
    if ca.action_type in ("dividend", "cash_dividend"):
        if ca.cash_amount is None:
            raise ValueError("dividend requires cash_amount")
        if ca.cash_amount < 0:
            raise ValueError("cash_amount must be >=0")
    # compute factor if missing
    if ca.adjustment_factor is None:
        ca.adjustment_factor = compute_adjustment_factor(ca.action_type, ca.ratio_numerator, ca.ratio_denominator)
    if ca.raw_hash is None:
        ca.raw_hash = _hash_action(ca)
    if ca.retrieved_at is None:
        ca.retrieved_at = datetime.utcnow().isoformat()
    return ca

def normalize_actions(actions: List[CorporateAction]) -> List[CorporateAction]:
    """Validate, deduplicate deterministically, sort by ex_date."""
    validated = []
    for a in actions:
        # handle dict input
        if isinstance(a, dict):
            # map legacy dict keys
            if "date" in a and "ex_date" not in a:
                a["ex_date"] = a.pop("date")
            if "type" in a and "action_type" not in a:
                a["action_type"] = a.pop("type")
            if "ratio" in a and "ratio_numerator" not in a:
                # legacy ratio as float: treat as numerator/1
                try:
                    r = float(a.pop("ratio"))
                    a["ratio_numerator"] = r
                    a["ratio_denominator"] = 1
                except:
                    pass
            # dividend legacy
            if a.get("action_type") == "dividend" and "cash_amount" not in a and "amount" in a:
                a["cash_amount"] = a.pop("amount")
            a = CorporateAction(**{k: v for k, v in a.items() if k in CorporateAction.__dataclass_fields__})
        validated.append(validate_action(a))
    # deduplicate by (symbol, action_type, ex_date, ratio, cash_amount) -> keep first
    seen = {}
    deduped = []
    for a in validated:
        key = (a.symbol, a.action_type, a.ex_date, a.ratio_numerator, a.ratio_denominator, a.cash_amount)
        if key not in seen:
            seen[key] = a
            deduped.append(a)
        # else duplicate silently dropped (deterministic: first wins)
    deduped.sort(key=lambda x: x.ex_date)
    return deduped

def cumulative_factors_for_dates(dates: pd.Series, actions: List[CorporateAction]) -> pd.Series:
    """Return series of cumulative adjustment factor per date.

    For each date, factor = product of adjustment_factor for all actions
    where ex_date > date (i.e., action occurs after that price date).
    """
    actions = normalize_actions(actions)
    # ensure dates are datetime
    dates_dt = pd.to_datetime(dates)
    factors = pd.Series([1.0] * len(dates), index=dates.index, dtype=float)
    for act in actions:
        if act.adjustment_factor == 1.0:
            continue  # dividends never adjust price
        ex = pd.to_datetime(act.ex_date)
        mask = dates_dt < ex
        factors[mask] = factors[mask] * act.adjustment_factor
    return factors

def apply_adjustments(df: pd.DataFrame, actions: List[CorporateAction]) -> pd.DataFrame:
    """Apply backward price adjustments to OHLCV.

    Returns new DataFrame with:
      - raw columns preserved as raw_open etc? We keep original as raw_* and
        produce adjusted columns open/high/low/close and adjusted_volume.
      - For idempotence, always compute from raw if present; otherwise from current.
    Semantics documented in module docstring.
    """
    if df is None or df.empty:
        return df
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    # ensure raw columns exist for idempotence
    for col in ["open","high","low","close"]:
        raw_col = f"raw_{col}"
        if raw_col not in df.columns:
            df[raw_col] = df[col]
        # else keep existing raw
    if "raw_volume" not in df.columns and "volume" in df.columns:
        df["raw_volume"] = df["volume"]

    if not actions:
        # ensure adjusted equals raw
        for col in ["open","high","low","close"]:
            df[col] = df[f"raw_{col}"]
        if "volume" in df.columns:
            df["volume"] = df["raw_volume"]
        df["cumulative_adjustment_factor"] = 1.0
        return df

    factors = cumulative_factors_for_dates(df["date"], actions)
    df["cumulative_adjustment_factor"] = factors
    for col in ["open","high","low","close"]:
        df[col] = df[f"raw_{col}"] * factors
    # volume inverse
    if "volume" in df.columns:
        # avoid division by zero; factors never zero (ratios >0)
        df["volume"] = (df["raw_volume"] / factors).astype(int)
    # preserve dividend cash flows separately: add column dividend_cash if any dividend actions
    # not altering price; just annotate
    dividend_map = {}
    for act in normalize_actions(actions):
        if act.action_type in ("dividend","cash_dividend"):
            dividend_map.setdefault(act.ex_date, 0.0)
            dividend_map[act.ex_date] += float(act.cash_amount or 0)
    df["dividend_cash"] = df["date"].dt.strftime("%Y-%m-%d").map(dividend_map).fillna(0.0)
    return df

def total_return_series(df_adjusted: pd.DataFrame) -> pd.Series:
    """Compute total-return vs price-return if dividends present.

    For this phase, not automatically applied to price series; provided for
    backtester to optionally use.
    """
    # price return from adjusted close
    # total return would add dividend reinvested: not implemented fully, just placeholder
    return df_adjusted["close"].pct_change()
