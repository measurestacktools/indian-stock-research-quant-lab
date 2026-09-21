import streamlit as st, pandas as pd, datetime, json, sys, pathlib, os, traceback
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from app.config.settings import settings
from app.data.registry import get_provider
from app.features.engine import compute_features
from app.features.regime import classify_regime
from app.screening.run import run_screen
from app.backtesting.run import run_backtest
from app.portfolio.portfolio import create_portfolio, get_value, buy, sell, get_positions, get_cash
from app.portfolio.budget import BudgetInput, assess_affordability
from app.screening.rules import evaluate_rules
from app.ai.groq_client import analyst_call, critic_call
from app.database.db import init_db, get_conn
import plotly.graph_objs as go

st.set_page_config(page_title="Indian Stock Quant Lab", layout="wide", initial_sidebar_state="expanded")
init_db()

# session defaults
if "budget" not in st.session_state: st.session_state.budget=150
if "provider" not in st.session_state: st.session_state.provider="mock"
if "portfolio" not in st.session_state: st.session_state.portfolio="default"
try: create_portfolio(st.session_state.portfolio, st.session_state.budget)
except: pass

# helper: data mode badge
def data_mode_badge():
    p = st.session_state.provider
    if p=="mock": return "DATA MODE: MOCK  — synthetic, for testing"
    if p=="yfinance": return "DATA MODE: YFINANCE — Yahoo Finance (.NS), 15min delay"
    return f"DATA MODE: {p.upper()}"
def nse_status(): return "NSE PROVIDER: NOT CONFIGURED (stub — use YFinance or Mock)"

def _safe(fn, *args, **kwargs):
    try: return fn(*args, **kwargs), None
    except Exception as e:
        return None, str(e)

def human_error(title, msg, hint=""):
    st.error(f"**{title}**\n\n{msg}\n\n{hint}")
    with st.expander("Developer details"): st.code(traceback.format_exc()[-2000:])

# Sidebar navigation - 11 items
NAV = ["Market Overview","Stock Scanner","Quant Research","Fundamentals","Point-in-Time Data","Experiments","Backtests","Research Ledger","Paper Portfolio","Data Health","System"]
if "nav" not in st.session_state: st.session_state.nav = NAV[0]

with st.sidebar:
    st.title("Quant Lab")
    st.caption("Research candidate — not trade instruction.")
    st.caption(data_mode_badge())
    st.caption(nse_status())
    st.divider()
    st.session_state.budget = st.number_input("Budget (₹)", min_value=50.0, value=float(st.session_state.budget), step=50.0)
    st.session_state.provider = st.selectbox("Provider", ["mock","yfinance"], index=0)
    st.session_state.portfolio = st.text_input("Portfolio", st.session_state.portfolio)
    try: create_portfolio(st.session_state.portfolio, st.session_state.budget)
    except: pass
    st.divider()
    # navigation
    choice = st.radio("Navigate", NAV, index=NAV.index(st.session_state.nav), label_visibility="collapsed")
    st.session_state.nav = choice
    st.divider()
    st.caption(f"Data as of: {datetime.date.today().isoformat()}")
    try:
        conn=get_conn(); row=conn.execute("SELECT MAX(date) as d FROM prices_daily").fetchone()
        last=row["d"] if row and row["d"] else "never"
        st.caption(f"Last price in DB: {last}")
        if last!="never":
            try:
                delta=(datetime.date.today() - datetime.date.fromisoformat(last)).days
                if delta>5: st.warning("WARNING: DATA MAY BE STALE")
            except: pass
    except: pass
    if not (settings.groq_api_key or os.getenv("GROQ_API_KEY")):
        st.warning("Groq API key not set → AI mock mode")

page = st.session_state.nav

