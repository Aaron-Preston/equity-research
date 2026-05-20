"""
Equity Research Terminal — Streamlit Web App
Wraps sector_screener.py, equity_research.py, and thesis_discovery.py
into a clean visual interface.

Install:
    py -m pip install streamlit plotly pandas anthropic requests

Run:
    streamlit run app.py
"""

import os, re, sys, json, time, hashlib
from pathlib import Path

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import requests
import anthropic

# ── Page config (must be first Streamlit call) ────────────────────────────────

st.set_page_config(
    page_title="Equity Research Terminal",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Keys ──────────────────────────────────────────────────────────────────────

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FMP_KEY       = os.environ.get("FMP_API_KEY", "")
FMP_BASE      = "https://financialmodelingprep.com/api/v3"
# ── Cache & Storage ───────────────────────────────────────────────────────────
# Works locally (filesystem) and on Streamlit Cloud (st.session_state fallback)

CACHE_DIR     = Path.home() / ".equity_research_cache"
CACHE_TTL_HRS = 24

def _is_cloud():
    """Detect if running on Streamlit Cloud."""
    return os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("HOME") == "/home/appuser"

# ── Styling ───────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@700;800&display=swap');

/* Global */
html, body, [class*="css"] {
    font-family: 'DM Mono', monospace;
    background-color: #080810;
    color: #e0e0f0;
}

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 2rem 2rem 4rem; max-width: 1400px; }

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #0d0d1a;
    border-right: 1px solid #1a1a2e;
}
[data-testid="stSidebar"] * { font-family: 'DM Mono', monospace; }

/* Inputs */
.stTextInput input, .stSelectbox select, .stNumberInput input {
    background-color: #111120 !important;
    border: 1px solid #1e1e3a !important;
    color: #e0e0f0 !important;
    border-radius: 6px !important;
    font-family: 'DM Mono', monospace !important;
}
.stTextInput input:focus {
    border-color: #00d4aa !important;
    box-shadow: 0 0 0 2px #00d4aa20 !important;
}

/* Buttons */
.stButton > button {
    background-color: #00d4aa !important;
    color: #080810 !important;
    border: none !important;
    border-radius: 6px !important;
    font-family: 'DM Mono', monospace !important;
    font-weight: 700 !important;
    letter-spacing: 0.05em !important;
    padding: 0.5rem 1.5rem !important;
    width: 100%;
}
.stButton > button:hover { opacity: 0.85 !important; }

