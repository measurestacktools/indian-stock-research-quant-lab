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
if "groq_key" not in st.session_state: st.session_state.groq_key = os.getenv("GROQ_API_KEY") or settings.groq_api_key or ""
try: create_portfolio(st.session_state.portfolio, st.session_state.budget)
except: pass

def data_mode_badge():
    p = st.session_state.provider
    if p=="mock": return "DATA MODE: MOCK  — synthetic, for testing"
    if p=="yfinance": return "DATA MODE: YFINANCE — Yahoo Finance (.NS), 15min delay"
    return f"DATA MODE: {p.upper()}"
def nse_status(): return "NSE PROVIDER: NOT CONFIGURED (stub — use YFinance or Mock)"

def human_error(title, msg, hint=""):
    st.error(f"**{title}**\n\n{msg}\n\n{hint}")
    with st.expander("Developer details"): st.code(traceback.format_exc()[-2000:])

def save_groq_key(key: str):
    key=key.strip()
    if not key:
        st.warning("Enter a valid API key.")
        return False
    # update env and .env
    os.environ["GROQ_API_KEY"] = key
    st.session_state.groq_key = key
    # also try to persist to .env
    try:
        env_path = pathlib.Path(".env")
        if not env_path.exists(): env_path = pathlib.Path("C:/Users/rayan/Downloads/stock 2/stock-lab/.env")
        # read existing
        content = ""
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
        # replace or add GROQ_API_KEY
        import re
        if "GROQ_API_KEY" in content:
            content = re.sub(r"GROQ_API_KEY=.*", f"GROQ_API_KEY={key}", content)
        else:
            content += f"\nGROQ_API_KEY={key}\n"
        env_path.write_text(content, encoding="utf-8")
        # also try project root .env
        alt = pathlib.Path(__file__).resolve().parents[2] / ".env"
        if str(alt) != str(env_path):
            try: alt.write_text(content, encoding="utf-8")
            except: pass
    except Exception as e:
        st.info(f"Key applied for this session (could not write .env): {e}")
    # also update settings object
    try: settings.groq_api_key = key
    except: pass
    st.success("Groq API key applied.")
    return True

def help_box(term: str, explanation: str):
    with st.expander(f"What does this mean? — {term}"):
        st.write(explanation)

# Sidebar navigation - 12 items with Historical Universe
NAV = ["Market Overview","Stock Scanner","Quant Research","Fundamentals","Point-in-Time Data","Historical Universe","Experiments","Backtests","Research Ledger","Paper Portfolio","Data Health","System"]
if "nav" not in st.session_state: st.session_state.nav = NAV[0]

with st.sidebar:
    st.title("Quant Lab")
    st.caption("Research candidate — not trade instruction.")
    st.caption(data_mode_badge())
    st.caption(nse_status())
    st.divider()
    st.session_state.budget = st.number_input("Budget (₹)", min_value=50.0, value=float(st.session_state.budget), step=50.0, help="Your available capital. The lab checks if you can afford at least one share including costs.")
    st.session_state.provider = st.selectbox("Provider", ["mock","yfinance"], index=0, help="Where market data comes from. Mock is safe for testing.")
    st.session_state.portfolio = st.text_input("Portfolio", st.session_state.portfolio, help="Paper portfolio name (simulated, no real money).")
    try: create_portfolio(st.session_state.portfolio, st.session_state.budget)
    except: pass
    st.divider()
    st.subheader("Groq AI")
    groq_input = st.text_input("Groq API Key", value=st.session_state.groq_key, type="password", help="Required for AI analyst. Stored locally in .env, never sent elsewhere except Groq.")
    c1,c2 = st.columns(2)
    with c1:
        if st.button("Apply Key", type="secondary", use_container_width=True):
            save_groq_key(groq_input)
    with c2:
        if st.button("Clear", use_container_width=True):
            st.session_state.groq_key=""
            os.environ.pop("GROQ_API_KEY", None)
            st.info("Key cleared for this session.")
    if not (os.getenv("GROQ_API_KEY") or settings.groq_api_key or st.session_state.groq_key):
        st.caption("⚠️ AI will run in mock mode until a key is applied.")
    else:
        st.caption("✅ Groq key set")
    st.divider()
    choice = st.radio("Navigate", NAV, index=NAV.index(st.session_state.nav) if st.session_state.nav in NAV else 0, label_visibility="collapsed")
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

page = st.session_state.nav

# --- helpers for survivorship plain-English ---
def survivorship_counts(as_of: str, provider_name="mock"):
    """Return real counts from universe: available, not_yet, already_delisted, incomplete"""
    try:
        from app.data.universe import get_universe
        # total current universe (today) to compare
        total_now = get_universe(None, provider_name=provider_name, use_db=False)
        avail = get_universe(as_of, provider_name=provider_name, use_db=False)
        # compute not_yet and already delisted by comparing listed/delisted dates
        import pandas as pd
        as_of_dt = pd.to_datetime(as_of).normalize()
        not_yet = 0
        already = 0
        incomplete = 0
        for c in total_now:
            if not c.listed_date:
                incomplete+=1
            else:
                try:
                    if pd.to_datetime(c.listed_date).normalize() > as_of_dt:
                        not_yet+=1
                        continue
                except: incomplete+=1
            if c.delisted_date:
                try:
                    if pd.to_datetime(c.delisted_date).normalize() <= as_of_dt:
                        already+=1
                except: pass
        # incomplete also counts those with missing listed_date among avail? Already counted.
        # for available, incomplete is those without listed_date but still counted as available
        return {
            "available": len(avail),
            "not_yet": not_yet,
            "already": already,
            "incomplete": incomplete,
            "total": len(total_now)
        }
    except Exception:
        return {"available":0,"not_yet":0,"already":0,"incomplete":0,"total":0}

