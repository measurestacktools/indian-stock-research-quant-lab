# Survivorship-Bias Protection — Implementation Plan

## 1. Model
- Extend `companies` and `securities` with `listed_date`, `delisted_date`, `security_id`, `company_id`, `source`, `retrieved_at`, `data_version`.
- Keep `symbol` as current ticker for backward compat; add `security_symbols` table for history (security_id stable).
- Inclusive/exclusive: `listed_date` inclusive (eligible on listed_date), `delisted_date` exclusive (not eligible on delisted_date and after). Documented consistently.
- Migration via ALTER TABLE ADD COLUMN if not exists (idempotent, preserves data).

## 2. Historical Universe
- `app/data/universe.py`: `get_universe(as_of: str|None, db_path=None, provider=None, definition="nse_equities") -> List[Company]`
  - If `as_of is None`: current universe (all active).
  - Else: `WHERE (listed_date IS NULL OR listed_date <= as_of) AND (delisted_date IS NULL OR delisted_date > as_of)` plus status='active' filter.
  - Provider fallback if DB empty.
- Reusable interface, not hard-coded in backtester.

## 3. Snapshots
- Table `universe_snapshots(snapshot_id TEXT PK, as_of TEXT, universe_definition TEXT, security_id TEXT, symbol TEXT, exchange TEXT, listed_date TEXT, delisted_date TEXT, source TEXT, created_at TEXT, data_version TEXT, hash TEXT)`
- Deterministic: hash = sha256(universe_definition|as_of|sorted(symbols)|data_version)
- Functions: `create_snapshot(as_of, definition)`, `get_snapshot(as_of)`, `list_snapshots()`

## 4. Backtest Integration
- `app/backtesting/engine.py`: add `backtest_universe(symbols, start, end, config, universe_callback)` and modify `walk_forward` to use historical universe per date.
- For single-symbol backtest, no change; for universe screening/backtest, use `get_universe(as_of=T)` per bar.

## 5. Symbol Changes
- Table `security_symbols(security_id, symbol, start_date, end_date, source)`
- Abstraction ready; document that YFinance/Mock currently lack history, so mappings must be supplied manually.

## 6. Corporate Actions
- No conflict; corporate actions already use ex_date; survivorship uses listed/delisted.

## 7. UI
- Data Health shows universe snapshot counts, listed/delisted counts.
- PIT page shows universe availability.

## 8. Tests
- listed/delisted inclusive/exclusive, snapshot determinism, look-ahead prevention, integration.
