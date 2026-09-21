from abc import ABC, abstractmethod
import pandas as pd
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class Company:
    symbol: str
    name: str
    exchange: str = "NSE"
    isin: str = ""
    sector: str = ""
    industry: str = ""
    security_type: str = "EQ"
    status: str = "active"
    # survivorship fields
    security_id: str = ""  # stable id, defaults to symbol if not provided
    company_id: str = ""
    listed_date: Optional[str] = None  # ISO YYYY-MM-DD, inclusive
    delisted_date: Optional[str] = None  # ISO, exclusive — not eligible on delisted_date
    source: str = "manual"
    retrieved_at: Optional[str] = None
    data_version: str = "v1"

    def __post_init__(self):
        if not self.security_id:
            self.security_id = self.symbol
        if not self.company_id:
            self.company_id = self.symbol

class DataProvider(ABC):
    @abstractmethod
    def get_universe(self, as_of: Optional[str] = None) -> List[Company]:
        """Return universe eligible at as_of (ISO date). If as_of None, current universe.
        Must obey listed_date <= as_of and (delisted_date is None or delisted_date > as_of).""" 
        pass
    @abstractmethod
    def get_daily_prices(self, symbol: str, start: str, end: str) -> pd.DataFrame: pass
    def get_fundamentals(self, symbol: str) -> Optional[Dict]: return None
    def get_corporate_actions(self, symbol: str) -> List[Dict]: return []
    def health_check(self) -> bool: return True
    @property
    def name(self) -> str: return self.__class__.__name__
