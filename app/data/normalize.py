import pandas as pd
from typing import List, Optional

def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Basic OHLCV normalization: coerce types, sort, drop NaNs."""
    df=df.copy()
    df["date"]=pd.to_datetime(df["date"])
    df=df.sort_values("date")
    # ensure numeric
    for c in ["open","high","low","close","volume"]:
        if c in df.columns: df[c]=pd.to_numeric(df[c], errors="coerce")
    df=df.dropna(subset=["open","high","low","close"])
    return df

def normalize_prices_with_actions(df: pd.DataFrame, actions: Optional[List]=None, adjust: bool = True) -> pd.DataFrame:
    """
    Full normalization pipeline: normalize -> corporate-action adjustment.

    Adjustment semantics (from app.data.corporate_actions):
      adjusted_price(t) = raw_price(t) * cumulative_price_adjustment_factor(t)
      where cumulative factor = product of adjustment_factor for all splits/bonuses
      with ex_date > t. Dividends have factor 1.0 and are kept as separate cash flows.

    Forward vs backward: backward adjustment (historical scaled to current).
    Which date receives adjustment: date < ex_date gets factor, date >= ex_date does not.
    Multiple actions: multiplicative compounding in reverse chronological order.
    Split/bonus ratio: ratio_numerator = new_shares, ratio_denominator = old_shares,
      factor = denominator / numerator (e.g. 2:1 split => 0.5).
    Dividends: stored in dividend_cash column, not applied to OHLCV.

    Idempotence: calling twice yields same adjusted prices because raw_* preserved.
    """
    df = normalize_prices(df)
    if adjust and actions:
        from app.data.corporate_actions import apply_adjustments
        df = apply_adjustments(df, actions)
    else:
        # ensure factor column exists for downstream
        if "cumulative_adjustment_factor" not in df.columns:
            df["cumulative_adjustment_factor"] = 1.0
        if "dividend_cash" not in df.columns:
            df["dividend_cash"] = 0.0
        # preserve raw for idempotence check
        for col in ["open","high","low","close"]:
            raw_col = f"raw_{col}"
            if raw_col not in df.columns:
                df[raw_col] = df[col]
    return df