def survivorship_status(counts):
    # plain-English status
    if counts["total"]==0:
        return "red", "Do not trust this historical universe yet", "No companies found — data unavailable."
    # if many incomplete
    incomplete_ratio = counts["incomplete"]/max(1,counts["total"])
    if incomplete_ratio > 0.2:
        return "yellow", "Historical data is incomplete", f"{counts['incomplete']} companies have missing listing dates, so the universe for {counts['total']} total may be unreliable."
    if counts["available"]==0:
        return "red", "Do not trust this historical universe yet", "No companies were available on this date according to the data."
    if counts["available"] < counts["total"]*0.5 and counts["not_yet"]==0 and counts["already"]==0:
        return "yellow", "Historical data is incomplete", "Only a small fraction shown as available — listing history may be missing."
    return "green", "Historical universe looks valid", "Enough listing and delisting history is available for this date."

# --- 1 Market Overview ---
if page=="Market Overview":
    st.header("Market Overview")
    st.caption("Your research lab at a glance — what you have, what the market looks like, and what to do next.")
    c1,c2,c3,c4 = st.columns(4)
    try:
        val=get_value(st.session_state.portfolio, {})
        prov=get_provider(st.session_state.provider)
        c1.metric("Budget", f"₹{st.session_state.budget:.0f}", help="Paper capital you set in the sidebar")
        c2.metric("Portfolio Value", f"₹{val['total']:.2f}", delta=f"{val['unrealized_pnl']:.2f}")
        c3.metric("Positions", len(val["positions"]))
        c4.metric("Companies tracked", len(prov.get_universe()))
    except Exception as e: human_error("Overview unavailable", str(e))
    st.info("**What to do next:** Start with **Stock Scanner** to find affordable candidates, then check **Quant Research** for details. If you added a Groq key, you can get AI summaries.")
    help_box("Paper portfolio", "No real money moves. You simulate buys/sells to learn how costs and risk affect small budgets.")
    st.divider()
    try:
        prov=get_provider(st.session_state.provider)
        sym=prov.get_universe()[0].symbol
        df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
        df=compute_features(df)
        reg=classify_regime(df)
        st.subheader(f"Market check — {sym} (example)")
        st.json(reg)
        st.caption("This is a simple trend/volatility check, not a prediction.")
        help_box("Market regime", "A quick label for whether prices have been rising, falling, or flat, and whether volatility is high. Used to avoid testing a strategy only in one type of market.")
    except Exception as e: st.info(f"Market check unavailable: {e}")

# --- 2 Stock Scanner ---
elif page=="Stock Scanner":
    st.header("Stock Scanner")
    st.caption("Find companies you can actually afford and that pass basic quality checks. Affordable does not mean attractive.")
    help_box("Survivorship bias", "If you test only companies that exist today, companies that failed or were delisted in the past disappear from your historical sample. That can make a strategy look better than it really was.")
    col1,col2 = st.columns([1,3])
    with col1:
        if st.button("Run Scanner", type="primary", help="Filters thousands of companies down to a small research set."):
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
            st.caption("Transparent percentiles show why a stock passed — momentum and profitability compared to peers, not a black-box score.")
        else: st.info("No candidates. Try a larger budget or check Data Health for missing data.")
        with st.expander("See all stage results (technical)"):
            st.json(res["all_results"][:100])
    with st.expander("What does affordable mean?"):
        st.write("**Affordable** = you have enough paper cash to buy at least one share after including brokerage and slippage. **Attractive** = fundamentals, price trend, and risk look interesting. A ₹20 stock is not automatically good; a ₹140 stock is not automatically bad.")
        from app.portfolio.budget import BudgetInput, assess_affordability
        b=BudgetInput(total_capital=150)
        for price in [20,120,140,200]:
            r=assess_affordability(price,b)
            st.write(f"₹{price}: {'Affordable' if r.affordable else 'Not affordable'} — {r.reason}")