/* Metrics */
[data-testid="stMetric"] {
    background: #0f0f1e;
    border: 1px solid #1a1a2e;
    border-radius: 8px;
    padding: 1rem;
}
[data-testid="stMetricValue"] {
    font-family: 'DM Mono', monospace !important;
    color: #00d4aa !important;
    font-size: 1.2rem !important;
}
[data-testid="stMetricLabel"] {
    font-family: 'DM Mono', monospace !important;
    color: #6b6b8a !important;
    font-size: 0.7rem !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

/* Expanders */
[data-testid="stExpander"] {
    background: #0f0f1e !important;
    border: 1px solid #1a1a2e !important;
    border-radius: 8px !important;
}

/* Dataframe */
[data-testid="stDataFrame"] { border: 1px solid #1a1a2e; border-radius: 8px; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background-color: #0d0d1a; border-bottom: 1px solid #1a1a2e; }
.stTabs [data-baseweb="tab"] { color: #6b6b8a; font-family: 'DM Mono', monospace; }
.stTabs [aria-selected="true"] { color: #00d4aa !important; border-bottom-color: #00d4aa !important; }

/* Progress */
.stProgress > div > div { background-color: #00d4aa !important; }

/* Alerts */
.stAlert { border-radius: 8px; font-family: 'DM Mono', monospace; }

/* Custom cards */
.company-card {
    background: #0f0f1e;
    border: 1px solid #1a1a2e;
    border-radius: 10px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
}
.company-card:hover { border-color: #00d4aa44; }
.section-label {
    font-size: 0.65rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #6b6b8a;
    margin-bottom: 0.3rem;
}
.conviction-bar {
    height: 6px;
    border-radius: 3px;
    background: linear-gradient(90deg, #00d4aa, #00a888);
    margin-top: 4px;
}
.tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.65rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-right: 4px;
}
.tag-pure { background: #00d4aa22; color: #00d4aa; border: 1px solid #00d4aa44; }
.tag-div  { background: #ffffff11; color: #888; border: 1px solid #333; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="border-bottom: 1px solid #1a1a2e; padding-bottom: 1rem; margin-bottom: 2rem;">
    <span style="font-family: 'Syne', sans-serif; font-size: 1.6rem; font-weight: 800;
                 color: #00d4aa; letter-spacing: -0.02em;">◎ RESEARCH TERMINAL</span>
    <span style="color: #3a3a5a; font-size: 0.75rem; letter-spacing: 0.1em;
                 margin-left: 16px;">AI-POWERED EQUITY INTELLIGENCE</span>
</div>
""", unsafe_allow_html=True)

# ── Key check ─────────────────────────────────────────────────────────────────

if not ANTHROPIC_KEY:
    st.error("**ANTHROPIC_API_KEY not set.** Open a terminal and run: "
             "`[System.Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'sk-ant-...', 'User')`"
             " then restart Streamlit.")
    st.stop()

if not FMP_KEY:
    st.warning("**FMP_API_KEY not set** — financial data will be unavailable. "
               "Get a free key at financialmodelingprep.com")

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_KEY)

def call_claude(client, use_web=True, **kwargs):
    if use_web:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
    for attempt in range(3):
        try:
            return client.messages.create(**kwargs)
        except Exception as e:
            err = str(e)
            if ("429" in err or "rate_limit" in err) and attempt < 2:
                wait = 30 * (attempt + 1)
                st.warning(f"Rate limited — waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded")

def call_claude_no_retry(client, use_web=False, **kwargs):
    """Single attempt — use after deliberate waits so we don't burn tokens on retries."""
    if use_web:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
    return client.messages.create(**kwargs)

def fmt_currency(value, decimals=1):
    if value is None: return "N/A"
    neg = value < 0; av = abs(value)
    if av >= 1e9:   s = f"${av/1e9:.{decimals}f}B"
    elif av >= 1e6: s = f"${av/1e6:.{decimals}f}M"
    elif av >= 1e3: s = f"${av/1e3:.{decimals}f}K"
    else:           s = f"${av:.2f}"
    return f"-{s}" if neg else s

def fmt_pct(value, decimals=1):
    if value is None: return "N/A"
    return f"{value:+.{decimals}f}%"

# ── Cache ─────────────────────────────────────────────────────────────────────

def cache_key(sector, region, limit):
    return hashlib.md5(f"{sector.lower()}|{region}|{limit}".encode()).hexdigest()

def load_cache(sector, region, limit):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{cache_key(sector, region, limit)}.json"
    if not path.exists(): return None
    try:
        data = json.loads(path.read_text())
        if (time.time() - data["saved_at"]) / 3600 > CACHE_TTL_HRS:
            path.unlink(); return None
        return data["companies"]
    except Exception: return None

def save_cache(sector, region, limit, companies):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{cache_key(sector, region, limit)}.json"
    path.write_text(json.dumps({"sector": sector, "region": region,
                                "limit": limit, "saved_at": time.time(),
                                "companies": companies}, indent=2))

# ── Watchlist ─────────────────────────────────────────────────────────────────

WATCHLIST_PATH = CACHE_DIR / "watchlist.json"

def load_watchlist() -> list:
    # On cloud use session state, locally use file
    if _is_cloud():
        return st.session_state.get("watchlist", [])
    CACHE_DIR.mkdir(exist_ok=True)
    if not WATCHLIST_PATH.exists(): return []
    try:
        return json.loads(WATCHLIST_PATH.read_text())
    except Exception: return []

def save_watchlist(watchlist: list):
    if _is_cloud():
        st.session_state["watchlist"] = watchlist
        return
    CACHE_DIR.mkdir(exist_ok=True)
    WATCHLIST_PATH.write_text(json.dumps(watchlist, indent=2))

def add_to_watchlist(ticker: str, name: str, exchange: str,
                     sector: str, fin: dict, notes: str = ""):
    wl = load_watchlist()
    # Update if already exists, add if not
    for item in wl:
        if item["ticker"].upper() == ticker.upper():
            item.update({"name": name, "exchange": exchange, "sector": sector,
                         "fin": fin, "notes": notes,
                         "updated_at": time.strftime("%Y-%m-%d %H:%M")})
            save_watchlist(wl)
            return
    wl.append({"ticker": ticker.upper(), "name": name, "exchange": exchange,
                "sector": sector, "fin": fin, "notes": notes,
                "added_at": time.strftime("%Y-%m-%d %H:%M"),
                "updated_at": time.strftime("%Y-%m-%d %H:%M")})
    save_watchlist(wl)

def remove_from_watchlist(ticker: str):
    wl = load_watchlist()
    wl = [i for i in wl if i["ticker"].upper() != ticker.upper()]
    save_watchlist(wl)

# ── FMP financials ────────────────────────────────────────────────────────────

def fetch_financials(fmp_ticker):
    fin = {}
    if not FMP_KEY: return fin

    def get(ep, params=None):
        p = {"apikey": FMP_KEY}
        if params: p.update(params)
        try:
            r = requests.get(f"{FMP_BASE}/{ep}/{fmp_ticker}", params=p, timeout=8)
            d = r.json()
            if not r.ok or isinstance(d, dict) and "Error" in str(d): return None
            if isinstance(d, list) and not d: return None
            return d
        except Exception: return None

    # Company profile — name, description, location, exchange, sector, employees
    d = get("profile")
    if d:
        p = d[0]
        fin.update({
            "company_name":    p.get("companyName"),
            "description":     p.get("description"),
            "sector":          p.get("sector"),
            "industry":        p.get("industry"),
            "exchange":        p.get("exchangeShortName") or p.get("exchange"),
            "country":         p.get("country"),
            "city":            p.get("city"),
            "state":           p.get("state"),
            "website":         p.get("website"),
            "ceo":             p.get("ceo"),
            "employees":       p.get("fullTimeEmployees"),
            "ipo_date":        p.get("ipoDate"),
            "currency":        p.get("currency"),
            "is_etf":          p.get("isEtf"),
            "is_actively_trading": p.get("isActivelyTrading"),
        })

    d = get("quote")
    if d:
        q = d[0]
        fin.update({"price": q.get("price"), "market_cap": q.get("marketCap"),
                    "change_pct": q.get("changesPercentage"),
                    "52w_high": q.get("yearHigh"), "52w_low": q.get("yearLow"),
                    "shares_out": q.get("sharesOutstanding"),
                    "pe_ratio": q.get("pe"), "eps": q.get("eps")})

    d = get("income-statement", {"limit": 2})
    if d:
        s = d[0]
        fin.update({"revenue": s.get("revenue"), "gross_profit": s.get("grossProfit"),
                    "gross_margin": (s["grossProfit"]/s["revenue"]*100
                                     if s.get("revenue") and s.get("grossProfit") else None),
                    "ebitda": s.get("ebitda"), "net_income": s.get("netIncome"),
                    "rd_expense": s.get("researchAndDevelopmentExpenses"),
                    "report_date": s.get("date","")[:7]})
        if len(d) > 1:
            prev = d[1].get("revenue") or 0; curr = s.get("revenue") or 0
            if prev: fin["revenue_growth"] = (curr-prev)/abs(prev)*100

    d = get("balance-sheet-statement", {"limit": 2})
    if d:
        b = d[0]
        total_debt = b.get("totalDebt") or 0
        cash_val   = b.get("cashAndCashEquivalents") or 0
        fin.update({
            "cash":              cash_val,
            "cash_date":         b.get("date","")[:7],
            "total_debt":        total_debt,
            "long_term_debt":    b.get("longTermDebt"),
            "short_term_debt":   b.get("shortTermDebt") or b.get("shortTermDebtCurrent"),
            "net_debt":          total_debt - cash_val,
            "equity":            b.get("totalStockholdersEquity"),
            "total_assets":      b.get("totalAssets"),
            "total_liabilities": b.get("totalLiabilities"),
        })
        if len(d) > 1:
            cur = b.get("commonStock") or 0; prev = d[1].get("commonStock") or 0
            if prev > 0: fin["dilution_yoy_pct"] = (cur-prev)/prev*100

    d = get("cash-flow-statement", {"limit": 1})
    if d:
        c = d[0]
        fin.update({
            "operating_cf":    c.get("operatingCashFlow"),
            "fcf":             c.get("freeCashFlow"),
            "capex":           c.get("capitalExpenditure"),
            "stock_based_comp":c.get("stockBasedCompensation"),
            "shares_issued":   c.get("commonStockIssued"),
        })
        ocf = c.get("operatingCashFlow")
        if ocf and ocf < 0 and fin.get("cash"):
            mb = abs(ocf)/12
            fin["monthly_burn"]  = mb
            fin["runway_months"] = fin["cash"]/mb if mb > 0 else None
            # Runway end date
            import datetime
            months = fin["runway_months"]
            if months:
                end = datetime.date.today() + datetime.timedelta(days=months*30)
                fin["runway_end"] = end.strftime("%b %Y")

    d = get("key-metrics-ttm")
    if d:
        m = d[0]
        fin.update({"ev_ebitda":     m.get("enterpriseValueOverEBITDATTM"),
                    "ps_ratio":      m.get("priceToSalesRatioTTM"),
                    "debt_equity":   m.get("debtToEquityTTM"),
                    "current_ratio": m.get("currentRatioTTM"),
                    "ev":            m.get("enterpriseValueTTM")})

    d = get("insider-roaster-statistic")
    if d:
        ins = d[0] if isinstance(d, list) else d
        fin.update({"insider_ownership":       ins.get("ownedByInsiders"),
                    "institutional_ownership": ins.get("ownedByInstitutions")})

    # Short interest
    d = get("short-float")
    if d and isinstance(d, list) and d:
        s = d[0]
        fin.update({"short_float_pct":  s.get("shortFloatPercent") or s.get("shortPercentOfFloat"),
                    "short_ratio":      s.get("shortRatio"),
                    "days_to_cover":    s.get("daysToCover")})

    return fin

# ── AI functions ──────────────────────────────────────────────────────────────

def classify_sector(sector):
    client = get_client()
    try:
        r = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=10,
            messages=[{"role": "user", "content":
                f'Is "{sector}" a well-known investment sector with 20+ public companies '
                f'a financial analyst knows from memory? Reply only: YES, NO, or UNSURE'}])
        a = r.content[0].text.strip().upper()
        return a != "YES"
    except Exception: return True

def identify_companies(sector, region, limit, use_web):
    client = get_client()
    region_map = {
        "US only": "Focus on US-listed companies (NYSE, NASDAQ) only.",
        "UK only": "Focus on UK-listed companies (LSE/AIM) only.",
        "Global":  "Include ALL major global exchanges: NYSE, NASDAQ, LSE, AIM, TSX, ASX, Euronext, TSE, HKEX.",
        "US + UK": "Include US (NYSE/NASDAQ) and UK (LSE/AIM) listed companies.",
    }
    knowledge_note = ("Be thorough — include smaller, less-covered, newer public companies "
                      "alongside large caps. Do not just list the obvious names." if not use_web else "")

    prompt = f"""Identify publicly listed companies in: {sector}
{region_map.get(region, '')}
{knowledge_note}
Return ONLY a raw JSON array. Each object:
  "ticker": primary exchange ticker
  "name": full company name
  "exchange": NYSE/NASDAQ/LSE/AIM/TSX/ASX/TSE/HKEX etc
  "country": 2-letter ISO code
  "fmp_ticker": FMP-formatted ticker (US as-is, UK add .L, Canada add .TO, Australia add .AX)
  "description": one sentence on relevance to {sector}
  "pure_play": true/false
Up to {limit} companies, pure-plays first. No ETFs. No private companies. JSON only."""

    kwargs = dict(model="claude-sonnet-4-5", max_tokens=2000,
                  messages=[{"role": "user", "content": prompt}])
    response = call_claude(client, use_web=use_web, **kwargs)
    raw = "\n".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\[[\s\S]+\]", raw)
    if not match: return []
    try: return json.loads(match.group())[:limit]
    except Exception: return []

def get_company_brief(ticker, name, sector, fin):
    client = get_client()
    runway = fin.get("runway_months")
    dil    = fin.get("dilution_yoy_pct")

    fin_ctx = f"""Market cap: {fmt_currency(fin.get('market_cap'))} | Revenue: {fmt_currency(fin.get('revenue'))}
EBITDA: {fmt_currency(fin.get('ebitda'))} | Net income: {fmt_currency(fin.get('net_income'))}
Cash: {fmt_currency(fin.get('cash'))} | Debt: {fmt_currency(fin.get('total_debt'))}
Runway: {f"{runway:.0f} months" if runway else "unknown"} | Dilution YoY: {f"{dil:+.1f}%" if dil else "unknown"}
Insider ownership: {f"{fin['insider_ownership']*100:.1f}%" if fin.get('insider_ownership') else "unknown"}"""

    data_note = ("No structured financial data — rely on web search for all figures." 
                 if not fin.get("market_cap") else "")

    prompt = f"""Analyse {name} ({ticker}) in the {sector} sector.
{data_note}
Financials: {fin_ctx}

Search for: contracts, partnerships, grants, dilution events, insider activity, catalysts.

Respond in EXACTLY this format:
THESIS: [2 sentences]
CONTRACTS: [notable deals or 'None identified']
DILUTION: [dilution risk assessment]
INSIDER: [ownership and recent transactions]
RISK: [single biggest risk in one sentence]
CONVICTION: [X/10 — one sentence rationale]"""

    response = call_claude(client, use_web=True,
                           model="claude-sonnet-4-5", max_tokens=500,
                           messages=[{"role": "user", "content": prompt}])
    return "\n".join(b.text for b in response.content if b.type == "text")

def get_stock_brief(ticker, market, criteria, filing_text, fin):
    client = get_client()
    runway = fin.get("runway_months")
    dil    = fin.get("dilution_yoy_pct")

    fin_ctx = f"""Price: {fmt_currency(fin.get('price'))} | Mkt Cap: {fmt_currency(fin.get('market_cap'))} | EV: {fmt_currency(fin.get('ev'))}
Revenue TTM: {fmt_currency(fin.get('revenue'))} | Growth: {fmt_pct(fin.get('revenue_growth'))} | Gross Margin: {fmt_pct(fin.get('gross_margin'))}
EBITDA: {fmt_currency(fin.get('ebitda'))} | Net Income: {fmt_currency(fin.get('net_income'))} | FCF: {fmt_currency(fin.get('fcf'))} | Capex: {fmt_currency(fin.get('capex'))}
Cash: {fmt_currency(fin.get('cash'))} (as of {fin.get('cash_date','unknown')}) | Total Debt: {"$0" if fin.get('total_debt') == 0 else fmt_currency(fin.get('total_debt'))} | LT Debt: {fmt_currency(fin.get('long_term_debt'))} | ST Debt: {fmt_currency(fin.get('short_term_debt'))}
Net Debt: {fmt_currency(fin.get('net_debt'))} | D/E: {f"{fin['debt_equity']:.2f}" if fin.get('debt_equity') is not None else 'N/A'}
Runway: {f"{runway:.0f} months (est. end {fin.get('runway_end','unknown')})" if runway else "N/A"} | Monthly Burn: {fmt_currency(fin.get('monthly_burn'))}
Shares Out: {f"{fin['shares_out']/1e6:.1f}M" if fin.get('shares_out') else 'N/A'} | Dilution YoY: {f"{dil:+.1f}%" if dil is not None else "N/A"} | SBC: {fmt_currency(fin.get('stock_based_comp'))}
Insider: {f"{fin['insider_ownership']*100:.1f}%" if fin.get('insider_ownership') else 'N/A'} | Institutional: {f"{fin['institutional_ownership']*100:.1f}%" if fin.get('institutional_ownership') else 'N/A'}
Short Float: {f"{fin['short_float_pct']*100:.1f}%" if fin.get('short_float_pct') else 'N/A'} | Days to Cover: {f"{fin['days_to_cover']:.1f}" if fin.get('days_to_cover') else 'N/A'}
R&D: {fmt_currency(fin.get('rd_expense'))} | P/E: {f"{fin['pe_ratio']:.1f}x" if fin.get('pe_ratio') else 'N/A'} | EV/EBITDA: {f"{fin['ev_ebitda']:.1f}x" if fin.get('ev_ebitda') else 'N/A'}"""

    filing_block = (f"FILING DATA (use as primary source):\n{filing_text[:8000]}"
                    if filing_text else "No filing data — rely on web search.")

    criteria_prompts = {
        "Thesis":      "THESIS: What they do and the investment case in 2-3 sentences.",
        "Financials":  "FINANCIALS: Key metrics. Search for most recent earnings if filing is old.",
        "Market":      "MARKET: Search for the specific addressable market for this company's product or technology. Include: (1) current market size with source, (2) projected size in 5 and 10 years with CAGR, (3) key growth drivers, (4) where this company sits in the value chain. For biotech/pharma: include the specific indication TAM, patient population size, comparable drug pricing, and regulatory pathway context. For pre-revenue companies: flag if market size estimates are speculative and note what assumptions they depend on. Use specific dollar figures where findable.",
        "Risk":        "RISK: Top 3 material risks including any market-specific risks.",
        "Insider":     "INSIDER: Ownership % and all notable recent transactions with names and amounts.",
        "Competitive": "COMPETITIVE: Key competitors and differentiation.",
        "Contracts":   f"CONTRACTS: Search specifically for '{ticker} contract', '{ticker} partnership', '{ticker} agreement 2025 2026'. Name counterparties.",
        "Dilution":    "DILUTION: Share issuance history, ATM facilities, warrant overhang with exercise prices.",
    }
    criteria_block = "\n".join(criteria_prompts[c] for c in criteria if c in criteria_prompts)

    prompt = f"""You are a senior equity research analyst.
Company: {ticker} | Market: {market}
{filing_block}
Structured financials: {fin_ctx}

Provide research brief — search the web to supplement and find post-filing developments.

CRITICAL: You MUST use EXACTLY these section headers in ALL CAPS followed by a colon.
Do not write prose paragraphs. Do not include any preamble or explanation.
Start your response immediately with the first header.

{criteria_block}
CONVICTION: X/10 — one sentence. Penalise for runway <12mo, heavy dilution, no revenue traction.

Example format:
THESIS: Company does X and Y...
FINANCIALS: Revenue was $Z...
CONVICTION: 5/10 — strong technology but..."""

    response = call_claude(client, use_web=True,
                           model="claude-sonnet-4-5", max_tokens=1200,
                           messages=[{"role": "user", "content": prompt}])
    return "\n".join(b.text for b in response.content if b.type == "text")

# ── Chart builders ────────────────────────────────────────────────────────────

def make_comparison_chart(df, col, title, color="#00d4aa"):
    fig = go.Figure(go.Bar(
        x=df["ticker"], y=df[col],
        marker_color=color,
        marker_line_color="rgba(0,212,170,0.27)",
        marker_line_width=1,
        text=[fmt_currency(v) if col != "conviction" else f"{v}/10" for v in df[col]],
        textposition="outside",
        textfont=dict(color="#e0e0f0", size=11),
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(color="#e0e0f0", size=13,
                                         family="DM Mono"), x=0),
        paper_bgcolor="#0f0f1e", plot_bgcolor="#0f0f1e",
        font=dict(color="#6b6b8a", family="DM Mono"),
        xaxis=dict(gridcolor="#1a1a2e", tickfont=dict(color="#e0e0f0")),
        yaxis=dict(gridcolor="#1a1a2e", tickfont=dict(color="#6b6b8a")),
        margin=dict(l=0, r=0, t=40, b=0),
        height=280,
    )
    return fig

def make_runway_gauge(months):
    color = "#52b788" if months >= 24 else "#f4a261" if months >= 12 else "#ff4d6d"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=months,
        number={"suffix": " mo", "font": {"color": color, "family": "DM Mono", "size": 28}},
        gauge={"axis": {"range": [0, 60], "tickcolor": "#3a3a5a",
                        "tickfont": {"color": "#6b6b8a", "family": "DM Mono"}},
               "bar": {"color": color},
               "bgcolor": "#0f0f1e",
               "bordercolor": "#1a1a2e",
               "steps": [{"range": [0, 12], "color": "#1a0812"},
                          {"range": [12, 24], "color": "#1a1508"},
                          {"range": [24, 60], "color": "#081a12"}]},
    ))
    fig.update_layout(paper_bgcolor="#0f0f1e", font_color="#6b6b8a",
                      height=200, margin=dict(l=20, r=20, t=20, b=20))
    return fig

# ── Brief parser ──────────────────────────────────────────────────────────────

def parse_brief(raw):
    sections = {}
    keys = ["THESIS","MARKET","CONTRACTS","DILUTION","INSIDER","RISK","CONVICTION",
            "FINANCIALS","COMPETITIVE"]
    for key in keys:
        m = re.search(rf"{key}:\s*(.+?)(?=\n[A-Z]+:|$)", raw, re.DOTALL)
        if m: sections[key] = m.group(1).strip()

    # If no structured sections found, try to extract conviction score
    # and put the whole response under THESIS
    if not sections:
        sections["THESIS"] = raw.strip()
        # Still try to find a conviction score anywhere in the text
        m = re.search(r"(\d+)\s*/\s*10", raw)
        if m:
            # Find the sentence containing the score
            sentences = raw.split(".")
            for s in sentences:
                if "/10" in s or "out of 10" in s.lower():
                    sections["CONVICTION"] = s.strip() + "."
                    break

    return sections

def extract_conviction(sections, raw=None):
    """Extract conviction score from sections or raw text as fallback."""
    # Try CONVICTION section first
    text = sections.get("CONVICTION","")
    m = re.search(r"(\d+)\s*/\s*10", text)
    if m: return int(m.group(1)), text

    # Fall back to searching entire raw response
    if raw:
        m = re.search(r"(\d+)\s*/\s*10", raw)
        if m:
            score = int(m.group(1))
            # Find surrounding sentence as rationale
            sentences = raw.replace("\n"," ").split(".")
            for s in sentences:
                if "/10" in s:
                    return score, s.strip() + "."
            return score, ""
    return None, ""

# ── Render functions ──────────────────────────────────────────────────────────

def render_brief_sections(sections, skip=None):
    skip = skip or []
    icons = {"THESIS": "◎", "FINANCIALS": "▦", "CONTRACTS": "◆",
             "DILUTION": "▲", "INSIDER": "◈", "RISK": "⚠",
             "MARKET": "◉", "COMPETITIVE": "⬡", "CONVICTION": "★"}
    colours = {"THESIS": "#00d4aa", "FINANCIALS": "#52b788", "CONTRACTS": "#52b788",
               "DILUTION": "#f4a261", "INSIDER": "#74b9ff", "RISK": "#ff4d6d",
               "MARKET": "#c77dff", "COMPETITIVE": "#e0e0f0", "CONVICTION": "#00d4aa"}

    for key, text in sections.items():
        if key in skip or not text: continue
        if key == "CONVICTION":
            score, rationale = extract_conviction(sections)
            if score:
                rest = rationale or re.sub(r"\d+\s*/\s*10\s*[-—]?\s*", "", text).strip()
                st.markdown(f"""
<div style="margin: 0.8rem 0;">
<div class="section-label">{icons.get(key,'·')} {key}</div>
<div style="display:flex; align-items:center; gap:12px; margin-bottom:6px;">
    <span style="font-size:1.4rem; font-weight:700; color:{colours[key]};">{score}/10</span>
    <div style="flex:1; height:8px; background:#1a1a2e; border-radius:4px; overflow:hidden;">
        <div style="width:{score*10}%; height:100%; background:linear-gradient(90deg,#00d4aa,#00a888);
                    border-radius:4px;"></div>
    </div>
</div>
<div style="color:#9999bb; font-size:0.82rem; line-height:1.6;">{clean_text(rest)}</div>
</div>""", unsafe_allow_html=True)
            continue

        colour = colours.get(key, "#e0e0f0")
        cleaned = clean_text(text)
        st.markdown(f"""
<div style="margin: 0.8rem 0;">
<div class="section-label">{icons.get(key,'·')} {key}</div>
<div style="color:#c8c8e0; font-size:0.84rem; line-height:1.8;
            border-left: 2px solid {colour}44; padding-left: 10px;">
{cleaned}
</div></div>""", unsafe_allow_html=True)

def clean_text(text: str) -> str:
    """Clean AI response text — remove bad spacing, fix markdown, prevent mid-sentence breaks."""
    import html
    t = html.escape(text)
    # Remove spaces before punctuation: "end-2026 ." → "end-2026."
    t = re.sub(r"\s+([,\.\;\:\!\?])", r"\1", t)
    # Remove citation brackets [1], [2]
    t = re.sub(r"\s*\[\d+\]", "", t)
    # Convert **bold** to HTML
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong style='color:#e0e0f0;'>\1</strong>", t)
    # Mark real paragraph breaks (double newlines) before collapsing single ones
    t = re.sub(r"\n{2,}", "||PARA||", t)
    # Collapse single newlines into spaces — prevents mid-sentence line breaks
    t = re.sub(r"\n", " ", t)
    # Restore paragraph breaks
    t = re.sub(r"\|\|PARA\|\|", "<br><br>", t)
    # Clean multiple spaces
    t = re.sub(r"  +", " ", t)
    # Format numbered list items at paragraph start
    t = re.sub(r"<br><br>(\d+)[\.\)]\s+", r"<br><span style='color:#00d4aa;font-weight:600;'>\1.</span>&nbsp;", t)
    t = re.sub(r"^(\d+)[\.\)]\s+", r"<span style='color:#00d4aa;font-weight:600;'>\1.</span>&nbsp;", t)
    return t.strip()


def render_metric(label, value, good=None, bad=None, suffix=""):
    if value is None or value == "N/A":
        colour = "#6b6b8a"
    elif good and isinstance(value, (int, float)) and value >= good:
        colour = "#52b788"
    elif bad and isinstance(value, (int, float)) and value <= bad:
        colour = "#ff4d6d"
    else:
        colour = "#f4a261"
    display = fmt_currency(value) if isinstance(value, (int, float)) else str(value)
    st.markdown(f"""
<div style="background:#0f0f1e; border:1px solid #1a1a2e; border-radius:8px;
            padding:0.8rem 1rem; text-align:center;">
<div style="font-size:0.6rem; letter-spacing:0.1em; text-transform:uppercase;
            color:#6b6b8a; margin-bottom:4px;">{label}</div>
<div style="font-size:1rem; font-weight:600; color:{colour};">{display}{suffix}</div>
</div>""", unsafe_allow_html=True)

# ── Sidebar nav ───────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
<div style="font-size:0.6rem; letter-spacing:0.15em; text-transform:uppercase;
            color:#3a3a5a; margin-bottom:1rem;">Navigation</div>
""", unsafe_allow_html=True)

    page = st.radio("", ["◎  Sector Screener", "▦  Stock Deep Dive",
                          "⬡  Thesis Discovery", "★  Watchlist"],
                    label_visibility="collapsed")

    st.markdown("---")
    st.markdown("""
<div style="font-size:0.6rem; letter-spacing:0.1em; text-transform:uppercase; color:#3a3a5a;">
API Status</div>""", unsafe_allow_html=True)

    anthropic_ok = bool(ANTHROPIC_KEY)
    fmp_ok       = bool(FMP_KEY)
    st.markdown(f"""
<div style="font-size:0.75rem; margin-top:0.5rem;">
{'🟢' if anthropic_ok else '🔴'} Anthropic API<br>
{'🟢' if fmp_ok else '🟡'} Financial Modeling Prep
</div>""", unsafe_allow_html=True)

    if fmp_ok:
        st.markdown("""
<div style="font-size:0.6rem; color:#3a3a5a; margin-top:0.5rem;">
Tip: run with --refresh flag to bypass cache
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — SECTOR SCREENER
# ══════════════════════════════════════════════════════════════════════════════

if page == "◎  Sector Screener":
    st.markdown("""
<div style="font-family:'Syne',sans-serif; font-size:1.2rem; font-weight:700;
            color:#e0e0f0; margin-bottom:1.5rem; letter-spacing:-0.01em;">
Sector Screener
<span style="font-family:'DM Mono',monospace; font-size:0.7rem; font-weight:400;
             color:#3a3a5a; margin-left:12px;">IDENTIFY · SCREEN · ANALYSE</span>
</div>""", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns([3, 1.5, 1, 1])
    with col1:
        sector = st.text_input("Sector / Theme",
                               placeholder="e.g. helium-3, neuromorphic chips, solid state batteries",
                               label_visibility="visible")
    with col2:
        region = st.selectbox("Region", ["US + UK", "US only", "UK only", "Global"])
    with col3:
        limit = st.number_input("Max Companies", min_value=3, max_value=30, value=10)
    with col4:
        refresh = st.checkbox("Refresh cache", value=False)

    run_brief = st.checkbox("Include AI brief per company (uses more API credit)", value=False)

    run_btn = st.button("Run Sector Screen", use_container_width=True)

    if run_btn and sector:
        st.markdown("---")

        # Step 1 — identify
        with st.status("Step 1 — Identifying companies...") as s1:
            cached = None if refresh else load_cache(sector, region, limit)
            if cached:
                companies = cached
                s1.update(label=f"Step 1 — Loaded {len(companies)} companies from cache ✓", state="complete")
            else:
                s1.write("Classifying sector familiarity...")
                use_web = classify_sector(sector)
                method  = "web search" if use_web else "training knowledge"
                s1.write(f"Using {method} to identify companies...")
                companies = identify_companies(sector, region, limit, use_web)
                if companies:
                    save_cache(sector, region, limit, companies)
                    s1.update(label=f"Step 1 — {len(companies)} companies identified via {method} ✓",
                              state="complete")
                else:
                    s1.update(label="Step 1 — No companies found", state="error")
                    st.error("No companies found. Try a broader search term.")
                    st.stop()

        # Step 2 — financials
        fin_map = {}
        if FMP_KEY:
            with st.status("Step 2 — Fetching financials...") as s2:
                prog = st.progress(0)
                for i, co in enumerate(companies):
                    ticker     = co.get("ticker","")
                    fmp_ticker = co.get("fmp_ticker") or ticker
                    s2.write(f"Fetching {ticker}...")
                    fin_map[ticker] = fetch_financials(fmp_ticker)
                    prog.progress((i+1)/len(companies))
                    time.sleep(0.3)
                s2.update(label="Step 2 — Financials fetched ✓", state="complete")
        else:
            st.info("FMP key not set — showing AI analysis only (no structured financials)")
            for co in companies:
                fin_map[co.get("ticker","")] = {}

        # Summary table
        st.markdown(f"""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin: 1.5rem 0 0.5rem;">Overview Table</div>""",
                    unsafe_allow_html=True)

        rows = []
        for co in companies:
            t   = co.get("ticker","")
            fin = fin_map.get(t, {})
            rows.append({
                "Ticker":    t,
                "Name":      co.get("name","")[:30],
                "Exchange":  co.get("exchange",""),
                "Pure Play": "✓" if co.get("pure_play") else "",
                "Mkt Cap":   fmt_currency(fin.get("market_cap")),
                "Price":     fmt_currency(fin.get("price"), ),
                "Revenue":   fmt_currency(fin.get("revenue")),
                "Cash":      fmt_currency(fin.get("cash")),
                "Debt":      fmt_currency(fin.get("total_debt")),
                "Runway":    f"{fin['runway_months']:.0f}mo" if fin.get("runway_months") else "N/A",
                "EBITDA":    fmt_currency(fin.get("ebitda")),
                "Dil YoY":   fmt_pct(fin.get("dilution_yoy_pct")),
                "Rev Growth":fmt_pct(fin.get("revenue_growth")),
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True,
                     column_config={"Pure Play": st.column_config.TextColumn(width="small")})

        # Quick-save to watchlist
        st.markdown(f"""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin: 1rem 0 0.3rem;">Save to Watchlist</div>""",
                    unsafe_allow_html=True)
        wl_cols = st.columns(min(len(companies), 6))
        for idx, co in enumerate(companies[:6]):
            t   = co.get("ticker","?")
            fin = fin_map.get(t, {})
            with wl_cols[idx % 6]:
                if st.button(f"+ {t}", key=f"wl_sector_{t}",
                             help=f"Add {co.get('name',t)} to watchlist"):
                    add_to_watchlist(t, co.get("name",""), co.get("exchange",""),
                                     sector, fin)
                    st.success(f"{t} added ✓")

        # Charts
        chart_data = []
        for co in companies:
            t   = co.get("ticker","")
            fin = fin_map.get(t, {})
            if fin.get("market_cap"):
                chart_data.append({"ticker": t, "market_cap": fin["market_cap"],
                                   "cash": fin.get("cash"), "revenue": fin.get("revenue"),
                                   "ebitda": fin.get("ebitda")})

        if chart_data:
            cdf = pd.DataFrame(chart_data)
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(make_comparison_chart(cdf, "market_cap", "Market Cap"),
                                use_container_width=True)
            with c2:
                if cdf["cash"].notna().any():
                    st.plotly_chart(make_comparison_chart(cdf, "cash", "Cash Position", "#52b788"),
                                   use_container_width=True)

        # Step 3 — AI briefs
        if run_brief:
            st.markdown("---")
            st.markdown(f"""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin-bottom:1rem;">Company Briefs</div>""",
                        unsafe_allow_html=True)

            delay = 8
            for i, co in enumerate(companies):
                ticker = co.get("ticker","?")
                name   = co.get("name","")
                fin    = fin_map.get(ticker, {})
                pure   = co.get("pure_play", False)
                desc   = co.get("description","")

                with st.expander(f"{'★ ' if pure else ''}{name}  ({ticker})  {co.get('exchange','')}"):
                    # Metrics row
                    m1,m2,m3,m4,m5,m6 = st.columns(6)
                    with m1: render_metric("Price", fin.get("price"))
                    with m2: render_metric("Mkt Cap", fin.get("market_cap"))
                    with m3: render_metric("Cash", fin.get("cash"),
                                           good=100e6, bad=20e6)
                    with m4: render_metric("Revenue", fin.get("revenue"))
                    with m5: render_metric("EBITDA", fin.get("ebitda"))
                    with m6:
                        ru = fin.get("runway_months")
                        render_metric("Runway", f"{ru:.0f} mo" if ru else None,
                                      good=24, bad=12)

                    if desc:
                        st.markdown(f"<div style='color:#6b6b8a; font-size:0.8rem; "
                                    f"margin:0.8rem 0;'>{desc}</div>",
                                    unsafe_allow_html=True)

                    with st.spinner(f"Analysing {ticker}..."):
                        try:
                            raw    = get_company_brief(ticker, name, sector, fin)
                            parsed = parse_brief(raw)
                            render_brief_sections(parsed)
                            delay = max(8, delay - 2)
                        except Exception as e:
                            if "429" in str(e) or "rate_limit" in str(e):
                                delay = min(delay * 2, 90)
                                st.warning(f"Rate limited — next requests will wait {delay}s")
                            else:
                                st.error(f"Analysis failed: {str(e)[:100]}")

                    if i < len(companies) - 1:
                        time.sleep(delay)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — STOCK DEEP DIVE
# ══════════════════════════════════════════════════════════════════════════════

elif page == "▦  Stock Deep Dive":
    st.markdown("""
<div style="font-family:'Syne',sans-serif; font-size:1.2rem; font-weight:700;
            color:#e0e0f0; margin-bottom:1.5rem;">
Stock Deep Dive
<span style="font-family:'DM Mono',monospace; font-size:0.7rem; font-weight:400;
             color:#3a3a5a; margin-left:12px;">FILINGS · FINANCIALS · AI ANALYSIS</span>
</div>""", unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        ticker_input = st.text_input("Ticker Symbol",
                                     placeholder="e.g. IONQ, ENS.L, SYA.AX, NLST")
    with col2:
        market = st.selectbox("Market", ["Auto-detect", "US (NYSE/NASDAQ)", "UK (LSE/AIM)",
                                          "Canada (TSX)", "Australia (ASX)", "OTC", "Japan (TSE)"])

    criteria = st.multiselect("Analysis Criteria",
                              ["Thesis","Financials","Market","Risk","Insider",
                               "Competitive","Contracts","Dilution"],
                              default=["Thesis","Financials","Market","Risk","Insider"])

    run_dive = st.button("Run Deep Dive", use_container_width=True)

    if run_dive and ticker_input:
        ticker = ticker_input.upper().strip()

        # Detect FMP ticker
        market_map = {
            "UK (LSE/AIM)":    lambda t: t if t.endswith(".L")  else f"{t}.L",
            "Canada (TSX)":    lambda t: t if t.endswith(".TO") else f"{t}.TO",
            "Australia (ASX)": lambda t: t if t.endswith(".AX") else f"{t}.AX",
        }
        fmp_ticker = market_map.get(market, lambda t: t)(ticker)

        st.markdown("---")

        # Financials
        fin = {}
        if FMP_KEY:
            with st.status("Fetching financials from FMP...") as sf:
                fin = fetch_financials(fmp_ticker)
                fields = sum(1 for v in fin.values() if v is not None)
                if fields > 3:
                    sf.update(label=f"Financials fetched — {fields} data points ✓", state="complete")
                else:
                    sf.update(label="Limited FMP data — AI will rely on web search", state="complete")

        # Filing
        filing_text = None
        if market in ("Auto-detect", "US (NYSE/NASDAQ)", "OTC"):
            with st.status("Fetching SEC filing...") as sfi:
                try:
                    from equity_research import get_us_filing
                    filing_text, filing_label = get_us_filing(ticker)
                    if filing_text:
                        sfi.update(label=f"Filing fetched: {filing_label[:60]} ✓", state="complete")
                    else:
                        sfi.update(label=f"Filing not found — {filing_label[:60]}", state="complete")
                except Exception:
                    # equity_research.py not importable — skip filing
                    sfi.update(label="Filing fetch skipped — web search will be used", state="complete")

        # Company profile card
        if fin.get("company_name") or fin.get("description"):
            location_parts = [p for p in [fin.get("city"), fin.get("state"), fin.get("country")] if p]
            location = ", ".join(location_parts) if location_parts else "N/A"
            exchange_str = fin.get("exchange") or market
            sector_str   = " · ".join(p for p in [fin.get("sector"), fin.get("industry")] if p) or "N/A"
            employees    = f"{int(fin['employees']):,}" if fin.get("employees") else "N/A"
            ipo          = fin.get("ipo_date","")[:4] if fin.get("ipo_date") else "N/A"
            currency     = fin.get("currency","")
            website      = fin.get("website","")
            ceo          = fin.get("ceo","N/A")
            desc         = fin.get("description","")
            # Truncate description to 3 sentences
            sentences = desc.split(". ")
            short_desc = ". ".join(sentences[:3]) + ("." if len(sentences) > 3 else "")

            st.markdown(f"""
<div style="background:#0d0d1a; border:1px solid #1a1a2e; border-radius:10px;
            padding:1.2rem 1.5rem; margin-bottom:1.5rem;">
  <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.8rem;">
    <div>
      <span style="font-family:'Syne',sans-serif; font-size:1.1rem; font-weight:700;
                   color:#e0e0f0;">{fin.get('company_name', ticker)}</span>
      <span style="font-size:0.75rem; color:#00d4aa; margin-left:10px;
                   font-family:'DM Mono',monospace;">{ticker}</span>
      <span style="font-size:0.7rem; color:#3a3a5a; margin-left:8px;">{exchange_str} · {currency}</span>
    </div>
    {f'<a href="{website}" target="_blank" style="font-size:0.7rem; color:#00d4aa; text-decoration:none; opacity:0.7;">{website.replace("https://","").replace("http://","").rstrip("/")}</a>' if website else ''}
  </div>
  <div style="display:flex; gap:20px; margin-bottom:0.8rem; flex-wrap:wrap;">
    <div><span style="font-size:0.58rem; text-transform:uppercase; letter-spacing:0.1em;
                      color:#3a3a5a;">Sector</span>
         <div style="font-size:0.75rem; color:#9999bb; margin-top:2px;">{sector_str}</div></div>
    <div><span style="font-size:0.58rem; text-transform:uppercase; letter-spacing:0.1em;
                      color:#3a3a5a;">Location</span>
         <div style="font-size:0.75rem; color:#9999bb; margin-top:2px;">{location}</div></div>
    <div><span style="font-size:0.58rem; text-transform:uppercase; letter-spacing:0.1em;
                      color:#3a3a5a;">CEO</span>
         <div style="font-size:0.75rem; color:#9999bb; margin-top:2px;">{ceo}</div></div>
    <div><span style="font-size:0.58rem; text-transform:uppercase; letter-spacing:0.1em;
                      color:#3a3a5a;">Employees</span>
         <div style="font-size:0.75rem; color:#9999bb; margin-top:2px;">{employees}</div></div>
    <div><span style="font-size:0.58rem; text-transform:uppercase; letter-spacing:0.1em;
                      color:#3a3a5a;">IPO Year</span>
         <div style="font-size:0.75rem; color:#9999bb; margin-top:2px;">{ipo}</div></div>
    <div><span style="font-size:0.58rem; text-transform:uppercase; letter-spacing:0.1em;
                      color:#3a3a5a;">Listed On</span>
         <div style="font-size:0.75rem; color:#9999bb; margin-top:2px;">{exchange_str}</div></div>
  </div>
  {f'<div style="font-size:0.78rem; color:#6b6b8a; line-height:1.7; border-top:1px solid #1a1a2e; padding-top:0.8rem;">{short_desc}</div>' if short_desc else ''}
</div>""", unsafe_allow_html=True)

        # Metrics header
        if fin.get("price") or fin.get("market_cap"):
            st.markdown(f"""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin: 1rem 0 0.5rem;">Live Data
{f'<span style="color:#3a3a5a; margin-left:8px;">· as of {fin["cash_date"]}</span>' if fin.get("cash_date") else ""}
</div>""", unsafe_allow_html=True)

            # Row 1 — Pricing
            st.markdown(f"<div style='font-size:0.58rem; color:#3a3a5a; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:4px;'>Pricing</div>", unsafe_allow_html=True)
            m1,m2,m3,m4,m5,m6,m7 = st.columns(7)
            with m1: render_metric("Price", fin.get("price"))
            with m2: render_metric("Mkt Cap", fin.get("market_cap"))
            with m3: render_metric("EV", fin.get("ev"))
            with m4: render_metric("52w High", fin.get("52w_high"))
            with m5: render_metric("52w Low", fin.get("52w_low"))
            with m6: render_metric("P/E", f"{fin['pe_ratio']:.1f}x" if fin.get("pe_ratio") and fin["pe_ratio"] > 0 else None)
            with m7: render_metric("EV/EBITDA", f"{fin['ev_ebitda']:.1f}x" if fin.get("ev_ebitda") and fin["ev_ebitda"] > 0 else None)

            st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)

            # Row 2 — Profitability
            st.markdown(f"<div style='font-size:0.58rem; color:#3a3a5a; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:4px;'>Profitability</div>", unsafe_allow_html=True)
            m8,m9,m10,m11,m12,m13,m14 = st.columns(7)
            with m8:  render_metric("Revenue", fin.get("revenue"))
            with m9:  render_metric("Rev Growth", fmt_pct(fin.get("revenue_growth")))
            with m10: render_metric("Gross Margin", fmt_pct(fin.get("gross_margin")))
            with m11: render_metric("EBITDA", fin.get("ebitda"))
            with m12: render_metric("Net Income", fin.get("net_income"))
            with m13: render_metric("FCF", fin.get("fcf"))
            with m14: render_metric("Capex", fin.get("capex"))

            st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)

            # Row 3 — Balance sheet & debt
            st.markdown(f"<div style='font-size:0.58rem; color:#3a3a5a; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:4px;'>Balance Sheet & Debt</div>", unsafe_allow_html=True)
            m15,m16,m17,m18,m19,m20,m21 = st.columns(7)
            with m15: render_metric("Cash", fin.get("cash"), good=100e6, bad=20e6)
            with m16:
                debt = fin.get("total_debt")
                # Explicitly show $0 if zero
                render_metric("Total Debt",
                              "$0" if debt == 0 else debt,
                              bad=50e6 if debt else None)
            with m17: render_metric("LT Debt", fin.get("long_term_debt"))
            with m18: render_metric("ST Debt", fin.get("short_term_debt"))
            with m19: render_metric("Net Debt", fin.get("net_debt"))
            with m20: render_metric("D/E Ratio", f"{fin['debt_equity']:.2f}" if fin.get("debt_equity") is not None else None)
            with m21: render_metric("Current Ratio", f"{fin['current_ratio']:.2f}" if fin.get("current_ratio") else None)

            st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)

            # Row 4 — Cash burn & runway
            st.markdown(f"<div style='font-size:0.58rem; color:#3a3a5a; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:4px;'>Cash Burn & Runway</div>", unsafe_allow_html=True)
            m22,m23,m24,m25,m26,m27,m28 = st.columns(7)
            with m22: render_metric("Operating CF", fin.get("operating_cf"))
            with m23: render_metric("Monthly Burn", fin.get("monthly_burn"))
            with m24:
                ru = fin.get("runway_months")
                render_metric("Runway", f"{ru:.0f} mo" if ru else None,
                              good=24, bad=12)
            with m25: render_metric("Runway End", fin.get("runway_end"))
            with m26: render_metric("SBC", fin.get("stock_based_comp"))
            with m27: render_metric("R&D Spend", fin.get("rd_expense"))
            with m28: render_metric("Shares Issued", fin.get("shares_issued"))

            st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)

            # Row 5 — Ownership & short interest
            st.markdown(f"<div style='font-size:0.58rem; color:#3a3a5a; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:4px;'>Ownership & Short Interest</div>", unsafe_allow_html=True)
            m29,m30,m31,m32,m33,m34,m35 = st.columns(7)
            with m29: render_metric("Shares Out", f"{fin['shares_out']/1e6:.1f}M" if fin.get("shares_out") else None)
            with m30: render_metric("Dilution YoY", fmt_pct(fin.get("dilution_yoy_pct")))
            with m31: render_metric("Insider Own", f"{fin['insider_ownership']*100:.1f}%" if fin.get("insider_ownership") else None)
            with m32: render_metric("Institutional", f"{fin['institutional_ownership']*100:.1f}%" if fin.get("institutional_ownership") else None)
            with m33: render_metric("Short Float", f"{fin['short_float_pct']*100:.1f}%" if fin.get("short_float_pct") else None)
            with m34: render_metric("Short Ratio", f"{fin['short_ratio']:.1f}" if fin.get("short_ratio") else None)
            with m35: render_metric("Days to Cover", f"{fin['days_to_cover']:.1f}" if fin.get("days_to_cover") else None)

            # Runway gauge
            if fin.get("runway_months"):
                st.plotly_chart(make_runway_gauge(fin["runway_months"]),
                                use_container_width=False)

        # AI analysis
        st.markdown("---")
        st.markdown("""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin-bottom:0.5rem;">AI Analysis</div>""",
                    unsafe_allow_html=True)

        with st.spinner("Running AI analysis with web search..."):
            try:
                raw    = get_stock_brief(ticker, market, criteria, filing_text, fin)
                parsed = parse_brief(raw)

                if not parsed:
                    st.warning("Parser couldn't find section headers — showing full response:")
                    st.text(raw)
                else:
                    score, rationale = extract_conviction(parsed, raw)
                    if score:
                        rest = re.sub(r"\d+\s*/\s*10\s*[-—]?\s*", "", rationale).strip() if rationale else ""
                        st.markdown(f"""
<div style="background:linear-gradient(135deg,#0f1a15,#0f0f1e);
            border:1px solid #00d4aa44; border-radius:10px;
            padding:1rem 1.5rem; margin-bottom:1rem; display:flex;
            align-items:center; gap:16px;">
<span style="font-size:2rem; font-weight:800; color:#00d4aa;
             font-family:'Syne',sans-serif;">{score}/10</span>
<div style="flex:1;">
<div style="height:10px; background:#1a1a2e; border-radius:5px; overflow:hidden; margin-bottom:6px;">
<div style="width:{score*10}%; height:100%;
            background:linear-gradient(90deg,#00d4aa,#00a888);
            border-radius:5px;"></div></div>
<div style="font-size:0.65rem; color:#6b6b8a; letter-spacing:0.06em;">CONVICTION SCORE</div>
{f'<div style="font-size:0.78rem; color:#9999bb; margin-top:4px; line-height:1.5;">{rest}</div>' if rest else ''}
</div></div>""", unsafe_allow_html=True)

                    render_brief_sections(parsed, skip=["CONVICTION"])

                    # Save to watchlist
                    st.markdown("---")
                    col_save, col_note = st.columns([1, 3])
                    with col_save:
                        if st.button("★  Save to Watchlist", key=f"wl_dive_{ticker}"):
                            add_to_watchlist(
                                ticker,
                                fin.get("company_name", ticker),
                                fin.get("exchange", market),
                                "Manual — Stock Deep Dive",
                                fin,
                            )
                            st.success(f"{ticker} saved to watchlist ✓")

            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err:
                    st.error("**Rate limited** — you've hit the Anthropic API request limit.")
                    st.info("Wait 15-30 minutes and try again. Check your tier at console.anthropic.com → Usage. The financials above are still valid — only the AI brief is affected.")
                elif "401" in err or "authentication" in err:
                    st.error("**API key invalid** — check your ANTHROPIC_API_KEY in your run.bat file.")
                elif "529" in err or "overloaded" in err:
                    st.error("**Anthropic servers busy** — try again in a few minutes.")
                else:
                    st.error(f"**Analysis failed:** {err[:300]}")
                    st.info("The financials fetched above are still valid. Only the AI brief failed.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — THESIS DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

elif page == "⬡  Thesis Discovery":
    st.markdown("""
<div style="font-family:'Syne',sans-serif; font-size:1.2rem; font-weight:700;
            color:#e0e0f0; margin-bottom:0.5rem;">
Thesis Discovery
<span style="font-family:'DM Mono',monospace; font-size:0.7rem; font-weight:400;
             color:#3a3a5a; margin-left:12px;">SUBSTACK · ARXIV · YC · VC BLOGS</span>
</div>""", unsafe_allow_html=True)

    # ── Mode selector ─────────────────────────────────────────────────────────
    st.markdown("""
<div style="font-size:0.65rem; letter-spacing:0.1em; text-transform:uppercase;
            color:#3a3a5a; margin-bottom:0.5rem;">Discovery Mode</div>""",
                unsafe_allow_html=True)

    mode = st.radio("", ["🔭  Proactive Scan — surface what's emerging right now, no input needed",
                          "🎯  Guided Scan — I have a broad area in mind"],
                    label_visibility="collapsed")

    proactive = mode.startswith("🔭")

    st.markdown("---")

    if proactive:
        # Proactive mode UI
        st.markdown("""
<div style="background:#0d1a0d; border:1px solid #52b78833; border-radius:8px;
            padding:1rem 1.2rem; margin-bottom:1rem;">
<div style="font-size:0.7rem; color:#52b788; letter-spacing:0.08em;
            text-transform:uppercase; margin-bottom:4px;">Proactive Scan</div>
<div style="font-size:0.82rem; color:#9999bb; line-height:1.6;">
Sweeps Substack, arXiv, Y Combinator, VC blogs, DARPA/DOE grants, and tech media
to surface sectors gaining unusual traction in the last 30-60 days —
themes you haven't searched for, before they become mainstream narratives.
</div></div>""", unsafe_allow_html=True)

        col1, col2 = st.columns([1, 1])
        with col1:
            top_n = st.number_input("Themes to surface", min_value=3, max_value=10, value=5)
        with col2:
            deep_dive_n = st.slider("Deep dive top N", 0, 3, 1)

        focus_hint = st.text_input("Optional focus hint",
                                    placeholder="e.g. 'exclude biotech' or 'weight towards hardware'  — leave blank for fully open",
                                    label_visibility="visible")

        run_btn = st.button("🔭  Start Proactive Scan", use_container_width=True)
        area      = None
        depth_key = "open"

        open_sweep_prompt = f"""You are a senior technology and investment analyst running a proactive intelligence sweep.

Identify 3-5 investment themes gaining UNUSUAL momentum RIGHT NOW — last 30-60 days — that are NOT yet mainstream narratives. Exclude obvious themes like AI, semiconductors, EVs, cloud computing.

Focus on: technologies moving from academic/military to commercial for the first time, commodities gaining strategic importance, regulatory changes creating new investable opportunities, sectors where multiple independent smart investors are suddenly paying attention.
{f"Focus hint: {focus_hint}" if focus_hint else ""}

Search specifically: Substack newsletters changing topic focus, arXiv paper volume spikes, YC batch themes new vs previous batch, a16z/Lux Capital/Founders Fund writing about something for the FIRST TIME, DARPA/DOE/ARIA grant programmes announced in last 90 days, patent filing clusters.

For each theme: note the SPECIFIC signal, when it appeared, why it's genuinely new. Be concise but precise."""

    else:
        # Guided mode UI
        col1, col2, col3 = st.columns([3, 1.5, 1])
        with col1:
            area = st.text_input("Broad Area",
                                 placeholder="e.g. deep tech, energy transition, biotech, defence tech")
        with col2:
            depth_sel = st.selectbox("Depth", ["Broad (area + adjacencies)",
                                                "Focused (area only)"])
            depth_key = "broad" if "Broad" in depth_sel else "focused"
        with col3:
            top_n = st.number_input("Themes to surface", min_value=3, max_value=10, value=5)

        deep_dive_n = st.slider("Deep dive top N themes", 0, 3, 1)
        run_btn     = st.button("🎯  Discover Themes", use_container_width=True)
        focus_hint  = ""

        depth_instructions = {
            "focused": f"Focus tightly on '{area}' and immediate adjacencies only.",
            "broad":   f"Start with '{area}' but include adjacent and cross-disciplinary themes that intersect with it.",
        }

        guided_sweep_prompt = f"""You are a technology and investment trend analyst.
Identify 3-5 emerging investment themes gaining momentum RIGHT NOW — last 1-3 months.
{depth_instructions.get(depth_key,'')}

Search: Substack newsletters, arXiv preprints, Y Combinator batches, a16z/Sequoia/Lux Capital blog posts, DARPA/DOE grant announcements, MIT Tech Review, Wired, Hacker News.
Look for: newsletter clustering on new themes, arXiv paper spikes, new VC-backed companies, government grants, technology moving from academic to commercial.
Be specific about sources and timing. Note what makes each signal genuinely new."""

    # ── Run ───────────────────────────────────────────────────────────────────

    if run_btn and (proactive or area):
        sweep_prompt = open_sweep_prompt if proactive else guided_sweep_prompt

        st.markdown("---")

        # Step 1 — Sweep using Haiku (separate rate limit pool, supports web search)
        with st.status("Sweeping sources for signals..." +
                       (" (proactive mode)" if proactive else "")) as ss:
            client = get_client()
            try:
                response    = call_claude(client, use_web=True,
                                          model="claude-haiku-4-5-20251001",
                                          max_tokens=1200,
                                          messages=[{"role":"user","content":sweep_prompt}])
                raw_signals = "\n".join(b.text for b in response.content if b.type=="text")
                # Trim to avoid token overflow in structure step
                raw_signals = raw_signals[:2000]
                ss.update(label="Sources swept ✓", state="complete")
            except Exception as e:
                ss.update(label=f"Sweep failed: {str(e)[:60]}", state="error")
                st.error(f"Sweep failed: {str(e)[:200]}")
                st.stop()

        # Wait for Haiku rate limit window to reset
        wait_box = st.empty()
        for i in range(15, 0, -5):
            wait_box.info(f"⏳ Pausing {i}s between steps...")
            time.sleep(5)
        wait_box.empty()

        # Step 2 — Structure
        with st.status(f"Structuring top {top_n} themes...") as st2:

            novelty_note = """
Prioritise genuine novelty above all else.
A theme new in 3 independent sources THIS MONTH ranks higher than a well-known theme.
Penalise anything mainstream for more than 6 months.""" if proactive else ""

            structure_prompt = f"""Based on this research, identify and rank the top {top_n} emerging investment themes. {novelty_note}

RESEARCH:
{raw_signals[:4000]}

Return ONLY a raw JSON array. Each object:
  "rank": integer 1-{top_n}
  "theme": short compelling name (3-6 words)
  "sector_query": exact search term for stock screener
  "signal_score": 1-10
  "novelty_score": 1-10 (10=new this month, 1=well-known for years)
  "momentum": accelerating/emerging/building/maturing
  "stage": "very early"/"early"/"mid"/"late"
  "sources": list of 2-3 specific sources
  "why_now": 2 sentences on what changed in last 1-3 months
  "investable": 2 sentences on investable angle and which companies benefit
  "risks": 1 sentence bear case
  "time_horizon": e.g. "6-18 months" / "2-5 years" / "5-10 years"
  "tags": list of 2-3 tags
  "first_signal": one sentence — the specific signal that put this on your radar

Rank by novelty_score x signal_score. JSON array only, no other text."""

            try:
                resp2  = call_claude_no_retry(client, use_web=False,
                                     model="claude-haiku-4-5-20251001", max_tokens=2500,
                                     messages=[{"role":"user","content":structure_prompt}])
                raw2   = "\n".join(b.text for b in resp2.content if b.type=="text")
                match  = re.search(r"\[[\s\S]+\]", raw2)
                themes = json.loads(match.group()) if match else []
                st2.update(label=f"{len(themes)} themes structured ✓", state="complete")
            except Exception as e:
                st2.update(label=f"Structuring failed: {str(e)[:60]}", state="error")
                st.stop()

        if not themes:
            st.error("No themes identified. Try again or use a different area.")
            st.stop()

        # ── Summary banner ────────────────────────────────────────────────────
        scan_label = "Proactive Open Scan" if proactive else f"Guided Scan — {area}"
        st.markdown(f"""
<div style="background:#0d0d1a; border:1px solid #1a1a2e; border-radius:8px;
            padding:0.8rem 1.2rem; margin-bottom:1.5rem; display:flex;
            justify-content:space-between; align-items:center;">
<div>
<span style="font-size:0.6rem; letter-spacing:0.12em; text-transform:uppercase;
             color:#3a3a5a;">Scan complete — </span>
<span style="font-size:0.8rem; color:#e0e0f0;">{scan_label}</span>
</div>
<div style="font-size:0.75rem; color:#00d4aa;">{len(themes)} themes surfaced</div>
</div>""", unsafe_allow_html=True)

        # ── Novelty vs signal scatter (proactive mode) ────────────────────────
        if proactive:
            scatter_data = []
            for t in themes:
                if t.get("novelty_score") and t.get("signal_score"):
                    scatter_data.append({
                        "theme": t.get("theme","")[:25],
                        "novelty": t.get("novelty_score",5),
                        "signal": t.get("signal_score",5),
                        "stage": t.get("stage","early"),
                    })
            if scatter_data:
                sdf = pd.DataFrame(scatter_data)
                fig = go.Figure(go.Scatter(
                    x=sdf["novelty"], y=sdf["signal"],
                    mode="markers+text",
                    text=sdf["theme"],
                    textposition="top center",
                    textfont=dict(color="#e0e0f0", size=10, family="DM Mono"),
                    marker=dict(size=14, color="#00d4aa",
                                line=dict(color="rgba(0,212,170,0.27)", width=1)),
                ))
                fig.add_shape(type="rect", x0=7, y0=7, x1=10, y1=10,
                              fillcolor="rgba(0,212,170,0.03)", line=dict(color="rgba(0,212,170,0.2)", dash="dot"))
                fig.add_annotation(x=8.5, y=9.5, text="Sweet spot",
                                   font=dict(color="rgba(0,212,170,0.53)", size=9, family="DM Mono"),
                                   showarrow=False)
                fig.update_layout(
                    title=dict(text="Novelty vs Signal Strength — top-right = most interesting",
                               font=dict(color="#6b6b8a", size=11, family="DM Mono"), x=0),
                    xaxis=dict(title="Novelty Score", gridcolor="#1a1a2e",
                               tickfont=dict(color="#6b6b8a"), range=[0,11]),
                    yaxis=dict(title="Signal Score", gridcolor="#1a1a2e",
                               tickfont=dict(color="#6b6b8a"), range=[0,11]),
                    paper_bgcolor="#0f0f1e", plot_bgcolor="#0f0f1e",
                    font=dict(color="#6b6b8a", family="DM Mono"),
                    height=350, margin=dict(l=0,r=0,t=40,b=0),
                )
                st.plotly_chart(fig, use_container_width=True)

        # ── Theme cards ───────────────────────────────────────────────────────
        st.markdown(f"""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin: 1rem 0 0.5rem;">Ranked Themes</div>""",
                    unsafe_allow_html=True)

        stage_colours = {"very early": "#c77dff", "early": "#00d4aa",
                         "mid": "#f4a261", "late": "#6b6b8a"}
        mom_icons     = {"accelerating": "⚡", "emerging": "◎",
                         "building": "▲", "maturing": "─"}

        for i, theme in enumerate(themes):
            score    = theme.get("signal_score", 5)
            novelty  = theme.get("novelty_score", 5)
            stage    = theme.get("stage","").lower()
            momentum = theme.get("momentum","").lower()
            sc       = stage_colours.get(stage, "#e0e0f0")
            mi       = mom_icons.get(momentum, "·")
            query    = theme.get("sector_query","")
            tags     = theme.get("tags",[])
            first_sig= theme.get("first_signal","")
            do_deep  = i < deep_dive_n

            with st.expander(
                f"#{theme.get('rank','?')}  {theme.get('theme','')}  "
                f"  Signal {score}/10  {'·  Novelty ' + str(novelty) + '/10' if proactive else ''}"):

                col_a, col_b = st.columns([3, 1])
                with col_a:
                    # Stage / momentum / horizon tags
                    st.markdown(f"""
<div style="display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap;">
<span style="background:{sc}22; color:{sc}; border:1px solid {sc}44;
             padding:2px 8px; border-radius:4px; font-size:0.6rem;
             text-transform:uppercase; letter-spacing:0.06em;">{stage}</span>
<span style="background:#ffffff11; color:#888; border:1px solid #333;
             padding:2px 8px; border-radius:4px; font-size:0.6rem;">{mi} {momentum}</span>
<span style="background:#ffffff11; color:#888; border:1px solid #333;
             padding:2px 8px; border-radius:4px; font-size:0.6rem;">
⏱ {theme.get('time_horizon','')}</span>
{''.join(f'<span style="background:#ffffff08;color:#666;padding:2px 8px;border-radius:4px;font-size:0.6rem;">#{t}</span>' for t in tags)}
</div>
<div style="height:6px; background:#1a1a2e; border-radius:3px; margin-bottom:12px; overflow:hidden;">
<div style="width:{score*10}%; height:100%;
            background:linear-gradient(90deg,{sc},{sc}88); border-radius:3px;"></div>
</div>""", unsafe_allow_html=True)

                    # First signal (proactive mode highlight)
                    if proactive and first_sig:
                        st.markdown(f"""
<div style="background:#0d1520; border:1px solid #74b9ff33; border-radius:6px;
            padding:8px 12px; margin-bottom:10px;">
<div style="font-size:0.58rem; letter-spacing:0.1em; text-transform:uppercase;
            color:#74b9ff88; margin-bottom:3px;">What put this on the radar</div>
<div style="font-size:0.8rem; color:#9bb8d4; line-height:1.5;">{first_sig}</div>
</div>""", unsafe_allow_html=True)

                with col_b:
                    sources = theme.get("sources",[])
                    if sources:
                        st.markdown(f"""
<div style="font-size:0.6rem; color:#3a3a5a; text-transform:uppercase;
            letter-spacing:0.08em; margin-bottom:4px;">Signals found in</div>
<div style="font-size:0.72rem; color:#6b6b8a; line-height:1.8;">
{"<br>".join(f"· {s}" for s in sources[:3])}</div>""", unsafe_allow_html=True)

                # Why now
                if theme.get("why_now"):
                    st.markdown(f"""
<div class="section-label">Why Now</div>
<div style="color:#c8c8e0; font-size:0.82rem; line-height:1.8;
            border-left:2px solid #00d4aa44; padding-left:10px; margin-bottom:10px;">
{clean_text(theme['why_now'])}</div>""", unsafe_allow_html=True)

                if theme.get("investable"):
                    st.markdown(f"""
<div class="section-label">Investable Angle</div>
<div style="color:#c8c8e0; font-size:0.82rem; line-height:1.8;
            border-left:2px solid #52b78844; padding-left:10px; margin-bottom:10px;">
{clean_text(theme['investable'])}</div>""", unsafe_allow_html=True)

                if theme.get("risks"):
                    st.markdown(f"""
<div class="section-label">Bear Case</div>
<div style="color:#ff6b6b; font-size:0.8rem; line-height:1.6;
            border-left:2px solid #ff4d6d44; padding-left:10px; margin-bottom:10px;">
{clean_text(theme['risks'])}</div>""", unsafe_allow_html=True)

                # Deep dive
                if do_deep:
                    with st.spinner(f"Deep diving {theme.get('theme','')}..."):
                        time.sleep(3)
                        try:
                            dd_prompt = f"""Deep dive on this emerging investment theme: {theme.get('theme')}
Thesis: {theme.get('investable','')}
{"This was surfaced via proactive scan — be especially thorough about finding niche/early signals." if proactive else ""}

Search for:
1. 2-3 prominent people championing this theme RIGHT NOW (name them, note their background)
2. Specific Substack posts, essays, or threads in the last 60 days worth reading (title + author)
3. Government/regulatory announcements accelerating this in the last 90 days
4. Private companies or recent YC/Antler/Entrepreneur First batches as directional signals
5. The single most compelling data point or development for this thesis
6. Bear case in one sentence

Format exactly:
CHAMPIONS: [names, roles, why they matter]
READING: [specific posts/essays with authors and approximate dates]
CATALYSTS: [government/regulatory/macro developments]
PRIVATE_SIGNALS: [early companies or accelerator cohorts]
KEY_DATAPOINT: [most compelling evidence]
BEAR_CASE: [one sentence]"""

                            dd_resp = call_claude(client, use_web=True,
                                                  model="claude-sonnet-4-5", max_tokens=500,
                                                  messages=[{"role":"user","content":dd_prompt}])
                            dd_raw  = "\n".join(b.text for b in dd_resp.content if b.type=="text")
                            dd_sect = parse_brief(dd_raw)

                            dd_labels = {
                                "CHAMPIONS":       ("Who to Follow",    "#74b9ff"),
                                "READING":         ("Worth Reading",     "#74b9ff"),
                                "CATALYSTS":       ("Catalysts",         "#f4a261"),
                                "PRIVATE_SIGNALS": ("Private Signals",   "#9999bb"),
                                "KEY_DATAPOINT":   ("Key Data Point",    "#52b788"),
                                "BEAR_CASE":       ("Bear Case",         "#ff4d6d"),
                            }
                            st.markdown("""<div style='border-top:1px solid #1a1a2e;
                                margin:12px 0;'></div>
<div style="font-size:0.6rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#c77dff; margin-bottom:8px;">Deep Dive</div>""",
                                        unsafe_allow_html=True)
                            for key, (label, colour) in dd_labels.items():
                                text = dd_sect.get(key,"")
                                if text and text.lower() not in ("none","n/a","none identified"):
                                    st.markdown(f"""
<div class="section-label">{label}</div>
<div style="color:#c8c8e0; font-size:0.8rem; line-height:1.8;
            border-left:2px solid {colour}44; padding-left:10px; margin-bottom:8px;">
{clean_text(text)}</div>""", unsafe_allow_html=True)
                        except Exception as e:
                            st.warning(f"Deep dive failed: {str(e)[:80]}")

                # Screener shortcut
                if query:
                    st.markdown(f"""
<div style="background:#0d1a15; border:1px solid #00d4aa22; border-radius:6px;
            padding:8px 12px; margin-top:8px; font-size:0.75rem; color:#6b6b8a;">
Run in Sector Screener →
<span style="color:#00d4aa; font-family:'DM Mono',monospace;">"{query}"</span>
</div>""", unsafe_allow_html=True)

                if do_deep and i < deep_dive_n - 1:
                    time.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — WATCHLIST
# ══════════════════════════════════════════════════════════════════════════════

elif page == "★  Watchlist":
    st.markdown("""
<div style="font-family:'Syne',sans-serif; font-size:1.2rem; font-weight:700;
            color:#e0e0f0; margin-bottom:1.5rem;">
Watchlist
<span style="font-family:'DM Mono',monospace; font-size:0.7rem; font-weight:400;
             color:#3a3a5a; margin-left:12px;">SAVED COMPANIES · QUICK ACCESS</span>
</div>""", unsafe_allow_html=True)

    watchlist = load_watchlist()

    if not watchlist:
        st.markdown("""
<div style="text-align:center; padding:60px 20px; color:#3a3a5a;">
<div style="font-size:2rem; margin-bottom:12px;">★</div>
<div style="font-size:0.85rem; line-height:1.8;">
No companies saved yet.<br>
Use the <strong style="color:#6b6b8a;">+ TICKER</strong> buttons in the Sector Screener<br>
or the <strong style="color:#6b6b8a;">★ Save to Watchlist</strong> button in Stock Deep Dive.
</div></div>""", unsafe_allow_html=True)
    else:
        # Summary count and clear button
        col_hdr, col_clear = st.columns([4, 1])
        with col_hdr:
            st.markdown(f"""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin-bottom:1rem;">{len(watchlist)} companies saved</div>""",
                        unsafe_allow_html=True)
        with col_clear:
            if st.button("Clear All", key="wl_clear"):
                save_watchlist([])
                st.rerun()

        # Group by sector
        sectors = {}
        for item in watchlist:
            s = item.get("sector", "Unsorted")
            sectors.setdefault(s, []).append(item)

        for sector_name, items in sectors.items():
            st.markdown(f"""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#00d4aa; margin: 1.5rem 0 0.5rem;">◎ {sector_name}</div>""",
                        unsafe_allow_html=True)

            for item in items:
                ticker   = item.get("ticker","?")
                name     = item.get("name", ticker)
                exchange = item.get("exchange","")
                added    = item.get("added_at","")
                fin      = item.get("fin", {})

                col_info, col_metrics, col_actions = st.columns([3, 5, 1])

                with col_info:
                    st.markdown(f"""
<div style="background:#0f0f1e; border:1px solid #1a1a2e; border-radius:8px;
            padding:0.8rem 1rem; height:100%;">
<div style="font-size:0.85rem; font-weight:600; color:#e0e0f0;">{name}</div>
<div style="font-size:0.7rem; color:#00d4aa; margin-top:2px;">{ticker}</div>
<div style="font-size:0.65rem; color:#3a3a5a; margin-top:2px;">{exchange}</div>
<div style="font-size:0.6rem; color:#3a3a5a; margin-top:4px;">Added {added}</div>
</div>""", unsafe_allow_html=True)

                with col_metrics:
                    m1,m2,m3,m4,m5 = st.columns(5)
                    with m1: render_metric("Price",   fin.get("price"))
                    with m2: render_metric("Mkt Cap", fin.get("market_cap"))
                    with m3: render_metric("Cash",    fin.get("cash"), good=100e6, bad=20e6)
                    with m4: render_metric("Revenue", fin.get("revenue"))
                    with m5:
                        ru = fin.get("runway_months")
                        render_metric("Runway", f"{ru:.0f}mo" if ru else None,
                                      good=24, bad=12)

                with col_actions:
                    # Deep dive button — sets session state to navigate
                    if st.button("🔍", key=f"wl_dive_{ticker}",
                                 help=f"Deep dive {ticker}"):
                        st.session_state["dive_ticker"] = ticker
                        st.session_state["dive_market"] = exchange
                        st.rerun()
                    if st.button("✕", key=f"wl_remove_{ticker}",
                                 help=f"Remove {ticker}"):
                        remove_from_watchlist(ticker)
                        st.rerun()

                st.markdown("<div style='margin-bottom:8px;'></div>",
                            unsafe_allow_html=True)

        # Watchlist comparison charts
        if len(watchlist) > 1:
            st.markdown("---")
            st.markdown("""
<div style="font-size:0.65rem; letter-spacing:0.12em; text-transform:uppercase;
            color:#3a3a5a; margin-bottom:0.5rem;">Watchlist Comparison</div>""",
                        unsafe_allow_html=True)
            chart_data = [{"ticker": i["ticker"],
                           "market_cap": i.get("fin",{}).get("market_cap"),
                           "cash":       i.get("fin",{}).get("cash"),
                           "revenue":    i.get("fin",{}).get("revenue")}
                          for i in watchlist if i.get("fin",{}).get("market_cap")]
            if chart_data:
                cdf = pd.DataFrame(chart_data)
                c1, c2 = st.columns(2)
                with c1:
                    st.plotly_chart(make_comparison_chart(cdf, "market_cap", "Market Cap"),
                                    use_container_width=True)
                with c2:
                    if cdf["cash"].notna().any():
                        st.plotly_chart(make_comparison_chart(cdf, "cash",
                                                               "Cash Position", "#52b788"),
                                        use_container_width=True)

# ── Handle watchlist deep dive navigation ─────────────────────────────────────
# If user clicked 🔍 on watchlist, auto-populate stock deep dive
if "dive_ticker" in st.session_state and page == "▦  Stock Deep Dive":
    st.session_state.pop("dive_ticker", None)
    st.session_state.pop("dive_market", None)