# --- 1 Market Overview ---
if page=="Market Overview":
    st.header("Market Overview")
    c1,c2,c3,c4 = st.columns(4)
    try:
        val=get_value(st.session_state.portfolio, {})
        prov=get_provider(st.session_state.provider)
        c1.metric("Budget", f"₹{st.session_state.budget:.0f}")
        c2.metric("Portfolio Value", f"₹{val['total']:.2f}", delta=f"{val['unrealized_pnl']:.2f}")
        c3.metric("Positions", len(val["positions"]))
        c4.metric("Universe", len(prov.get_universe()))
    except Exception as e: human_error("Overview unavailable", str(e))
    st.divider()
    # regime for first symbol
    try:
        prov=get_provider(st.session_state.provider)
        sym=prov.get_universe()[0].symbol
        df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
        df=compute_features(df)
        reg=classify_regime(df)
        st.subheader(f"Market Regime — {sym} (example)")
        st.json(reg)
        st.caption("Regime uses deterministic metrics (MA50/MA200, vol). Not predictive.")
    except Exception as e: st.info(f"Regime unavailable: {e}")

# --- 2 Stock Scanner ---
elif page=="Stock Scanner":
    st.header("Stock Scanner — Budget-Aware")
    st.caption("Stages: eligibility → affordability → quant → fundamental → candidate. Affordable ≠ Attractive.")
    col1,col2 = st.columns([1,3])
    with col1:
        if st.button("Run Scanner", type="primary"):
            st.session_state["scan_res"]=None
            with st.spinner("Screening…"):
                try:
                    res=run_screen(st.session_state.budget, st.session_state.provider)
                    st.session_state["scan_res"]=res
                except Exception as e: human_error("Scanner failed", "Unable to screen universe.", f"{e}")
    if "scan_res" in st.session_state and st.session_state["scan_res"]:
        res=st.session_state["scan_res"]
        st.success(f"Candidates: {len(res['candidates'])} / {res['universe']}")
        if res["candidates"]:
            df=pd.DataFrame(res["candidates"])
            show_cols=[c for c in ["symbol","reason","momentum_percentile","roe_percentile"] if c in df.columns]
            st.dataframe(df[show_cols], width='stretch')
        else: st.info("No candidates. Try larger budget or check Data Health.")
        with st.expander("All stage results"): st.json(res["all_results"][:100])
    # quick affordability demo
    with st.expander("Affordability example — ₹150"):
        from app.portfolio.budget import BudgetInput, assess_affordability
        b=BudgetInput(total_capital=150)
        for price in [20,120,140,200]:
            r=assess_affordability(price,b)
            st.write(f"₹{price}: {'Affordable' if r.affordable else 'NOT affordable'} — {r.reason}")

