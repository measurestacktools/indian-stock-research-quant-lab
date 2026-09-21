# Indian Stock Research & Quant Lab — Plan

## Data Sources Investigated
| Source | Fields | Limits | Freshness | Historical | Reliability | License |
|--------|--------|--------|-----------|------------|-------------|---------|
| **yfinance (Yahoo Finance)** | OHLCV, divis/splits, fundamentals (limited), 52w | ~2000 req/hr, no key, .NS suffix for NSE | 15min delay, EOD reliable | 10+ years | Medium-high, unofficial but stable | MIT wrapper, Yahoo ToS |
| **NSE India API (nseindia.com/api)** | OHLCV, universe, corp actions | Requires cookies + headers, IP throttled, brittle | Near RT | Limited | Low, breaks without warning | Use sparingly, respect robots |
| **MockProvider** | Synthetic OHLCV + fundamentals | None | Instant | Configurable | 100% for tests | Internal |

**Decision:** Abstraction `DataProvider` with MockProvider default for offline/tests, YFinanceProvider for real ingestion, NSEProvider stub for future. Never tight-couple.

**Fields unavailable free/reliably:** detailed cashflow, EV/EBITDA consistently, news sentiment. Mark as `null/unknown`.

## DB Schema (SQLite)
- companies(id PK, symbol UNIQUE, name, exchange, isin, sector, industry, security_type, status)
- securities(id PK, company_id FK, symbol, exchange, type, status)
- prices_daily(id PK, symbol, date, open, high, low, close, volume, source, retrieved_at, hash, UNIQUE(symbol,date))
- fundamentals(symbol, date, revenue, profit, eps, roe, roce, debt_equity, pe, pb, market_cap, source, retrieved_at)
- corporate_actions(id PK, symbol, date, type, ratio, source)
- news_items(id PK, symbol, date, title, source, url, retrieved_at)
- features_daily(symbol, date, returns, ma_20, ma_50, vol_20, atr_14, drawdown, rsi_hint, etc.)
- screening_runs(id PK, timestamp, config_json, dataset_version, universe_count)
- screening_results(run_id FK, symbol, stage, passed, reason_json)
- ai_analyses(id PK, symbol, date, model, prompt_version, input_hash, output_json, created_at)
- ai_critiques(id PK, analysis_id FK, output_json, created_at)
- backtests(id PK, strategy, start, end, config_json, metrics_json, created_at)
- paper_portfolios(id PK, name, initial_capital, created_at)
- paper_positions(portfolio_id FK, symbol, qty, avg_price)
- paper_trades(id PK, portfolio_id FK, symbol, side, qty, price, costs, timestamp)
- performance_snapshots(id PK, portfolio_id FK, date, value, cash, pnl)
- system_events(id PK, timestamp, level, message, context_json)

Indexes on (symbol,date), (date), screening_results run_id.

Raw parquet: data/raw/<source>/<symbol>/<date>.parquet immutable.
Processed: data/processed/
Cache: data/cache/ (httpx, ai)

## Provider Interface
```python
class DataProvider(ABC):
    def get_universe(self)->List[Company]
    def get_daily_prices(self, symbol, start, end)->pd.DataFrame
    def get_fundamentals(self, symbol)->dict|None
    def get_corporate_actions(self, symbol)->List[dict]
    def health_check(self)->bool
```

## Risks
- yfinance throttling → cache + exponential backoff + Mock fallback, show "Data unavailable"
- Groq rate limit → never bulk call, cache, TTL 7d
- Corporate actions incomplete → flag quality, don't silently adjust
- SQLite concurrency → WAL mode, single writer
- Lookahead bias → strictly T-only data in backtest; tests with synthetic predictable series

## Phases
1 Skeleton ✓ 2 Data 3 Features 4 Fundamentals 5 AI 6 Rules 7 Backtest 8 Portfolio 9 UI 10 Tests