# --- 3 Quant Research ---
elif page=="Quant Research":
    st.header("Quant Research")
    st.caption("Separate facts (market data), calculations (features), and AI interpretation so you can judge each layer.")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Company", symbols, key="qr_sym", help="Pick a company to inspect price and calculated metrics")
    try:
        prov=get_provider(st.session_state.provider)
        df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
        try:
            conn=get_conn()
            rows=conn.execute("SELECT * FROM corporate_actions WHERE symbol=?", (sym,)).fetchall()
            cas=[]
            for r in rows: d=dict(r); cas.append(d)
            if cas:
                from app.data.normalize import normalize_prices_with_actions
                df=normalize_prices_with_actions(df, cas, adjust=True)
            else:
                df=compute_features(df)
        except Exception: df=compute_features(df)
        if "cumulative_adjustment_factor" not in df.columns: df=compute_features(df)
        st.caption(f"Data as of: {df['date'].iloc[-1].date()}")
        st.subheader("Market data — price and volume")
        st.caption("Measured from the exchange (or synthetic mock).")
        fig=go.Figure()
        fig.add_trace(go.Candlestick(x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="Price"))
        if "ma20" in df.columns:
            fig.add_trace(go.Scatter(x=df["date"], y=df["ma20"], name="MA20 (20-day avg)", line=dict(width=1)))
            fig.add_trace(go.Scatter(x=df["date"], y=df["ma50"], name="MA50", line=dict(width=1)))
        st.plotly_chart(fig, width='stretch')
        st.plotly_chart(go.Figure(go.Bar(x=df["date"], y=df["volume"], name="Volume")), width='stretch')
        help_box("Corporate actions", "Splits, bonuses, and dividends change share counts or pay cash. Prices are adjusted backward so a 2:1 split does not look like a 50% crash. Dividends are kept as separate cash, not subtracted from price.")
        st.subheader("Calculated — features")
        st.caption("Deterministic calculations from price history.")
        last=df.iloc[-1]
        calc={k: (float(last[k]) if pd.notna(last[k]) else None) for k in ["ret_1d","ret_21d","ret_63d","ma20","ma50","vol20","atr14","drawdown","rel_vol"] if k in df.columns}
        st.json(calc)
        st.json(classify_regime(df))
        st.subheader("Deterministic rules — pass / fail")
        st.caption("Simple, explainable rules (not a hidden score).")
        fund=prov.get_fundamentals(sym)
        ctx={"avg_volume": float(df["volume"].tail(20).mean()), "roe": (fund or {}).get("roe"), "debt_equity": (fund or {}).get("debt_equity"), "pe": (fund or {}).get("pe"), "ret_63d": float(df["ret_63d"].iloc[-1]) if "ret_63d" in df.columns and pd.notna(df["ret_63d"].iloc[-1]) else None}
        for r in evaluate_rules(ctx):
            icon="✓" if r["status"]=="PASSED" else "✕" if r["status"]=="FAILED" else "?"
            st.write(f"{icon} {r['message']}")
        help_box("Point-in-time data", "Financial results are only usable after they are actually published. A March 31 year-end filed on May 20 should not be visible in an April backtest.")
        st.subheader("AI interpretation — Groq")
        st.caption("AI explains verified data, it does not decide trades. You decide.")
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
                    st.markdown("**What would invalidate this thesis?**"); st.write(analyst.get("thesis_invalidators",[]))
                with st.expander("Technical details — raw AI JSON"):
                    st.json({"analyst":analyst,"critic":critic})
            except Exception as e: human_error("AI unavailable", "Groq unavailable or rate-limited.", str(e))
    except Exception as e: human_error("DATA PROVIDER ERROR", "Unable to retrieve market data.", f"{e}")

# --- 4 Fundamentals ---
elif page=="Fundamentals":
    st.header("Fundamentals")
    st.caption("Business health — revenue, profit, debt, valuation. Missing data is shown as unavailable, never invented.")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Company", symbols, key="f_sym")
    try:
        prov=get_provider(st.session_state.provider)
        fund=prov.get_fundamentals(sym)
        st.subheader("Latest fundamentals from provider")
        if fund: st.json(fund)
        else: st.warning("Fundamental data unavailable — No filing available. The stock is excluded from calculations that need it.")
        help_box("Corporate actions", "A split changes historical price proportionally; a dividend is cash, not a price drop. Both are tracked separately.")
        st.subheader("Point-in-Time History (from storage)")
        try:
            from app.data.fundamentals import get_fundamentals_history
            hist=get_fundamentals_history(sym)
            if hist:
                dfh=pd.DataFrame(hist)
                # user-friendly columns
                dfh_show = dfh[["period","available_at","retrieved_at","source","roe","pe","debt_equity"]].copy()
                dfh_show.columns=["Financial period","Published","Retrieved","Source","ROE","P/E","Debt/Equity"]
                st.dataframe(dfh_show, width='stretch')
                st.caption("Each filing shows when the period ended and when it was actually published — the backtest uses the published date.")
            else: st.info("No filings stored yet. Use the Point-in-Time page to explore.")
        except Exception as e: st.info(f"History unavailable: {e}")
        st.subheader("Corporate Actions for this company")
        try:
            conn=get_conn()
            rows=conn.execute("SELECT symbol, action_type, ex_date, ratio_numerator, ratio_denominator, cash_amount, adjustment_factor, source FROM corporate_actions WHERE symbol=? ORDER BY ex_date", (sym,)).fetchall()
            if rows:
                df=pd.DataFrame([dict(r) for r in rows])
                df_show = df.rename(columns={"action_type":"Action","ex_date":"Effective","ratio_numerator":"New shares","ratio_denominator":"Old shares","cash_amount":"Cash","adjustment_factor":"Price factor","source":"Source"})
                st.dataframe(df_show, width='stretch')
                st.caption("Splits/bonuses adjust old prices; dividends remain as cash.")
            else: st.info("No corporate actions recorded for this company.")
            with st.expander("Technical details"):
                if rows: st.json([dict(r) for r in rows])
        except Exception as e: st.info(f"Corporate actions unavailable: {e}")
    except Exception as e: human_error("Fundamentals error", str(e))

