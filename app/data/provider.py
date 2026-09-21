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

class DataProvider(ABC):
    @abstractmethod
    def get_universe(self) -> List[Company]: pass
    @abstractmethod
    def get_daily_prices(self, symbol: str, start: str, end: str) -> pd.DataFrame: pass
    def get_fundamentals(self, symbol: str) -> Optional[Dict]: return None
    def get_corporate_actions(self, symbol: str) -> List[Dict]: return []
    def health_check(self) -> bool: return True
    @property
    def name(self) -> str: return self.__class__.__name__
