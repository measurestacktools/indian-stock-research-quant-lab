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

## Browser-First Run
```bash
python run.py
# → Dashboard: http://localhost:8501
# → API: http://localhost:8000
# → Status: READY
```
Terminal shows only `Dashboard/API/Status`. All research via browser. `webbrowser` auto-opens. `python run.py` starts Streamlit + FastAPI together; `streamlit run app/ui/main.py` also works.

Navigation (11 pages): Market Overview, Stock Scanner, Quant Research, Fundamentals, Point-in-Time Data, Experiments, Backtests, Research Ledger, Paper Portfolio, Data Health, System. All show `Data as of:` + stale warning, `DATA MODE: MOCK/YFINANCE`, `NSE PROVIDER: NOT CONFIGURED` transparently. Errors show human-readable UI, not tracebacks.

## Corporate Actions (Phase 2)
`app/data/corporate_actions.py` — deterministic backward adjustment. **Semantics:** `adjusted_price(t) = raw_price(t) * cumulative_factor(t)` where cumulative factor = product of `adjustment_factor = denominator/numerator` for all splits/bonuses with `ex_date > t`. Dividends have factor 1.0 and are stored separately as `dividend_cash` cash flows (not subtracted from OHLCV), enabling price/ total/ dividend-reinvested return choices. Volume adjusted inversely (`raw_volume / factor`). Multiple actions compound multiplicatively; `date < ex_date` gets factor, `date >= ex_date` does not. Idempotent via `raw_*` preservation. Provenance: `source, retrieved_at, raw_hash, data_version` per action. See `app/data/normalize.py:12` and UI Data Health → Corporate Actions (inspectable raw vs adjusted).

**Worked example:** 2:1 split `ex_date=2024-01-03` → factor 0.5. Raw 200,200,100,105 → adjusted 100,100,100,105 — no -50% fake return.

## Point-in-Time Fundamentals (Phase 2)
`fundamentals` PK changed to `(symbol, period, available_at)` — `period` ≠ `available_at`. Backtest uses `available_at <= as_of` (never `period <= as_of`). Example: `period 2025-03-31, available 2025-05-20` → `as_of 2025-04-01` unavailable, `2025-06-01` available. Revision history preserved (Aug 10 restatement coexists with May 20). Query via `app/data/fundamentals.py:get_fundamentals_as_of(symbol, as_of)`; view `fundamentals_pit` documents semantics. Backtester `app/backtesting/engine.py:13` optionally gates signals via PIT (`use_pit_fundamentals=True`). Dashboard Page 5 visualizes `period → available_at → revision` timeline. Provenance: `source, retrieved_at, hash, data_version, transform_hash`. Migration in `app/database/db.py:33` preserves legacy data.

## Dashboard (Streamlit)
Pages: Market Overview, Stock Scanner, Quant Research, Fundamentals, Point-in-Time Data, Experiments, Backtests, Research Ledger, Paper Portfolio, Data Health, System — all show "Data as of: [timestamp]" and stale warning.

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