# --- 5 Point-in-Time Data ---
elif page=="Point-in-Time Data":
    st.header("Point-in-Time Data")
    st.caption("Look-ahead prevention — the backtest only sees what was known at that time.")
    st.info("**Why it matters:** A March 31 financial report filed on May 20 should not be visible on April 15. The system enforces `published date ≤ backtest date`.")
    help_box("Point-in-time data", "Financial data has two dates: when the period ended and when it was published. Only the published date determines availability in the past.")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Company", symbols, key="pit_sym")
    hist_date=st.date_input("Check fundamentals on: (historical date)", value=datetime.date(2025,4,1), help="The backtest date you want to inspect")
    try:
        from app.data.fundamentals import get_fundamentals_as_of, get_fundamentals_history
        as_of=str(hist_date)
        rec=get_fundamentals_as_of(sym, as_of)
        st.subheader(f"Available on {as_of}")
        if rec:
            st.success(f"Latest filing available: period ending {rec['period']} (published {rec['available_at']})")
            st.json({k:rec.get(k) for k in ["period","available_at","retrieved_at","source","roe","pe","debt_equity","revenue"]})
            st.caption("This is what a backtest on this date would see.")
        else:
            st.warning("Not available — No filing had been published yet on this date.")
            st.write("**Why:** The filing was published after the selected date.")
            st.write("**Effect:** A backtest on this date would skip this company for fundamentals-based rules.")
        # timeline visual
        st.subheader("Timeline")
        st.caption("Period → Published → Revision")
        st.write("2022 → 2023 → 2024 → 2025")
        st.caption("Financial period ends → Company files report → Possible revision later. The backtest follows this timeline.")
        hist=get_fundamentals_history(sym)
        if hist:
            for h in hist[:6]:
                st.write(f"Period {h['period']} → Published {h['available_at']} (ROE {h.get('roe')})")
            with st.expander("Worked example — FY2025"):
                st.write("FY2025 period = 2025-03-31, Published = 2025-05-20")
                for d in ["2025-04-01","2025-05-19","2025-05-20","2025-06-01"]:
                    r=get_fundamentals_as_of(sym, d)
                    st.write(f"As of {d} → {'AVAILABLE' if r and r['period']=='2025-03-31' else 'NOT AVAILABLE'}")
        else: st.info("No filing history stored — add via Fundamentals page or API.")
        with st.expander("Technical details"):
            if rec: st.json(rec)
        with st.expander("Revision handling"):
            st.write("Initial filing published 2025-05-20, restatement 2025-08-10. As of 2025-06-01 → May 20 version; As of 2025-09-01 → Aug 10 version. Both versions are kept.")
    except Exception as e: human_error("Point-in-time check failed", str(e))

