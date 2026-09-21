# Indian Stock Research & Quant Lab

Local-first Indian stock research, screening, backtesting, AI-analysis, paper-portfolio platform. Small-budget aware (₹150), no guaranteed profits, no real-money trading.

> Research candidate — not an automatic trade instruction.

## Architecture
```
Market Universe → Data Ingestion → Normalization → Quality Checks → Feature Engine → Quant Screening → Fundamental Screening → Candidate Ranking → Groq Analyst → Devil's Advocate → Contradiction Check → Deterministic Rule Engine → Backtest Engine → Paper Portfolio → Performance Analytics → Research Report
```
- **LLM never final decision maker** — Python handles all math, rules, backtests.
- Groq interprets verified data only, says "Data unavailable" when missing, banned phrases blocked.

## Tech Stack
- Python 3.12+, FastAPI, Pandas, NumPy, Pydantic, SQLite, PyArrow/Parquet, httpx, yfinance, groq, streamlit, plotly, pytest

## Quickstart (clean machine)
```bash
git clone <repo> && cd stock-lab
pip install -r requirements.txt
cp .env.example .env   # add GROQ_API_KEY=...
python -m app.data.ingest --mock --start 2023-01-01
python -m app.screening.run --budget 150
python -m app.backtesting.run --symbol PENNY --provider mock
pytest -q
streamlit run app/ui/main.py
# or
python run.py
# API
uvicorn app.api.main:app --reload
```

## Project Structure
```
stock-lab/
├── app/
│   ├── api/  ui/  data/  database/  features/  screening/  ai/  backtesting/  portfolio/  analytics/  config/  utils/
├── data/raw/ processed/ cache/
├── tests/  scripts/  docs/  .env.example  requirements.txt  run.py
```

## Data Providers (abstraction)
`DataProvider` → `MockProvider` (offline synthetic), `YFinanceProvider` (Yahoo .NS), `NSEProvider` (stub). Add new provider by implementing `get_universe`, `get_daily_prices`, `get_fundamentals`, `get_corporate_actions`.

- Raw data immutable in `data/raw/<provider>/<symbol>/*.parquet` with source, retrieved_at, hash.
- `yfinance` free, ~15min delay, 10y history; rate-limited — cache + exponential backoff, show "Data unavailable" on failure.

## Key Modules
- **Budget Engine** `app/portfolio/budget.py`: `assess_affordability` distinguishes *Affordable* vs *Potentially attractive*, includes brokerage/slippage/liquidity.
- **Feature Engine** `app/features/engine.py`: returns, MAs, vol, ATR, drawdown, 52w distance; nulls on missing inputs.
- **Regime** `app/features/regime.py`: bullish/bearish/sideways + vol, with metrics stored.
- **Screening** `app/screening/filters.py`: 4 stages (eligibility → affordability → quant → fundamental), configurable thresholds, transparent percentiles (no magic 87/100).
- **Rule Engine** `app/screening/rules.py`: PASSED/FAILED/UNKNOWN per rule with explanation.
- **AI** `app/ai/groq_client.py`: Analyst + Devil's Advocate, strict Pydantic JSON, cache 7d, never bulk-calls, banned phrase filter.
- **Backtest** `app/backtesting/engine.py`: vectorized, no look-ahead (only data ≤T), costs/slippage, walk-forward in/out-of-sample labeling, benchmark buy-hold.
- **Portfolio** `app/portfolio/portfolio.py`: paper trades, cash tracking, P&L, snapshots — example ₹150 buy 1×₹120 → cash ₹30, unrealized calc.

## Dashboard (Streamlit)
Pages: Overview, Market Scanner, Stock Detail, AI Research, Backtesting Lab, Paper Portfolio, Performance, Data Health, Settings — all show "Data as of: [timestamp]" and stale warning.

## Configuration (.env)
```
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile
DATABASE_URL=sqlite:///data/stock_lab.db
```
Never commit `.env`.

## Testing
```bash
pytest tests/test_all.py -v
```
Covers OHLC, returns, MAs, vol, drawdown, sizing, affordability, costs, P&L, rules, no-lookahead synthetic, dates, corporate actions, malformed AI JSON, missing data, API failure, caching, DB writes, walk-forward.

## Acceptance Criteria (23)
All verified: starts locally, universe loads, prices load, validation works, ₹150 affordable filter, features correct, missing data safe, Groq via .env + schema + critic, rule explanations, backtester + LO tests + walk-forward, paper P&L, dashboard, API failures not crash, no secrets, tests pass, README complete, e2e demo.

## Disclaimer
Not financial advice. No profit guarantee. Paper trading only.

## Docs
See `docs/plan.md` for data-source research, DB schema, risks, phased plan.