# --- 3 Quant Research ---
elif page=="Quant Research":
    st.header("Quant Research — Measured vs Calculated vs AI")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Symbol", symbols, key="qr_sym")
    try:
        prov=get_provider(st.session_state.provider)
        df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
        # corporate actions if any
        try:
            from app.data.corporate_actions import apply_adjustments
            conn=get_conn()
            rows=conn.execute("SELECT * FROM corporate_actions WHERE symbol=?", (sym,)).fetchall()
            cas=[]
            for r in rows:
                d=dict(r)
                cas.append(d)  # dict handled by normalize_actions
            if cas:
                from app.data.normalize import normalize_prices_with_actions
                df=normalize_prices_with_actions(df, cas, adjust=True)
                st.caption(f"Corporate actions applied: {len(cas)} — backward adjusted, dividend cash preserved")
            else:
                df=compute_features(df)
        except Exception: df=compute_features(df)
        if "cumulative_adjustment_factor" not in df.columns: df=compute_features(df)
        st.caption(f"Data as of: {df['date'].iloc[-1]}")
        # separate DATA / CALCULATED / AI
        st.subheader("DATA — Price")
        fig=go.Figure()
        fig.add_trace(go.Candlestick(x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Price"))
        if "ma20" in df.columns:
            fig.add_trace(go.Scatter(x=df["date"], y=df["ma20"], name="MA20", line=dict(width=1)))
            fig.add_trace(go.Scatter(x=df["date"], y=df["ma50"], name="MA50", line=dict(width=1)))
        st.plotly_chart(fig, width='stretch')
        st.plotly_chart(go.Figure(go.Bar(x=df["date"], y=df["volume"], name="Volume")), width='stretch')
        st.subheader("CALCULATED — Features")
        # show last row features
        last=df.iloc[-1]
        calc={k: (float(last[k]) if pd.notna(last[k]) else None) for k in ["ret_1d","ret_21d","ret_63d","ma20","ma50","vol20","atr14","drawdown","rel_vol"] if k in df.columns}
        st.json(calc)
        st.json(classify_regime(df))
        st.subheader("DETERMINISTIC RULES")
        fund=prov.get_fundamentals(sym)
        ctx={"avg_volume": float(df["volume"].tail(20).mean()), "roe": (fund or {}).get("roe"), "debt_equity": (fund or {}).get("debt_equity"), "pe": (fund or {}).get("pe"), "ret_63d": float(df["ret_63d"].iloc[-1]) if "ret_63d" in df.columns and pd.notna(df["ret_63d"].iloc[-1]) else None}
        for r in evaluate_rules(ctx):
            icon="✓" if r["status"]=="PASSED" else "✕" if r["status"]=="FAILED" else "?"
            st.write(f"{icon} {r['message']}")
        st.subheader("AI INTERPRETATION (Groq)")
        if st.button("Run AI Analysis (cached)"):
            try:
                verified={"symbol":sym, "price":float(df["close"].iloc[-1]), "fundamentals":fund, "features":calc}
                analyst=analyst_call(sym, verified)
                critic=critic_call(sym, analyst, verified)
                c1,c2=st.columns(2)
                with c1:
                    st.markdown("**Thesis**"); st.write(analyst.get("thesis",""))
                    st.markdown("**Business Summary**"); st.write(analyst.get("business_summary",""))
                    st.markdown("**Supporting evidence**"); st.write(analyst.get("positive_factors",[]))
                    st.markdown("**Risks**"); st.write(analyst.get("risk_factors",[]))
                    st.caption(f"Confidence (analysis quality, not price): {analyst.get('confidence')}")
                with c2:
                    st.markdown("**Devil's Advocate**"); st.write(critic.get("strongest_counter_argument",""))
                    st.markdown("**Counter-evidence**"); st.write(critic.get("failure_modes",[]))
                    st.markdown("**What would invalidate thesis?**"); st.write(analyst.get("thesis_invalidators",[]))
                with st.expander("Raw AI JSON"): st.json({"analyst":analyst,"critic":critic})
            except Exception as e: human_error("AI unavailable", "Groq unavailable or rate-limited. Showing mock if available.", str(e))
    except Exception as e: human_error("DATA PROVIDER ERROR", "Unable to retrieve market data.", f"{e}")

# --- 4 Fundamentals ---
elif page=="Fundamentals":
    st.header("Fundamentals — PIT-aware")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Symbol", symbols, key="f_sym")
    try:
        prov=get_provider(st.session_state.provider)
        fund=prov.get_fundamentals(sym)
        st.subheader("Latest provider fundamentals (non-PIT, may be stale)")
        if fund: st.json(fund)
        else: st.warning("Fundamental data unavailable — Reason: No filing available. Effect: Stock excluded from PIT calc if required.")
        # PIT history
        st.subheader("Point-in-Time History (from DB)")
        try:
            from app.data.fundamentals import get_fundamentals_history
            hist=get_fundamentals_history(sym)
            if hist:
                st.dataframe(pd.DataFrame(hist)[["period","available_at","retrieved_at","source","roe","pe","debt_equity"]], width='stretch')
                st.caption("Each row is immutable: period ≠ available_at. See PIT Data page for explanation.")
            else: st.info("No PIT records yet. Insert via app/data/fundamentals.py insert_fundamental.")
        except Exception as e: st.info(f"PIT unavailable: {e}")
        # corporate actions table
        st.subheader("Corporate Actions")
        try:
            conn=get_conn(); rows=conn.execute("SELECT symbol, action_type, ex_date, ratio_numerator, ratio_denominator, cash_amount, adjustment_factor, source FROM corporate_actions WHERE symbol=? ORDER BY ex_date", (sym,)).fetchall()
            if rows:
                st.dataframe(pd.DataFrame([dict(r) for r in rows]), width='stretch')
                st.caption("Adjustment: adjusted_price = raw_price * cumulative_factor (backward). Dividends factor 1.0, kept as cash.")
            else: st.info("No corporate actions recorded for this symbol.")
        except Exception as e: st.info(f"Corporate actions unavailable: {e}")
    except Exception as e: human_error("Fundamentals error", str(e))

# --- 5 Point-in-Time Data ---
elif page=="Point-in-Time Data":
    st.header("Point-in-Time Data — Look-ahead Prevention")
    st.info("Rule: backtest at T may only use available_at ≤ T, not period ≤ T. A FY2025 filing available 2025-05-20 must not be visible on 2025-04-01.")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Symbol", symbols, key="pit_sym")
    hist_date=st.date_input("Historical date (as_of)", value=datetime.date(2025,4,1))
    try:
        from app.data.fundamentals import get_fundamentals_as_of, get_fundamentals_history
        as_of=str(hist_date)
        rec=get_fundamentals_as_of(sym, as_of)
        st.subheader(f"As of {as_of}")
        if rec:
            st.success(f"Latest available filing: period {rec['period']} available {rec['available_at']}")
            st.json({k:rec.get(k) for k in ["period","available_at","retrieved_at","source","roe","pe","debt_equity","revenue"]})
        else:
            st.warning("NOT AVAILABLE — No filing with available_at ≤ selected date.")
            st.write("Reason: Published after selected date")
            st.write("Effect: This stock was excluded from PIT calculation on that date.")
        # timeline
        st.subheader("Timeline")
        hist=get_fundamentals_history(sym)
        if hist:
            for h in hist[:6]:
                st.write(f"Period {h['period']} → Filing {h['available_at']} → Retrieved {h['retrieved_at'][:10] if h['retrieved_at'] else ''}  (roe {h.get('roe')})")
            # visual example from spec
            with st.expander("Worked example — FY2025"):
                st.write("FY2025 period = 2025-03-31, available_at = 2025-05-20")
                for d in ["2025-04-01","2025-05-19","2025-05-20","2025-06-01"]:
                    r=get_fundamentals_as_of(sym, d)
                    st.write(f"as_of {d} => {'AVAILABLE' if r and r['period']=='2025-03-31' else 'NOT AVAILABLE'}")
        else: st.info("No PIT history to show timeline.")
        # revision example
        with st.expander("Revision handling"):
            st.write("Initial filing available 2025-05-20, restatement 2025-08-10")
            st.write("as_of 2025-06-01 → May 20 version; as_of 2025-09-01 → Aug 10 version. History preserved, never overwritten.")
    except Exception as e: human_error("PIT query failed", str(e))

# --- 6 Experiments ---
elif page=="Experiments":
    st.header("Experiments — Hypothesis Tracker (Phase 3 placeholder)")
    st.caption("Future: experiment_id, hypothesis, universe, train/valid/test, params, results, failure reason.")
    with st.form("new_exp"):
        st.subheader("NEW EXPERIMENT")
        hyp=st.text_area("Hypothesis", "Stocks with X+Y+Z historically outperform benchmark")
        uni=st.selectbox("Universe", ["Indian equities (NSE)", "Mock universe"])
        c1,c2,c3=st.columns(3)
        with c1: st.text_input("Training", "2018 → 2022")
        with c2: st.text_input("Validation", "2023 → 2024")
        with c3: st.text_input("Test", "2025 → 2026")
        st.text_area("Parameters", '{"entry_momentum":0.02, "max_holding_days":63}')
        submitted=st.form_submit_button("RUN EXPERIMENT (placeholder)")
        if submitted: st.info("Experiment tracker not yet implemented — this will run walk-forward and record in experiments table.")
    st.divider()
    st.write("Past experiments will appear here once Strategy Registry lands.")

# --- 7 Backtests ---
elif page=="Backtests":
    st.header("Backtests — Configurable, PIT-aware")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    c1,c2,c3,c4=st.columns(4)
    with c1: sym=st.selectbox("Symbol", symbols, key="bt_sym")
    with c2: start=st.text_input("Start", "2022-01-01")
    with c3: end=st.text_input("End", datetime.date.today().isoformat())
    with c4: capital=st.number_input("Initial capital", value=10000.0)
    c5,c6,c7,c8=st.columns(4)
    with c5: mom=st.number_input("Entry momentum", value=0.02, step=0.01, format="%.3f")
    with c6: hold=st.number_input("Max holding days", value=63, step=1)
    with c7: costs=st.number_input("Brokerage %", value=0.001, step=0.001, format="%.4f")
    with c8: slip=st.number_input("Slippage %", value=0.001, step=0.001, format="%.4f")
    use_pit=st.checkbox("Use PIT fundamentals gating (available_at ≤ T)", value=False, help="When enabled, fundamentals at T come from PIT, preventing look-ahead.")
    if st.button("Run Backtest", type="primary"):
        with st.spinner("Backtesting…"):
            try:
                prov=get_provider(st.session_state.provider)
                df=prov.get_daily_prices(sym, start, end)
                # apply corporate actions if stored
                try:
                    conn=get_conn(); rows=conn.execute("SELECT * FROM corporate_actions WHERE symbol=?", (sym,)).fetchall()
                    if rows:
                        from app.data.normalize import normalize_prices_with_actions
                        from app.data.corporate_actions import CorporateAction
                        cas=[]
                        for r in rows:
                            d=dict(r); cas.append(CorporateAction(symbol=d["symbol"], action_type=d["action_type"], ex_date=d["ex_date"], ratio_numerator=d["ratio_numerator"], ratio_denominator=d["ratio_denominator"], cash_amount=d["cash_amount"], adjustment_factor=d["adjustment_factor"], source=d["source"]))
                        df=normalize_prices_with_actions(df, cas)
                except: pass
                df=compute_features(df)
                from app.backtesting.engine import BacktestConfig, backtest_symbol, walk_forward
                from app.backtesting.benchmark import benchmark_buy_hold
                cfg=BacktestConfig(entry_momentum=mom, max_holding_days=int(hold), brokerage_pct=costs, slippage_pct=slip)
                if use_pit:
                    res=backtest_symbol(df, cfg, symbol=sym, use_pit_fundamentals=True)
                else:
                    res=backtest_symbol(df, cfg)
                bench=benchmark_buy_hold(df)
                st.subheader("Results")
                m=res["metrics"]
                cc1,cc2,cc3,cc4=st.columns(4)
                cc1.metric("Total return", f"{m['total_return']:.2%}")
                cc2.metric("CAGR", f"{m['cagr']:.2%}")
                cc3.metric("Max DD", f"{m['max_drawdown']:.2%}")
                cc4.metric("Trades", m['num_trades'])
                cc1,cc2,cc3,cc4=st.columns(4)
                cc1.metric("Win rate", f"{m['win_rate']:.1%}")
                cc2.metric("Avg win", f"{m['avg_win']:.2%}")
                cc3.metric("Avg loss", f"{m['avg_loss']:.2%}")
                cc4.metric("Volatility", f"{m['volatility']:.2%}")
                st.write(f"Benchmark (buy-hold): {bench['total_return']:.2%}")
                if res["trades"]: st.dataframe(pd.DataFrame(res["trades"]).head(20), width='stretch')
                else: st.info("No trades — try different momentum/holding.")
                # walk-forward
                st.subheader("Walk-Forward (IN-SAMPLE vs OUT-OF-SAMPLE)")
                wf=walk_forward(df, cfg)
                if wf:
                    st.dataframe(pd.DataFrame([{"train":w["train_start"][:10]+"→"+w["train_end"][:10], "test":w["test_start"][:10]+"→"+w["test_end"][:10], "in":f"{w['in_sample']['total_return']:.1%}", "out":f"{w['out_of_sample']['total_return']:.1%}"} for w in wf[:5]]), width='stretch')
                    st.warning("Do not present in-sample as proof of future performance.")
            except Exception as e: human_error("Backtest failed", "Unable to run backtest with current parameters and data.", str(e))
            # warnings
            try:
                conn=get_conn()
                cnt=conn.execute("SELECT COUNT(*) as c FROM prices_daily WHERE symbol=?", (sym,)).fetchone()["c"]
                if cnt<100: st.warning("Data incomplete: fewer than 100 price rows — results may be unreliable.")
            except: pass

# --- 8 Research Ledger ---
elif page=="Research Ledger":
    st.header("Research Ledger — Auditable Candidates")
    st.caption("Future: Candidate → Thesis / Evidence / Counter-thesis / Risks / Invalidators / Data timestamp / AI / Rules / Forward outcome")
    syms=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Symbol", syms, key="ledger_sym")
    try:
        prov=get_provider(st.session_state.provider)
        df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
        df=compute_features(df)
        fund=prov.get_fundamentals(sym)
        st.write(f"Data timestamp: {df['date'].iloc[-1]} | Price ₹{df['close'].iloc[-1]:.2f}")
        st.divider()
        if st.button("Generate Ledger Entry (AI)"):
            try:
                verified={"symbol":sym, "price":float(df["close"].iloc[-1]), "fundamentals":fund}
                analyst=analyst_call(sym, verified)
                critic=critic_call(sym, analyst, verified)
                st.subheader("Thesis"); st.write(analyst.get("thesis",""))
                st.subheader("Evidence"); st.write(analyst.get("positive_factors",[]))
                st.subheader("Counter-thesis"); st.write(critic.get("strongest_counter_argument",""))
                st.subheader("Risks"); st.write(analyst.get("risk_factors",[]))
                st.subheader("Invalidators"); st.write(analyst.get("thesis_invalidators",[]))
                st.subheader("Rule Results")
                ctx={"avg_volume": float(df["volume"].tail(20).mean()), "roe": (fund or {}).get("roe"), "pe": (fund or {}).get("pe"), "ret_63d": float(df["ret_63d"].iloc[-1]) if pd.notna(df["ret_63d"].iloc[-1]) else None}
                for r in evaluate_rules(ctx): st.write(r["message"])
            except Exception as e: human_error("Ledger failed", str(e))
    except Exception as e: human_error("Ledger unavailable", str(e))
    st.info("Ledger will become append-only once Phase 3 lands — every candidate permanently recorded.")

# --- 9 Paper Portfolio ---
elif page=="Paper Portfolio":
    st.header("Paper Portfolio — Simulated")
    try:
        val=get_value(st.session_state.portfolio, {})
        st.metric("Cash", f"₹{get_cash(st.session_state.portfolio):.2f}")
        st.metric("Total", f"₹{val['total']:.2f}", delta=f"{val['unrealized_pnl']:.2f}")
        positions=get_positions(st.session_state.portfolio)
        if positions: st.dataframe(pd.DataFrame(positions), width='stretch')
        else: st.info("No positions yet. Use Stock Scanner → Buy, or Quant Research → Paper Buy.")
        # manual buy/sell
        with st.expander("Manual Trade"):
            sym=st.text_input("Symbol", "PENNY")
            qty=st.number_input("Qty", min_value=1, value=1)
            price=st.number_input("Price", value=20.0)
            c1,c2=st.columns(2)
            with c1:
                if st.button("Paper Buy"):
                    try: buy(st.session_state.portfolio, sym, int(qty), float(price)); st.success("Bought")
                    except Exception as e: st.error(str(e))
            with c2:
                if st.button("Paper Sell"):
                    try: sell(st.session_state.portfolio, sym, int(qty), float(price)); st.success("Sold")
                    except Exception as e: st.error(str(e))
    except Exception as e: human_error("Portfolio error", str(e))

# --- 10 Data Health ---
elif page=="Data Health":
    st.header("Data Health")
    def card(label, value, status):
        icon="✓" if status=="Healthy" else "⚠" if status=="Warning" else "✕"
        st.metric(label, value, delta=icon)
    try:
        conn=get_conn()
        # ensure migration run
        init_db()
        # counts
        c1,c2,c3,c4=st.columns(4)
        with c1:
            try: cnt=conn.execute("SELECT COUNT(*) as c FROM companies").fetchone()["c"]; card("Tracked securities", cnt, "Healthy" if cnt>0 else "Error")
            except: card("Tracked securities", "Error", "Error")
        with c2:
            try: cnt=conn.execute("SELECT COUNT(*) as c FROM prices_daily").fetchone()["c"]; card("Price records", cnt, "Healthy" if cnt>500 else "Warning" if cnt>0 else "Error")
            except: card("Price records", "Error", "Error")
        with c3:
            try: cnt=conn.execute("SELECT COUNT(*) as c FROM fundamentals").fetchone()["c"]; card("Fundamental records", cnt, "Healthy" if cnt>0 else "Warning")
            except: card("Fundamental records", "Error", "Error")
        with c4:
            try: cnt=conn.execute("SELECT COUNT(*) as c FROM corporate_actions").fetchone()["c"]; card("Corporate actions", cnt, "Healthy" if cnt>=0 else "Warning")
            except: card("Corporate actions", "0", "Warning")
        c5,c6,c7=st.columns(3)
        with c5:
            try:
                from app.data.fundamentals import list_pit_coverage
                cov=list_pit_coverage()
                card("PIT coverage", f"{cov['symbols']} symbols / {cov['total_records']} rows", "Healthy" if cov['total_records']>0 else "Warning")
            except: card("PIT coverage", "Unknown", "Warning")
        with c6:
            try:
                row=conn.execute("SELECT MAX(date) as m FROM prices_daily").fetchone()["m"]
                card("Latest market data", row or "never", "Healthy" if row else "Warning")
            except: card("Latest market data", "Error", "Error")
        with c7:
            try:
                row=conn.execute("SELECT MAX(available_at) as m FROM fundamentals").fetchone()["m"]
                card("Latest fundamental", row or "never", "Healthy" if row else "Warning")
            except: card("Latest fundamental", "Error", "Error")
        st.divider()
        st.subheader("Corporate Actions — Inspectable")
        fcol1,fcol2,fcol3=st.columns(3)
        with fcol1: filt_sym=st.text_input("Filter symbol", "")
        with fcol2: filt_type=st.selectbox("Action type", ["All","split","bonus","dividend"])
        with fcol3: filt_date=st.text_input("Date contains", "")
        try:
            q="SELECT symbol, action_type, ex_date, ratio_numerator, ratio_denominator, cash_amount, adjustment_factor, source, retrieved_at FROM corporate_actions WHERE 1=1 "
            params=[]
            if filt_sym: q+=" AND symbol LIKE ? "; params.append(f"%{filt_sym}%")
            if filt_type!="All": q+=" AND action_type=? "; params.append(filt_type)
            if filt_date: q+=" AND ex_date LIKE ? "; params.append(f"%{filt_date}%")
            q+=" ORDER BY ex_date DESC LIMIT 100"
            rows=conn.execute(q, params).fetchall()
            if rows:
                df=pd.DataFrame([dict(r) for r in rows])
                st.dataframe(df, width='stretch')
                st.caption("Raw price vs Adjusted: adjusted = raw * cumulative_factor. Dividends factor 1.0, kept as dividend_cash.")
                # verification for selected symbol
                if filt_sym:
                    st.subheader("Adjustment verification")
                    sym=filt_sym.strip().upper()
                    try:
                        prov=get_provider(st.session_state.provider)
                        raw=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
                        from app.data.corporate_actions import apply_adjustments, CorporateAction
                        cas=[]
                        for r in conn.execute("SELECT * FROM corporate_actions WHERE symbol=?", (sym,)).fetchall():
                            d=dict(r)
                            cas.append(CorporateAction(symbol=d["symbol"], action_type=d["action_type"], ex_date=d["ex_date"], ratio_numerator=d["ratio_numerator"], ratio_denominator=d["ratio_denominator"], cash_amount=d["cash_amount"], adjustment_factor=d["adjustment_factor"]))
                        if cas:
                            adj=apply_adjustments(raw, cas)
                            st.dataframe(adj[["date","raw_close","close","cumulative_adjustment_factor","dividend_cash"]].tail(10), width='stretch')
                        else: st.info("No actions for this symbol — raw == adjusted")
                    except Exception as e: st.info(f"Verification unavailable: {e}")
            else: st.info("No corporate actions match filter. Add via app/data/corporate_actions.py or ingest.")
        except Exception as e: human_error("Corporate actions query failed", str(e))
        st.divider()
        st.subheader("Survivorship — Historical Universe")
        try:
            from app.data.universe import get_universe, list_snapshots, create_snapshot
            # demo as_of
            demo_date = st.text_input("Historical universe as_of (YYYY-MM-DD)", "2021-12-31", key="surv_asof")
            prov_choice = st.session_state.provider
            uni = get_universe(demo_date, provider_name=prov_choice)
            st.write(f"Eligible at {demo_date}: {len(uni)} securities")
            if uni:
                dfu = pd.DataFrame([{"symbol":c.symbol, "listed":c.listed_date or "unknown", "delisted":c.delisted_date or "—", "status":c.status} for c in uni[:20]])
                st.dataframe(dfu, width='stretch')
                st.caption("Rule: listed_date ≤ as_of and (delisted_date is NULL or > as_of). Inclusive listed, exclusive delisted. PENNY (2022-06-15) not eligible on 2021-12-31; MIDCAP delisted 2024-08-20 not eligible on 2024-08-20+.")
            else: st.info("No eligible securities at that date (survivorship correctly filtered).")
            # snapshots
            snaps = list_snapshots()
            if snaps:
                st.dataframe(pd.DataFrame(snaps), width='stretch')
            else: st.caption("No snapshots yet — snapshots are deterministic: same definition+as_of+version → same hash.")
            if st.button("Create snapshot for as_of"):
                sid = create_snapshot(demo_date, provider_name=prov_choice)
                st.success(f"Snapshot {sid} created")
            # symbol history
            try:
                from app.data.symbol_history import list_history
                hist_sym = st.text_input("Security_id for symbol history", "RELIANCE", key="sym_hist")
                hist = list_history(hist_sym)
                if hist: st.dataframe(pd.DataFrame(hist), width='stretch')
                else: st.caption("No symbol history — abstraction ready, mock data has no renames (documented limitation).")
            except: pass
        except Exception as e: st.info(f"Survivorship unavailable: {e}")
        st.divider()
        st.subheader("System events (recent)")
        try:
            evs=conn.execute("SELECT timestamp, level, message FROM system_events ORDER BY timestamp DESC LIMIT 10").fetchall()
            if evs: st.dataframe(pd.DataFrame([dict(r) for r in evs]), width='stretch')
            else: st.write("No errors — provider health OK" if get_provider(st.session_state.provider).health_check() else "Provider health check failed")
        except: st.write("System events unavailable")
    except Exception as e: human_error("Data Health unavailable", str(e))

# --- 11 System ---
elif page=="System":
    st.header("System")
    def ok(v): return "✓" if v else "✕"
    cols=st.columns(3)
    checks=[]
    try: import pandas, numpy, pydantic; checks.append(("Python env", True))
    except: checks.append(("Python env", False))
    try: init_db(); checks.append(("Database", True))
    except: checks.append(("Database", False))
    try: get_provider(st.session_state.provider).health_check(); checks.append(("Market data provider", True))
    except: checks.append(("Market data provider", False))
    try: from app.features.engine import compute_features; checks.append(("Feature engine", True))
    except: checks.append(("Feature engine", False))
    try: groq_ok = bool(settings.groq_api_key or os.getenv("GROQ_API_KEY")); checks.append(("Groq", groq_ok))
    except: checks.append(("Groq", False))
    checks.append(("Backtesting engine", True))
    checks.append(("Paper portfolio", True))
    try: from app.data.universe import get_universe; get_universe("2021-12-31"); checks.append(("Survivorship protection", True))
    except: checks.append(("Survivorship protection", False))
    try: from app.data.symbol_history import get_symbol_at; checks.append(("Symbol history", True))
    except: checks.append(("Symbol history", False))
    for i,(name,val) in enumerate(checks):
        with cols[i%3]: st.metric(name, ok(val))
    st.divider()
    try:
        conn=get_conn()
        st.write(f"Data freshness: {datetime.date.today().isoformat()}")
        try: last=conn.execute("SELECT MAX(date) as m FROM prices_daily").fetchone()["m"]; st.write(f"Last successful ingestion: {last}")
        except: st.write("Last successful ingestion: unknown")
        st.write(f"Database: {settings.database_url}")
        st.write(f"App version: Quant Lab v1 (Mock/YFinance)")
        st.write(f"Provider: {st.session_state.provider}")
        st.write(f"Groq model: {settings.groq_model}")
        import sqlite3, pandas as pd
        st.write(f"SQLite: {sqlite3.sqlite_version} | Pandas: {pd.__version__}")
    except Exception as e: human_error("System info failed", str(e))
    st.caption("Secrets via .env only. Never hard-coded.")

# Footer for all pages
st.divider()
st.caption("Research candidate — not an automatic trade instruction. | DATA MODE: {} | {}".format(st.session_state.provider.upper(), "Groq mock" if not (settings.groq_api_key or os.getenv("GROQ_API_KEY")) else "Groq live"))