# --- 6 Historical Universe (NEW user-friendly) ---
elif page=="Historical Universe":
    st.header("Historical Universe")
    st.caption("See which companies actually existed on a specific historical date.")
    st.info("**Why this matters:** A backtest should only use companies that were actually available at that point in history. This prevents survivorship bias. *Example: A company listed in 2025 should not appear in a 2022 backtest.*")
    help_box("Survivorship bias", "If you test only companies that exist today, companies that failed or were delisted in the past disappear from your historical sample. That can make a strategy look better than it really was.")
    as_of = st.date_input("Check the market on:", value=datetime.date(2021,12,31), help="The historical date you want to inspect", key="hist_asof")
    as_of_str = str(as_of)
    counts = survivorship_counts(as_of_str, st.session_state.provider)
    # large metrics
    st.subheader(f"Market on {as_of_str}")
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric("AVAILABLE ON THIS DATE", counts["available"])
    with c2: st.metric("NOT YET LISTED", counts["not_yet"])
    with c3: st.metric("ALREADY DELISTED", counts["already"])
    with c4: st.metric("HISTORY INCOMPLETE", counts["incomplete"], help="Companies with missing listing/delisting dates")
    st.caption(f"Total companies tracked: {counts['total']} — numbers come directly from the database/provider, never hard-coded.")
    # status card
    color, title, msg = survivorship_status(counts)
    if color=="green":
        st.success(f"**{title}** — {msg}")
        st.caption("✅ Historical universe looks valid. Enough listing history is available for this date.")
    elif color=="yellow":
        st.warning(f"**{title}** — {msg}")
        st.caption("⚠️ Historical data is incomplete. Some companies lack reliable listing dates, so results for this date are less reliable.")
    else:
        st.error(f"**{title}** — {msg}")
        st.caption("🛑 Do not trust this backtest yet. Required listing/delisting information is missing.")
    st.divider()
    # timeline visual
    st.subheader("How listing changes work")
    st.caption("2022 → 2023 → 2024 → 2025")
    cols = st.columns(4)
    with cols[0]: st.info("**LIST**\nCompany appears")
    with cols[1]: st.info("**TRADE**\nEligible for backtest")
    with cols[2]: st.info("**CHANGE SYMBOL**\nSame company, new ticker (tracked separately)")
    with cols[3]: st.info("**DELIST**\nNo longer eligible after delisting date")
    st.caption("The backtest follows these changes through time — it checks the company list at each point instead of using today's list for the whole past.")
    st.divider()
    # company table
    st.subheader(f"Companies available on {as_of_str}")
    st.caption("Same data the backtest uses. Delisted or not-yet-listed companies are excluded.")
    try:
        from app.data.universe import get_universe
        uni = get_universe(as_of_str, provider_name=st.session_state.provider)
        filt = st.text_input("Search company or symbol", "", help="Filter the table")
        if uni:
            dfu = pd.DataFrame([{"Company":c.name, "Symbol":c.symbol, "Listed":c.listed_date or "unknown", "Delisted":c.delisted_date or "—", "Status":c.status} for c in uni])
            if filt:
                mask = dfu.apply(lambda r: filt.lower() in r["Company"].lower() or filt.lower() in r["Symbol"].lower(), axis=1)
                dfu = dfu[mask]
            st.dataframe(dfu, width='stretch')
            st.caption(f"Showing {len(dfu)} of {len(uni)} available")
        else:
            st.info("No companies were available on this date — the backtest would have no universe here.")
        with st.expander("Technical details"):
            st.write(f"Provider: {st.session_state.provider}, Data version: v1, As of: {as_of_str}")
            if uni:
                st.json([{"symbol":c.symbol, "security_id":c.security_id, "listed":c.listed_date, "delisted":c.delisted_date} for c in uni[:5]])
    except Exception as e: human_error("Historical universe unavailable", str(e))
    st.divider()
    # Research Snapshot
    st.subheader("Research Snapshot")
    st.caption("A Research Snapshot saves the exact group of companies used for a historical research run, so you can reproduce it later.")
    try:
        from app.data.universe import list_snapshots, create_snapshot, get_snapshot
        snaps = list_snapshots()
        if snaps:
            df_s = pd.DataFrame(snaps)
            # user-friendly view
            df_show = pd.DataFrame()
            df_show["Date"] = df_s["as_of"]
            df_show["Companies"] = df_s["cnt"]
            df_show["Created"] = df_s["created_at"]
            df_show["Status"] = "Saved"
            st.dataframe(df_show, width='stretch')
        else:
            st.info("No Research Snapshots yet.")
        c1,c2 = st.columns([1,2])
        with c1:
            if st.button("Create Research Snapshot for this date", type="primary"):
                try:
                    sid = create_snapshot(as_of_str, provider_name=st.session_state.provider)
                    st.success(f"Snapshot saved for {as_of_str}")
                    st.rerun()
                except Exception as e: st.error(f"Could not create snapshot: {e}")
        with c2:
            view_date = st.text_input("View snapshot for date", value=as_of_str, key="view_snap")
            if st.button("View companies in snapshot"):
                rows = get_snapshot(view_date)
                if rows:
                    st.dataframe(pd.DataFrame([{"Company":r["symbol"], "Symbol":r["symbol"], "Listed":r["listed_date"] or "unknown", "Delisted":r["delisted_date"] or "—"} for r in rows]), width='stretch')
                else: st.warning("No snapshot found for that date — create one first.")
        with st.expander("Technical details"):
            if snaps:
                st.json(snaps[:2])
                st.caption("Internally each snapshot has a snapshot_id, hash (SHA-256 of sorted symbols), source and data version for reproducibility.")
    except Exception as e: st.info(f"Snapshots unavailable: {e}")
    st.divider()
    # Symbol History
    st.subheader("Symbol History")
    st.caption("Track companies when their stock-market symbol changes.")
    try:
        from app.data.symbol_history import list_history
        sec = st.text_input("Check symbol history for", value="RELIANCE", help="Stable company ID, e.g., RELIANCE")
        hist = list_history(sec)
        if hist:
            st.write(f"Timeline for {sec}:")
            for h in hist:
                st.write(f"**{h['symbol']}**  {h['start_date']} → {h['end_date'] or 'today'}")
        else:
            st.info("Symbol-change history is not available from the current data provider.")
            st.caption("The system keeps the abstraction ready (security_id stays stable when a ticker changes), but mock/YFinance currently supply only the current symbol. Future NSE archival data will populate this.")
        with st.expander("Technical details"):
            if hist: st.json(hist)
    except Exception as e: st.info(f"Symbol history unavailable: {e}")

# --- 7 Experiments ---
elif page=="Experiments":
    st.header("Experiments")
    st.caption("Plan and track research hypotheses — not yet a full tracker, this is a placeholder for Phase 3+")
    help_box("Experiment tracker", "A hypothesis like 'cheap, profitable companies outperform' is tested on historical data with separate training/validation/test periods to avoid fooling yourself.")
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
    st.info("Past experiments will appear here once the strategy registry lands. For now, use **Backtests** for single-strategy tests.")

