from .mock_provider import MockProvider
from .yfinance_provider import YFinanceProvider
from .nse_provider import NSEProvider
def get_provider(name="mock"):
    name=name.lower()
    if name=="yfinance" or name=="yahoo": return YFinanceProvider()
    if name=="nse": return NSEProvider()
    return MockProvider()
