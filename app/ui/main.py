import streamlit as st, pandas as pd, datetime, json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from app.config.settings import settings
from app.data.registry import get_provider
from app.features.engine import compute_features
from app.screening.run import run_screen
from app.backtesting.run import run_backtest
from app.portfolio.portfolio import create_portfolio, get_value, buy, sell, get_positions, get_cash, get_portfolio
from app.portfolio.budget import BudgetInput, assess_affordability
from app.screening.rules import evaluate_rules
from app.ai.groq_client import analyst_call, critic_call
from app.features.regime import classify_regime
from app.database.db import init_db, get_conn
import plotly.graph_objs as go

st.set_page_config(page_title="Stock Lab", layout="wide")
init_db()

if "budget" not in st.session_state: st.session_state.budget=150
if "provider" not in st.session_state: st.session_state.provider="mock"
if "portfolio" not in st.session_state: st.session_state.portfolio="default"
create_portfolio(st.session_state.portfolio, st.session_state.budget)

# Sidebar
st.sidebar.title("Stock Lab")
st.sidebar.caption("Research candidate — not an automatic trade instruction.")
st.session_state.budget = st.sidebar.number_input("Budget (₹)", min_value=50.0, value=float(st.session_state.budget), step=50.0)
st.session_state.provider = st.sidebar.selectbox("Provider", ["mock","yfinance"], index=0)
st.session_state.portfolio = st.sidebar.text_input("Portfolio name", st.session_state.portfolio)
create_portfolio(st.session_state.portfolio, st.session_state.budget)
st.sidebar.markdown(f"**Data as of:** {datetime.date.today().isoformat()}")
# freshness warning
try:
    conn=get_conn(); row=conn.execute("SELECT MAX(date) as d FROM prices_daily").fetchone()
    last=row["d"] if row and row["d"] else "never"
    st.sidebar.caption(f"Last price date in DB: {last}")
    if last!="never":
        delta=(datetime.date.today() - datetime.date.fromisoformat(last)).days
        if delta>5: st.sidebar.warning("WARNING: DATA MAY BE STALE")
except: pass
if not (settings.groq_api_key or __import__('os').getenv("GROQ_API_KEY")): st.sidebar.warning("Groq API key not set → AI mock mode")

# Overview page inline
st.title("Overview")
c1,c2,c3,c4=st.columns(4)
with c1: st.metric("Budget", f"₹{st.session_state.budget:.0f}")
with c2:
    val=get_value(st.session_state.portfolio, {})
    st.metric("Portfolio Value", f"₹{val['total']:.2f}", delta=f"{val['unrealized_pnl']:.2f}")
with c3: st.metric("Positions", len(val["positions"]))
with c4:
    prov=get_provider(st.session_state.provider)
    st.metric("Universe", len(prov.get_universe()))
st.info("Use pages in sidebar. This MVP shows all sections on one page. See app/ui/pages for separate pages.")

# Market Scanner
st.header("Market Scanner")
if st.button("Run Scanner"):
    with st.spinner("Screening..."):
        res=run_screen(st.session_state.budget, st.session_state.provider)
        st.success(f"Candidates: {len(res['candidates'])} / {res['universe']}")
        if res["candidates"]:
            df=pd.DataFrame(res["candidates"])[["symbol","reason","momentum_percentile","roe_percentile"]]
            st.dataframe(df, use_container_width=True)
        else:
            st.write("No candidates. Try larger budget or check Data Health.")
        with st.expander("All results"): st.json(res["all_results"][:50])