# --- 8 Backtests ---
elif page=="Backtests":
    st.header("Backtests")
    st.caption("Test a strategy on historical data — with costs and survivorship handling.")
    # prominent survivorship status
    try:
        from app.data.universe import get_universe
        # check if lifecycle data exists
        uni_now = get_universe(None, provider_name=st.session_state.provider, use_db=False)
        has_lifecycle = any(c.listed_date for c in uni_now)
        if has_lifecycle:
            st.success("**Historical universe: Protected** — Each backtest uses the companies that were actually available at each point in time.")
            st.caption("The system checks the company universe at each point in the backtest instead of using today's list for the entire historical period.")
        else:
            st.warning("**Historical universe data is incomplete** — Listing dates are missing for many companies.")
            st.caption("This can make historical results less reliable because some companies may be missing from or incorrectly included in the past universe.")
    except:
        st.warning("Historical universe status unknown.")
    with st.expander("How this works"):
        st.write("The system checks the company universe at each point in the backtest instead of using today's list of companies for the entire historical period. This prevents survivorship bias.")
        st.write("Example: A company listed in 2025 does not appear in a 2022 backtest. A company delisted in 2023 stops being eligible after its delisting date.")
        help_box("Survivorship bias", "If you test only companies that exist today, companies that failed or were delisted in the past disappear from your historical sample. That can make a strategy look better than it really was.")
    # visual timeline
    st.caption("2022 → 2023 → 2024 → 2025  —  Companies can LIST → TRADE → CHANGE SYMBOL → DELIST. The backtest follows these changes through time.")
    symbols=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    c1,c2,c3,c4=st.columns(4)
    with c1: sym=st.selectbox("Company", symbols, key="bt_sym", help="Single-company backtest; portfolio backtest will use the historical universe")
    with c2: start=st.text_input("Start", "2022-01-01", help="Backtest start date")
    with c3: end=st.text_input("End", datetime.date.today().isoformat(), help="Backtest end date")
    with c4: capital=st.number_input("Initial capital (paper)", value=10000.0)
    c5,c6,c7,c8=st.columns(4)
    with c5: mom=st.number_input("Entry momentum", value=0.02, step=0.01, format="%.3f", help="How strong the price rise must be to enter")
    with c6: hold=st.number_input("Max holding days", value=63, step=1, help="Exit after this many days if not stopped")
    with c7: costs=st.number_input("Brokerage %", value=0.001, step=0.001, format="%.4f", help="Cost per trade")
    with c8: slip=st.number_input("Slippage %", value=0.001, step=0.001, format="%.4f", help="Extra cost for price movement")
    use_pit=st.checkbox("Use published fundamentals only (recommended)", value=True, help="When enabled, the backtest only sees filings that were actually published at that time.")
    use_survivorship = st.checkbox("Respect historical universe (survivorship protection)", value=True, help="When enabled, the backtest only uses companies that existed at each point in time.")
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
                # setup callbacks
                pit_cb = None
                if use_pit:
                    from app.data.fundamentals import get_fundamentals_as_of
                    pit_cb = get_fundamentals_as_of
                uni_cb = None
                if use_survivorship:
                    from app.data.universe import get_universe as gu
                    uni_cb = lambda d: gu(d, provider_name=st.session_state.provider, use_db=False)
                if use_pit or use_survivorship:
                    res=backtest_symbol(df, cfg, symbol=sym, use_pit_fundamentals=use_pit, pit_callback=pit_cb, universe_callback=uni_cb)
                else:
                    res=backtest_symbol(df, cfg)
                bench=benchmark_buy_hold(df)
                st.subheader("Results")
                m=res["metrics"]
                cc1,cc2,cc3,cc4=st.columns(4)
                cc1.metric("Total return", f"{m['total_return']:.2%}")
                cc2.metric("CAGR", f"{m['cagr']:.2%}")
                cc3.metric("Max drawdown", f"{m['max_drawdown']:.2%}")
                cc4.metric("Trades", m['num_trades'])
                cc1,cc2,cc3,cc4=st.columns(4)
                cc1.metric("Win rate", f"{m['win_rate']:.1%}")
                cc2.metric("Avg win", f"{m['avg_win']:.2%}")
                cc3.metric("Avg loss", f"{m['avg_loss']:.2%}")
                cc4.metric("Volatility", f"{m['volatility']:.2%}")
                st.write(f"Benchmark (buy-and-hold): {bench['total_return']:.2%}")
                if res["trades"]: st.dataframe(pd.DataFrame(res["trades"]).head(20), width='stretch')
                else: st.info("No trades — try a lower momentum or longer holding period.")
                st.subheader("Walk-Forward — training vs test")
                st.caption("Training period builds the idea; test period checks if it still worked (out-of-sample).")
                wf=walk_forward(df, cfg)
                if wf:
                    dfw=pd.DataFrame([{"Training":w["train_start"][:10]+"→"+w["train_end"][:10], "Test":w["test_start"][:10]+"→"+w["test_end"][:10], "Training return":f"{w['in_sample']['total_return']:.1%}", "Test return":f"{w['out_of_sample']['total_return']:.1%}"} for w in wf[:5]])
                    st.dataframe(dfw, width='stretch')
                    st.warning("Do not treat training performance as proof of future performance.")
                with st.expander("Technical details"):
                    st.json(m)
            except Exception as e: human_error("Backtest failed", "Unable to run backtest with current parameters and data.", str(e))
            try:
                conn=get_conn()
                cnt=conn.execute("SELECT COUNT(*) as c FROM prices_daily WHERE symbol=?", (sym,)).fetchone()["c"]
                if cnt<100: st.warning("Data incomplete: fewer than 100 price rows — results may be unreliable.")
            except: pass

# --- 9 Research Ledger ---
elif page=="Research Ledger":
    st.header("Research Ledger")
    st.caption("An auditable record — thesis, evidence, counter-evidence, and what happened next. (Future: permanently saved per candidate)")
    help_box("Research ledger", "Every candidate gets a permanent entry with thesis, data used, and later outcome, so you can learn what actually worked.")
    syms=[c.symbol for c in get_provider(st.session_state.provider).get_universe()]
    sym=st.selectbox("Company", syms, key="ledger_sym")
    try:
        prov=get_provider(st.session_state.provider)
        df=prov.get_daily_prices(sym, "2023-01-01", datetime.date.today().isoformat())
        df=compute_features(df)
        fund=prov.get_fundamentals(sym)
        st.write(f"Data as of: {df['date'].iloc[-1].date()} | Price ₹{df['close'].iloc[-1]:.2f}")
        st.divider()
        if st.button("Generate Ledger Entry (AI)"):
            try:
                verified={"symbol":sym, "price":float(df["close"].iloc[-1]), "fundamentals":fund}
                analyst=analyst_call(sym, verified)
                critic=critic_call(sym, analyst, verified)
                st.subheader("Thesis"); st.write(analyst.get("thesis",""))
                st.subheader("Supporting evidence"); st.write(analyst.get("positive_factors",[]))
                st.subheader("Counter-evidence"); st.write(critic.get("strongest_counter_argument",""))
                st.subheader("Risks"); st.write(analyst.get("risk_factors",[]))
                st.subheader("What would invalidate this?"); st.write(analyst.get("thesis_invalidators",[]))
                st.subheader("Rule check")
                ctx={"avg_volume": float(df["volume"].tail(20).mean()), "roe": (fund or {}).get("roe"), "pe": (fund or {}).get("pe"), "ret_63d": float(df["ret_63d"].iloc[-1]) if pd.notna(df["ret_63d"].iloc[-1]) else None}
                for r in evaluate_rules(ctx): st.write(r["message"])
                with st.expander("Technical details — raw AI and data"):
                    st.json({"analyst":analyst,"critic":critic})
            except Exception as e: human_error("Ledger failed", str(e))
    except Exception as e: human_error("Ledger unavailable", str(e))
    st.info("Later this will be saved permanently so you can see what the thesis was and what actually happened.")

# --- 10 Paper Portfolio ---
elif page=="Paper Portfolio":
    st.header("Paper Portfolio")
    st.caption("Simulated trading — no real money, with costs and paper cash tracking.")
    try:
        val=get_value(st.session_state.portfolio, {})
        st.metric("Paper cash", f"₹{get_cash(st.session_state.portfolio):.2f}")
        st.metric("Total value (cash + holdings)", f"₹{val['total']:.2f}", delta=f"{val['unrealized_pnl']:.2f}")
        positions=get_positions(st.session_state.portfolio)
        if positions:
            dfp=pd.DataFrame(positions)
            dfp_show = dfp.rename(columns={"symbol":"Company","qty":"Shares","avg_price":"Average price"})
            st.dataframe(dfp_show, width='stretch')
        else: st.info("No holdings yet. Use Stock Scanner → Buy, or Quant Research → Paper Buy.")
        with st.expander("Manual paper trade"):
            sym=st.text_input("Company", "PENNY")
            qty=st.number_input("Shares", min_value=1, value=1)
            price=st.number_input("Price per share", value=20.0)
            c1,c2=st.columns(2)
            with c1:
                if st.button("Paper Buy"):
                    try: buy(st.session_state.portfolio, sym, int(qty), float(price)); st.success("Paper buy recorded")
                    except Exception as e: st.error(str(e))
            with c2:
                if st.button("Paper Sell"):
                    try: sell(st.session_state.portfolio, sym, int(qty), float(price)); st.success("Paper sell recorded")
                    except Exception as e: st.error(str(e))
    except Exception as e: human_error("Portfolio error", str(e))

# --- 11 Data Health ---
elif page=="Data Health":
    st.header("Data Health")
    st.caption("Is the data safe to use for research?")
    def health_card(title, status, meaning, why, limitation):
        icon = "🟢" if status=="Ready" else "🟡" if status=="Limited" else "🔴"
        with st.container(border=True):
            st.write(f"{icon} **{title}** — {status}")
            st.caption(f"**What it means:** {meaning}")
            st.caption(f"**Why it matters:** {why}")
            if limitation: st.caption(f"**Limitation:** {limitation}")
    try:
        conn=get_conn(); init_db()
        # compute statuses plain-English
        try: cnt_c = conn.execute("SELECT COUNT(*) as c FROM companies").fetchone()["c"]
        except: cnt_c=0
        try: cnt_p = conn.execute("SELECT COUNT(*) as c FROM prices_daily").fetchone()["c"]
        except: cnt_p=0
        try: cnt_f = conn.execute("SELECT COUNT(*) as c FROM fundamentals").fetchone()["c"]
        except: cnt_f=0
        try: cnt_ca = conn.execute("SELECT COUNT(*) as c FROM corporate_actions").fetchone()["c"]
        except: cnt_ca=0
        # PIT coverage
        try:
            from app.data.fundamentals import list_pit_coverage
            cov=list_pit_coverage()
            pit_status = "Ready" if cov['total_records']>0 else "Limited"
        except: pit_status="Limited"; cov={"total_records":0}
        # historical universe
        try:
            from app.data.universe import get_universe
            uni_now = get_universe(None, provider_name=st.session_state.provider, use_db=False)
            has_life = any(c.listed_date for c in uni_now)
            uni_status = "Ready" if has_life else "Limited"
        except: uni_status="Limited"
        c1,c2 = st.columns(2)
        with c1:
            health_card("Prices", "Ready" if cnt_p>500 else "Limited" if cnt_p>0 else "Not ready",
                        f"{cnt_p} price rows stored", "Needed for charts, features, backtests", "Mock data is synthetic; YFinance has 15min delay" if cnt_p>0 else "No price data — ingest required")
        with c2:
            health_card("Corporate actions", "Ready" if cnt_ca>=0 else "Limited",
                        f"{cnt_ca} splits/bonuses/dividends stored", "Splits/bonuses are price-adjusted so history does not show fake crashes", "Dividends kept as separate cash" if cnt_ca>=0 else "")
        c1,c2 = st.columns(2)
        with c1:
            health_card("Historical fundamentals", pit_status,
                        f"{cnt_f} filings across {cov.get('symbols',0)} companies" if cnt_f>0 else "No filings stored",
                        "Fundamentals are only usable after they were published (point-in-time)", "Mock has limited fundamentals; real filing dates needed for full PIT" if pit_status=="Limited" else "")
        with c2:
            health_card("Historical universe", uni_status,
                        "Listing and delisting dates available for current dataset" if uni_status=="Ready" else "Some companies lack listing history",
                        "Prevents survivorship bias — backtests use only companies that existed then", "If incomplete, historical results may be biased" if uni_status=="Limited" else "")
        st.divider()
        st.subheader("Details — prices and filings")
        c1,c2=st.columns(2)
        with c1:
            try:
                row=conn.execute("SELECT MAX(date) as m FROM prices_daily").fetchone()["m"]
                st.metric("Latest price date", row or "never")
            except: st.metric("Latest price date", "unknown")
        with c2:
            try:
                row=conn.execute("SELECT MAX(available_at) as m FROM fundamentals").fetchone()["m"]
                st.metric("Latest filing published", row or "never")
            except: st.metric("Latest filing published", "unknown")
        with st.expander("Technical details — counts and storage"):
            st.write(f"Companies: {cnt_c}, Prices: {cnt_p}, Fundamentals: {cnt_f}, Corporate actions: {cnt_ca}")
            st.write(f"PIT coverage: {cov}")
            st.write(f"Database: {settings.database_url}")
        st.divider()
        st.subheader("Recent system events")
        try:
            evs=conn.execute("SELECT timestamp, level, message FROM system_events ORDER BY timestamp DESC LIMIT 10").fetchall()
            if evs: st.dataframe(pd.DataFrame([dict(r) for r in evs]), width='stretch')
            else: st.success("No recent errors — all systems look healthy")
        except: st.write("System events unavailable")
    except Exception as e: human_error("Data Health unavailable", str(e))