# Stock Detail
st.header("Stock Detail")
symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
sym=st.selectbox("Select symbol", symbols, key="detail_sym")
try:
    prov=get_provider(st.session_state.provider)
    df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
    df=compute_features(df)
    st.caption(f"Data as of: {df['date'].iloc[-1]}")
    fig=go.Figure()
    fig.add_trace(go.Candlestick(x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Price"))
    fig.add_trace(go.Scatter(x=df["date"], y=df["ma20"], name="MA20", line=dict(width=1)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["ma50"], name="MA50", line=dict(width=1)))
    st.plotly_chart(fig, use_container_width=True)
    st.plotly_chart(go.Figure(go.Bar(x=df["date"], y=df["volume"], name="Volume")), use_container_width=True)
    # metrics
    fund=prov.get_fundamentals(sym)
    st.subheader("Metrics")
    st.json({"fundamentals": fund, "last_close": float(df["close"].iloc[-1]), "vol20": float(df["vol20"].iloc[-1]) if not pd.isna(df["vol20"].iloc[-1]) else None, "regime": classify_regime(df)})
    # budget check
    b=BudgetInput(total_capital=st.session_state.budget)
    aff=assess_affordability(float(df["close"].iloc[-1]), b)
    st.write(f"**Affordable?** {'YES' if aff.affordable else 'NO'} — {aff.reason} (Attractive ≠ Affordable)")
    # rules
    ctx={"avg_volume": float(df["volume"].tail(20).mean()), "roe": (fund or {}).get("roe"), "debt_equity": (fund or {}).get("debt_equity"), "pe": (fund or {}).get("pe"), "ret_63d": float(df["ret_63d"].iloc[-1]) if not pd.isna(df["ret_63d"].iloc[-1]) else None}
    rules=evaluate_rules(ctx)
    for r in rules: st.write(r["message"])
    if st.button("Paper Buy 1 share"):
        try: buy(st.session_state.portfolio, sym, 1, float(df["close"].iloc[-1])); st.success("Bought 1 share (paper)")
        except Exception as e: st.error(str(e))
except Exception as e: st.error(f"Data unavailable: {e}")

# AI Research
st.header("AI Research")
if st.button("Run AI Analysis (cached, rate-limited)"):
    try:
        prov=get_provider(st.session_state.provider)
        df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
        df=compute_features(df)
        fund=prov.get_fundamentals(sym)
        verified={"symbol":sym, "price":float(df["close"].iloc[-1]), "fundamentals":fund, "features":{"ret_63d": float(df["ret_63d"].iloc[-1]) if not pd.isna(df["ret_63d"].iloc[-1]) else None}}
        analyst=analyst_call(sym, verified)
        critic=critic_call(sym, analyst, verified)
        st.subheader("Analyst")
        st.json(analyst)
        st.subheader("Devil's Advocate")
        st.json(critic)
        st.caption("Confidence = analysis quality, not price prediction. Research candidate — not trade instruction.")
    except Exception as e: st.error(f"AI unavailable: {e}")

# Backtesting Lab
st.header("Backtesting Lab — BASELINE EXPERIMENT")
if st.button("Run Backtest"):
    res=run_backtest(sym, st.session_state.provider, walk=True)
    st.json(res["metrics"])
    st.write("Benchmark", res["benchmark"])
    if res["walk_forward"]:
        st.subheader("Walk-Forward (IN-SAMPLE vs OUT-OF-SAMPLE)")
        st.json(res["walk_forward"][:3])
        st.warning("Do not present in-sample as proof of future performance.")
    if res["trades"]: st.dataframe(pd.DataFrame(res["trades"]).head(20))

# Paper Portfolio
st.header("Paper Portfolio")
val=get_value(st.session_state.portfolio, {})
st.write(val)
positions=get_positions(st.session_state.portfolio)
if positions: st.dataframe(pd.DataFrame(positions))
else: st.write("No positions yet. Use Stock Detail to buy.")
cash=get_cash(st.session_state.portfolio)
st.metric("Cash", f"₹{cash:.2f}")

# Data Health
st.header("Data Health")
try:
    conn=get_conn()
    for tbl in ["companies","prices_daily","features_daily"]:
        cnt=conn.execute(f"SELECT COUNT(*) as c FROM {tbl}").fetchone()["c"]
        st.write(f"{tbl}: {cnt} rows")
    st.write("System events:")
    evs=conn.execute("SELECT * FROM system_events ORDER BY timestamp DESC LIMIT 10").fetchall()
    if evs: st.dataframe(pd.DataFrame([dict(e) for e in evs]))
    else: st.write("No errors logged — provider health OK" if get_provider(st.session_state.provider).health_check() else "Provider health check failed")
except Exception as e: st.error(str(e))

# Settings
st.header("Settings")
st.json({"groq_model":settings.groq_model, "database":str(settings.database_url), "provider":st.session_state.provider})
st.caption("Secrets via .env only. Never hard-coded.")