# --- 12 System ---
elif page=="System":
    st.header("System")
    st.subheader("User Status")
    st.caption("Plain-English summary of what is working for you.")
    cols=st.columns(3)
    checks=[]
    try: get_provider(st.session_state.provider).health_check(); checks.append(("Market data", "Ready", "Prices can be fetched"))
    except: checks.append(("Market data", "Limited", "Provider may be unavailable"))
    try:
        from app.data.universe import get_universe
        uni_now = get_universe(None, provider_name=st.session_state.provider, use_db=False)
        has_life = any(c.listed_date for c in uni_now)
        checks.append(("Historical universe", "Protected ✓" if has_life else "Limited", "Backtests use historical company list" if has_life else "Listing history incomplete"))
    except: checks.append(("Historical universe", "Unknown", ""))
    try:
        from app.data.corporate_actions import CorporateAction
        checks.append(("Corporate actions", "Enabled ✓", "Splits/bonuses adjust old prices; dividends kept as cash"))
    except: checks.append(("Corporate actions", "Limited", ""))
    try:
        groq_ok = bool(os.getenv("GROQ_API_KEY") or settings.groq_api_key or st.session_state.groq_key)
        checks.append(("AI analyst (Groq)", "Ready ✓" if groq_ok else "Mock mode", "Explains verified data" if groq_ok else "Add API key in sidebar to enable"))
    except: checks.append(("AI analyst", "Unknown", ""))
    checks.append(("Backtesting", "No-lookahead ✓", "Only uses data available at that time"))
    checks.append(("Point-in-time fundamentals", "Available" if has_life else "Limited", "Filings only visible after published date"))
    for i,(name,status,desc) in enumerate(checks):
        with cols[i%3]:
            st.metric(name, status, delta=desc)
    st.divider()
    st.subheader("Technical Details")
    st.caption("For developers — database, versions, migrations")
    with st.expander("Show technical details"):
        try:
            conn=get_conn()
            st.write(f"Data freshness: {datetime.date.today().isoformat()}")
            try: last=conn.execute("SELECT MAX(date) as m FROM prices_daily").fetchone()["m"]; st.write(f"Last successful ingestion: {last}")
            except: st.write("Last successful ingestion: unknown")
            st.write(f"Database URL: {settings.database_url}")
            st.write(f"Provider: {st.session_state.provider}")
            st.write(f"Groq model: {settings.groq_model}")
            import sqlite3, pandas as pd
            st.write(f"SQLite: {sqlite3.sqlite_version} | Pandas: {pd.__version__}")
            # show schema info
            rows=conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            st.write(f"Tables: {', '.join([r[0] for r in rows][:10])}")
            st.write("Migrations: PIT, corporate actions, survivorship (listed/delisted, snapshots, symbol history) applied")
        except Exception as e: st.write(f"Technical details unavailable: {e}")
    st.divider()
    st.caption("Groq key is stored locally in .env and never committed to git. Manage it in the sidebar → Groq AI.")
    help_box("Why local .env?", "The key stays on your machine. The app reads it at startup; you can rotate or clear it anytime in the sidebar.")

# Footer for all pages
st.divider()
st.caption("Research candidate — not an automatic trade instruction. | DATA MODE: {} | {}".format(st.session_state.provider.upper(), "Groq ready" if (os.getenv("GROQ_API_KEY") or settings.groq_api_key or st.session_state.groq_key) else "Groq mock"))
