#!/usr/bin/env python3
"""
Sector Screener Terminal — AI-powered global equity research
Finds public companies in any sector with comprehensive financials + AI analysis

Requirements:
    py -m pip install anthropic requests

API Keys needed:
    ANTHROPIC_API_KEY  — console.anthropic.com
    FMP_API_KEY        — financialmodelingprep.com (free tier works)

Set in PowerShell:
    $env:ANTHROPIC_API_KEY="sk-ant-..."
    $env:FMP_API_KEY="your-fmp-key"

Usage:
    py sector_screener.py
    py sector_screener.py --sector "quantum computing"
    py sector_screener.py --sector "helium-3" --region global --limit 20
    py sector_screener.py --sector "semiconductors" --no-brief --limit 30
"""

import os, sys, re, json, time, textwrap, argparse, hashlib
from pathlib import Path
import requests
import anthropic

# ── Keys ──────────────────────────────────────────────────────────────────────

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FMP_KEY       = os.environ.get("FMP_API_KEY", "")
FMP_BASE      = "https://financialmodelingprep.com/api/v3"

# ── Cache ─────────────────────────────────────────────────────────────────────

CACHE_DIR     = Path.home() / ".equity_research_cache"
CACHE_TTL_HRS = 24  # company lists cached for 24 hours

def cache_key(sector: str, region: str, limit: int) -> str:
    raw = f"{sector.lower().strip()}|{region}|{limit}"
    return hashlib.md5(raw.encode()).hexdigest()

def load_cache(sector: str, region: str, limit: int):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{cache_key(sector, region, limit)}.json"
    if not path.exists(): return None
    try:
        data = json.loads(path.read_text())
        age_hrs = (time.time() - data["saved_at"]) / 3600
        if age_hrs > CACHE_TTL_HRS:
            path.unlink()
            return None
        return data["companies"]
    except Exception:
        return None

def save_cache(sector: str, region: str, limit: int, companies: list):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{cache_key(sector, region, limit)}.json"
    try:
        path.write_text(json.dumps({
            "sector": sector, "region": region, "limit": limit,
            "saved_at": time.time(), "companies": companies
        }, indent=2))
    except Exception:
        pass

def clear_cache():
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
    print(f"  {GREEN}Cache cleared.{RESET}")

# ── Colours ───────────────────────────────────────────────────────────────────

RESET   = "\033[0m";  BOLD    = "\033[1m"
CYAN    = "\033[96m"; GREEN   = "\033[92m"
YELLOW  = "\033[93m"; RED     = "\033[91m"
WHITE   = "\033[97m"; GREY    = "\033[90m"
BLUE    = "\033[94m"

WIDTH = 76

# ── Terminal helpers ──────────────────────────────────────────────────────────

def divider(char="─"): print(f"  {GREY}{char * WIDTH}{RESET}")
def header(text):
    print(f"\n  {GREY}{'=' * WIDTH}{RESET}")
    print(f"  {BOLD}{WHITE}  {text}{RESET}")
    print(f"  {GREY}{'=' * WIDTH}{RESET}")
def subheader(text, colour=CYAN):
    print(f"\n  {colour}{BOLD}> {text}{RESET}"); divider()
def status(step, total, text):
    print(f"  {GREY}[{step}/{total}]{RESET} {text}", end=" ", flush=True)
def ok(text="done"):  print(f"{GREEN}{text}{RESET}")
def na():             return f"{GREY}N/A{RESET}"

def fmt_large(value, prefix="$", decimals=2):
    if value is None: return na()
    neg = value < 0
    av  = abs(value)
    if av >= 1e9:   s = f"{av/1e9:.{decimals}f}B"
    elif av >= 1e6: s = f"{av/1e6:.{decimals}f}M"
    elif av >= 1e3: s = f"{av/1e3:.{decimals}f}K"
    else:           s = f"{av:.{decimals}f}"
    return f"{prefix}{'-' if neg else ''}{s}"

def fmt_pct(value, decimals=1):
    if value is None: return na()
    c = GREEN if value >= 0 else RED
    return f"{c}{value:+.{decimals}f}%{RESET}"

def colour_cash(v):
    if v is None: return na()
    s = fmt_large(v)
    return f"{GREEN}{s}{RESET}" if v >= 100e6 else f"{YELLOW}{s}{RESET}" if v >= 20e6 else f"{RED}{s}{RESET}"

def colour_debt(v):
    if v is None: return na()
    s = fmt_large(v)
    return f"{GREEN}{s}{RESET}" if v == 0 else f"{YELLOW}{s}{RESET}" if v < 50e6 else f"{RED}{s}{RESET}"

def colour_runway(m):
    if m is None: return na()
    s = f"{m:.0f} mo"
    return f"{GREEN}{s}{RESET}" if m >= 24 else f"{YELLOW}{s}{RESET}" if m >= 12 else f"{RED}{s}{RESET}"

def colour_ebitda(v):
    if v is None: return na()
    s = fmt_large(v)
    return f"{GREEN}{s}{RESET}" if v >= 0 else f"{RED}{s}{RESET}"

# ── Error classifier — turns raw errors into human explanations ───────────────

def classify_error(err_str: str) -> tuple[str, str]:
    """Returns (short_label, explanation) for a given error string."""
    e = err_str.lower()
    if "429" in e or "rate_limit" in e:
        return (
            "RATE LIMITED",
            "Too many API requests in a short window. The free Anthropic tier allows "
            "~5 requests/min. Waiting and retrying automatically."
        )
    if "401" in e or "authentication" in e or "api_key" in e:
        return (
            "AUTH ERROR",
            "Your ANTHROPIC_API_KEY is invalid or expired. "
            "Check it at console.anthropic.com and reset with: $env:ANTHROPIC_API_KEY='sk-ant-...'"
        )
    if "404" in e or "not_found" in e:
        return (
            "MODEL NOT FOUND",
            "The AI model name is unrecognised. This usually means the model was deprecated. "
            "The script will need updating — let Claude know."
        )
    if "timeout" in e or "timed out" in e:
        return (
            "TIMEOUT",
            "The request took too long. This can happen with slow internet or overloaded servers. "
            "Try again in a moment."
        )
    if "connection" in e or "network" in e:
        return (
            "CONNECTION ERROR",
            "Could not reach the API. Check your internet connection."
        )
    if "overloaded" in e or "529" in e:
        return (
            "SERVER BUSY",
            "Anthropic's servers are temporarily overloaded. Waiting and retrying."
        )
    return ("ERROR", err_str[:120])


def print_error(context: str, err_str: str):
    label, explanation = classify_error(err_str)
    print(f"\n  {RED}[{label}]{RESET} {YELLOW}{context}{RESET}")
    for line in textwrap.wrap(explanation, WIDTH - 2):
        print(f"  {GREY}{line}{RESET}")


# ── FMP key diagnostic ────────────────────────────────────────────────────────

def check_fmp_key() -> bool:
    """Quick ping to FMP to verify the key works."""
    if not FMP_KEY:
        return False
    try:
        r = requests.get(f"{FMP_BASE}/quote/AAPL",
                         params={"apikey": FMP_KEY}, timeout=6)
        if r.ok and r.json():
            return True
        if r.status_code == 401 or (r.ok and isinstance(r.json(), dict) and "Error" in r.json()):
            print(f"\n  {RED}[FMP KEY INVALID]{RESET} {GREY}Your FMP API key was rejected.")
            print(f"  Get a free key at: {CYAN}financialmodelingprep.com{RESET}")
            print(f"  Then: {CYAN}$env:FMP_API_KEY='your-key'{RESET}\n")
            return False
    except Exception:
        pass
    return False


# ── Sector familiarity classifier ────────────────────────────────────────────

def classify_sector_familiarity(sector: str) -> tuple[bool, str]:
    """
    Use a cheap no-web-search Claude call to decide if a sector is
    well-known enough that web search isn't needed to identify companies.
    Returns (needs_web_search, reason).
    Borderline always defaults to True (use web search) to avoid missing
    smaller or newer companies.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""Is "{sector}" a well-established investment sector with many publicly listed 
companies that a trained financial analyst would know from memory without needing 
to search the web?

Answer with ONLY one of these three words:
  YES    — well-known sector, 20+ public companies, no search needed (e.g. semiconductors, copper mining, oil & gas, pharmaceuticals)
  NO     — niche, emerging, or obscure — web search essential to find the right companies (e.g. helium-3, neuromorphic chips, solid-state batteries)
  UNSURE — borderline — web search recommended to avoid missing newer or smaller companies

Reply with only YES, NO, or UNSURE. Nothing else."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip().upper()
        if answer == "YES":
            return False, "well-known sector — skipping web search to save credits"
        elif answer == "NO":
            return True, "niche/emerging sector — using web search to find newer companies"
        else:
            return True, "borderline sector — using web search to avoid missing companies"
    except Exception:
        # If the classifier itself fails, default to web search (safe option)
        return True, "classifier unavailable — defaulting to web search"


# ── Adaptive delay tracker ────────────────────────────────────────────────────

class AdaptiveDelay:
    """
    Tracks rate limit hits and adapts the delay between API calls.
    Starts at BASE_DELAY, doubles on each rate limit hit, resets after
    a successful run of RESET_AFTER consecutive successes.
    """
    BASE_DELAY    = 8    # seconds between briefs normally
    MAX_DELAY     = 90   # cap
    RESET_AFTER   = 3    # consecutive successes before resetting delay

    def __init__(self):
        self.delay       = self.BASE_DELAY
        self.successes   = 0
        self.total_waits = 0

    def on_success(self):
        self.successes += 1
        if self.successes >= self.RESET_AFTER and self.delay > self.BASE_DELAY:
            self.delay = max(self.BASE_DELAY, self.delay // 2)
            self.successes = 0

    def on_rate_limit(self):
        self.successes   = 0
        self.delay       = min(self.delay * 2, self.MAX_DELAY)
        self.total_waits += 1
        print(f"\n  {YELLOW}[RATE LIMITED]{RESET} {GREY}Adapting — new delay between "
              f"briefs: {self.delay}s{RESET}")

    def wait(self):
        time.sleep(self.delay)

    def summary(self) -> str:
        if self.total_waits == 0:
            return f"{GREEN}No rate limits hit{RESET}"
        return f"{YELLOW}{self.total_waits} rate limit(s) encountered — final delay {self.delay}s{RESET}"




def call_claude_with_retry(client, max_retries=4, **kwargs):
    """Call Claude API with automatic retry on rate limit or server busy."""
    delay = 15  # seconds between retries
    for attempt in range(max_retries):
        try:
            return client.messages.create(**kwargs)
        except Exception as e:
            err = str(e)
            label, explanation = classify_error(err)
            if attempt < max_retries - 1 and label in ("RATE LIMITED", "SERVER BUSY"):
                print(f"\n  {YELLOW}[{label}]{RESET} {GREY}Waiting {delay}s before retry "
                      f"({attempt+1}/{max_retries-1})...{RESET}")
                time.sleep(delay)
                delay = min(delay * 2, 60)  # exponential backoff, cap at 60s
            else:
                raise
    raise RuntimeError("Max retries exceeded")


# ── Step 1: Identify companies ────────────────────────────────────────────────

def identify_sector_companies(sector: str, region: str, limit: int,
                               use_web_search: bool = True) -> list[dict]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    region_map = {
        "us":     "Focus on US-listed companies (NYSE, NASDAQ) only.",
        "uk":     "Focus on UK-listed companies (LSE Main Market and AIM) only.",
        "global": ("Include companies from ALL major global exchanges: "
                   "NYSE, NASDAQ, LSE, AIM, TSX (Canada), ASX (Australia), "
                   "Euronext, Frankfurt, Tokyo (TSE), Hong Kong (HKEX). Be genuinely global."),
        "both":   "Include US (NYSE/NASDAQ) and UK (LSE/AIM) listed companies.",
    }
    region_note = region_map.get(region, region_map["both"])

    # Extra instruction when NOT using web search — push Claude to be thorough
    # from training knowledge, including smaller and newer companies
    knowledge_note = ""
    if not use_web_search:
        knowledge_note = """
You are working from training knowledge only (no web search).
Be especially thorough — include smaller, less-covered, and newer public companies 
alongside the large caps. Do not just list the obvious top 5 names."""

    prompt = f"""You are a senior equity research analyst. Identify ALL meaningful publicly listed 
companies with exposure to this sector or theme:

SECTOR / THEME: {sector}

{region_note}
{knowledge_note}
Return ONLY a raw JSON array (no markdown, no backticks, no explanation).
Include up to {limit} companies — be comprehensive, don't stop early if there are more.
Each object must have EXACTLY these fields:
  "ticker"    : primary exchange ticker (e.g. IONQ, ENS.L, SYA.AX, 6501.T)
  "name"      : full legal company name
  "exchange"  : exchange (NYSE/NASDAQ/LSE/AIM/TSX/ASX/Euronext/TSE/HKEX/Frankfurt)
  "country"   : 2-letter ISO country code (US/GB/CA/AU/DE/JP/HK etc.)
  "fmp_ticker": ticker for Financial Modeling Prep API:
                US/NASDAQ/NYSE tickers as-is (e.g. LIN, APD, IONQ)
                UK LSE/AIM: add .L suffix (e.g. ENS.L, BOO.L)
                Canada TSX: add .TO suffix (e.g. SU.TO)
                Australia ASX: add .AX suffix (e.g. BHP.AX)
                Japan TSE: as-is numeric (e.g. 6501.T)
                If genuinely unsure, leave as the primary ticker
  "description": one sentence — what they do and their specific relevance to {sector}
  "pure_play"  : true if this is a pure-play on the sector, false if diversified exposure

Order: pure-plays first, then diversified.
Only genuine publicly listed equities. No ETFs. No private companies.
Return valid JSON array only — no other text whatsoever."""

    # Only attach web search tool if needed
    kwargs = dict(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    if use_web_search:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

    response = call_claude_with_retry(client, **kwargs)

    raw = "\n".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\[[\s\S]+\]", raw)
    if not match: return []
    try:
        return json.loads(match.group())[:limit]
    except Exception:
        return []


# ── Step 2: Fetch financials ──────────────────────────────────────────────────

def fetch_financials(ticker: str, fmp_ticker: str, exchange: str) -> dict:
    t   = fmp_ticker or ticker
    fin = {"_ticker": t, "_errors": []}

    def fmp_get(endpoint, params=None, timeout=8):
        p = {"apikey": FMP_KEY}
        if params: p.update(params)
        r = requests.get(f"{FMP_BASE}/{endpoint}/{t}", params=p, timeout=timeout)
        if not r.ok:
            fin["_errors"].append(f"{endpoint}: HTTP {r.status_code}")
            return None
        data = r.json()
        # FMP returns error messages as dicts with "Error Message" key
        if isinstance(data, dict) and ("Error Message" in data or "error" in data):
            msg = data.get("Error Message") or data.get("error","unknown")
            fin["_errors"].append(f"{endpoint}: {msg[:60]}")
            return None
        if isinstance(data, list) and len(data) == 0:
            fin["_errors"].append(f"{endpoint}: no data returned (ticker may not be in FMP)")
            return None
        return data

    # Quote
    data = fmp_get("quote")
    if data:
        q = data[0]
        fin.update({
            "price": q.get("price"), "market_cap": q.get("marketCap"),
            "change_pct": q.get("changesPercentage"), "52w_high": q.get("yearHigh"),
            "52w_low": q.get("yearLow"), "avg_volume": q.get("avgVolume"),
            "shares_out": q.get("sharesOutstanding"), "pe_ratio": q.get("pe"),
            "eps": q.get("eps"),
        })

    # Income statement
    data = fmp_get("income-statement", {"limit": 2})
    if data:
        s0 = data[0]
        fin.update({
            "revenue": s0.get("revenue"), "gross_profit": s0.get("grossProfit"),
            "gross_margin": (s0["grossProfit"] / s0["revenue"] * 100
                             if s0.get("revenue") and s0.get("grossProfit") else None),
            "ebitda": s0.get("ebitda"), "net_income": s0.get("netIncome"),
            "rd_expense": s0.get("researchAndDevelopmentExpenses"),
            "operating_income": s0.get("operatingIncome"),
            "report_date": s0.get("date", "")[:7],
        })
        if len(data) > 1:
            prev = data[1].get("revenue") or 0
            curr = s0.get("revenue") or 0
            if prev: fin["revenue_growth"] = (curr - prev) / abs(prev) * 100

    # Balance sheet
    data = fmp_get("balance-sheet-statement", {"limit": 2})
    if data:
        b0 = data[0]
        fin.update({
            "cash": b0.get("cashAndCashEquivalents"),
            "total_debt": b0.get("totalDebt"),
            "net_debt": ((b0.get("totalDebt") or 0) - (b0.get("cashAndCashEquivalents") or 0)),
            "equity": b0.get("totalStockholdersEquity"),
            "total_assets": b0.get("totalAssets"),
        })
        if len(data) > 1:
            cur_sh  = b0.get("commonStock") or 0
            prev_sh = data[1].get("commonStock") or 0
            if prev_sh > 0:
                fin["dilution_yoy_pct"] = (cur_sh - prev_sh) / prev_sh * 100

    # Cash flow
    data = fmp_get("cash-flow-statement", {"limit": 2})
    if data:
        c0 = data[0]
        fin.update({
            "operating_cf": c0.get("operatingCashFlow"),
            "capex": c0.get("capitalExpenditure"),
            "fcf": c0.get("freeCashFlow"),
            "stock_based_comp": c0.get("stockBasedCompensation"),
            "shares_issued": c0.get("commonStockIssued"),
            "shares_repurchased": c0.get("commonStockRepurchased"),
        })
        ocf = c0.get("operatingCashFlow")
        if ocf and ocf < 0 and fin.get("cash"):
            mb = abs(ocf) / 12
            fin["monthly_burn"]  = mb
            fin["runway_months"] = fin["cash"] / mb if mb > 0 else None

    # Key metrics TTM
    data = fmp_get("key-metrics-ttm")
    if data:
        m = data[0]
        fin.update({
            "ev_ebitda":     m.get("enterpriseValueOverEBITDATTM"),
            "ps_ratio":      m.get("priceToSalesRatioTTM"),
            "debt_equity":   m.get("debtToEquityTTM"),
            "current_ratio": m.get("currentRatioTTM"),
            "roe":           m.get("roeTTM"),
            "roa":           m.get("roaTTM"),
            "ev":            m.get("enterpriseValueTTM"),
        })

    # Insider ownership
    data = fmp_get("insider-roaster-statistic")
    if data:
        ins = data[0] if isinstance(data, list) else data
        fin.update({
            "insider_ownership":       ins.get("ownedByInsiders"),
            "institutional_ownership": ins.get("ownedByInstitutions"),
        })

    return fin


def fmp_data_quality_note(fin: dict) -> str:
    """Return a human-readable note about why FMP data may be missing."""
    errors = fin.get("_errors", [])
    if not errors: return ""

    # Categorise the errors
    reasons = set()
    for e in errors:
        el = e.lower()
        if "no data returned" in el:
            reasons.add("not_in_fmp")
        elif "401" in el or "invalid" in el or "api" in el:
            reasons.add("auth")
        elif "403" in el or "subscription" in el or "upgrade" in el:
            reasons.add("tier")
        elif "timeout" in el:
            reasons.add("timeout")
        elif "http 4" in el or "http 5" in el:
            reasons.add("http_error")

    if "auth" in reasons:
        return "FMP key invalid — run: $env:FMP_API_KEY='your-key'"
    if "tier" in reasons:
        return "Data requires FMP paid tier — free tier covers US large/mid caps only"
    if "not_in_fmp" in reasons:
        return "Ticker not found in FMP — may be too small, delisted, or non-US format"
    if "timeout" in reasons:
        return "FMP request timed out — try again"
    if "http_error" in reasons:
        return "FMP returned an error — ticker format may need adjusting"
    return f"{len(errors)} FMP endpoint(s) returned no data"


# ── Step 3: AI brief with retry ───────────────────────────────────────────────

def ai_mini_brief(ticker: str, name: str, sector: str, fin: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    def fv(key):
        v = fin.get(key)
        return fmt_large(v) if v is not None else "unknown"

    runway  = fin.get("runway_months")
    dil_yoy = fin.get("dilution_yoy_pct")

    fin_ctx = f"""
Market cap: {fv('market_cap')} | EV: {fv('ev')}
Revenue (TTM): {fv('revenue')} | YoY Growth: {f"{fin['revenue_growth']:+.1f}%" if fin.get('revenue_growth') else 'unknown'}
EBITDA: {fv('ebitda')} | Net income: {fv('net_income')} | FCF: {fv('fcf')}
Gross margin: {f"{fin['gross_margin']:.0f}%" if fin.get('gross_margin') else 'unknown'}
Cash: {fv('cash')} | Total debt: {fv('total_debt')} | Net debt: {fv('net_debt')}
Monthly burn: {fv('monthly_burn')} | Cash runway: {f"{runway:.0f} months" if runway else 'unknown'}
Shares outstanding: {f"{fin['shares_out']/1e6:.1f}M" if fin.get('shares_out') else 'unknown'}
Share dilution YoY: {f"{dil_yoy:+.1f}%" if dil_yoy is not None else 'unknown'}
Stock-based comp: {fv('stock_based_comp')} | Shares issued: {fv('shares_issued')}
Insider ownership: {f"{fin['insider_ownership']*100:.1f}%" if fin.get('insider_ownership') else 'unknown'}
R&D spend: {fv('rd_expense')}"""

    # Note if financials are unavailable — brief should rely on web search
    data_note = ""
    if not fin.get("market_cap") and not fin.get("revenue"):
        data_note = ("\nNote: Structured financial data unavailable for this company. "
                     "Please rely on web search for all financial figures and report "
                     "what you find, clearly labelled as (est.) or (source: web).")

    prompt = f"""You are a deep tech equity analyst. Analyse {name} ({ticker}) in the {sector} sector.
{data_note}
Known financials:{fin_ctx}

Search the web for: key contracts, partnerships, government grants, dilution events,
debt restructuring, insider buying/selling, warrant overhang, major catalysts or red flags.

Respond in EXACTLY this format — no extra text, no markdown:
THESIS: [2 sentences — what they do and the investment case for {sector} exposure]
CONTRACTS: [Notable contracts, partnerships, grants, or milestones. 'None identified' if none]
DILUTION: [Dilution risk — history, upcoming raises, ATM facilities, warrant overhang]
INSIDER: [Insider ownership and any notable recent buying or selling]
RISK: [Single most material investment risk in one sentence]
CONVICTION: [X/10 — one sentence. Penalise for runway under 12mo, heavy dilution, no revenue traction]"""

    response = call_claude_with_retry(
        client,
        model="claude-sonnet-4-5",
        max_tokens=600,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(b.text for b in response.content if b.type == "text")


# ── Step 4: Render company card ───────────────────────────────────────────────

SECTION_STYLE = {
    "THESIS":    (CYAN,   "o"),
    "CONTRACTS": (GREEN,  "+"),
    "DILUTION":  (YELLOW, "^"),
    "INSIDER":   (BLUE,   "*"),
    "RISK":      (RED,    "!"),
    "CONVICTION":(WHITE,  "S"),
}

def render_company(company: dict, fin: dict, brief: str, index: int):
    ticker   = company.get("ticker", "?")
    name     = company.get("name", "Unknown")
    exchange = company.get("exchange", "")
    country  = company.get("country", "")
    desc     = company.get("description", "")
    pure     = company.get("pure_play", False)
    pure_tag = f"  {GREEN}[pure-play]{RESET}" if pure else f"  {GREY}[diversified]{RESET}"

    print(f"\n  {BOLD}{WHITE}{index}. {name}{RESET}  "
          f"{CYAN}{ticker}{RESET}  {GREY}{exchange} / {country}{RESET}{pure_tag}")
    divider()

    if desc:
        for line in textwrap.wrap(desc, WIDTH - 2):
            print(f"  {GREY}{line}{RESET}")

    # Data quality note if FMP failed
    fmp_note = fmp_data_quality_note(fin)
    if fmp_note:
        print(f"\n  {YELLOW}[FMP DATA NOTE]{RESET} {GREY}{fmp_note}{RESET}")

    # Pricing
    price  = fin.get("price");   mktcap = fin.get("market_cap")
    chg    = fin.get("change_pct"); hi52 = fin.get("52w_high"); lo52 = fin.get("52w_low")
    ev     = fin.get("ev")

    if price or mktcap:
        print()
        parts = []
        if price:   parts.append(f"{CYAN}Price:{RESET} {fmt_large(price,'$',3)}  {fmt_pct(chg)}")
        if hi52 and lo52: parts.append(f"{GREY}52w {fmt_large(lo52,'$',2)}-{fmt_large(hi52,'$',2)}{RESET}")
        if mktcap:  parts.append(f"{CYAN}Mkt Cap:{RESET} {fmt_large(mktcap)}")
        if ev:      parts.append(f"{CYAN}EV:{RESET} {fmt_large(ev)}")
        print("  " + "  |  ".join(parts))

    # Revenue & profitability
    rev    = fin.get("revenue"); rev_gr = fin.get("revenue_growth")
    gm     = fin.get("gross_margin"); ebitda = fin.get("ebitda")
    ni     = fin.get("net_income"); rd = fin.get("rd_expense"); fcf = fin.get("fcf")

    if any(v is not None for v in [rev, ebitda, ni]):
        print()
        pre_rev = rev is not None and rev < 5_000_000
        rev_col = YELLOW if pre_rev else WHITE
        rev_str = (f"{rev_col}{fmt_large(rev)}{RESET} {GREY}(pre/early revenue){RESET}"
                   if pre_rev else fmt_large(rev)) if rev else na()
        print(f"  {CYAN}Revenue:{RESET} {rev_str}  "
              f"{CYAN}Growth:{RESET} {fmt_pct(rev_gr)}  "
              f"{CYAN}Gross Margin:{RESET} {fmt_pct(gm, 0) if gm else na()}")
        print(f"  {CYAN}EBITDA:{RESET} {colour_ebitda(ebitda)}  "
              f"{CYAN}Net Income:{RESET} {colour_ebitda(ni)}  "
              f"{CYAN}FCF:{RESET} {colour_ebitda(fcf)}")
        if rd and rev and rev > 0:
            print(f"  {CYAN}R&D:{RESET} {fmt_large(rd)}  {GREY}({rd/rev*100:.0f}% of revenue){RESET}")

    # Balance sheet & burn
    cash   = fin.get("cash"); debt = fin.get("total_debt")
    net_d  = fin.get("net_debt"); burn = fin.get("monthly_burn")
    runway = fin.get("runway_months"); de = fin.get("debt_equity"); cr = fin.get("current_ratio")

    if any(v is not None for v in [cash, debt, burn]):
        print()
        print(f"  {CYAN}Cash:{RESET} {colour_cash(cash)}  "
              f"{CYAN}Total Debt:{RESET} {colour_debt(debt)}  "
              f"{CYAN}Net Debt:{RESET} {colour_debt(net_d)}")
        if burn or runway:
            print(f"  {CYAN}Monthly Burn:{RESET} {fmt_large(burn) if burn else na()}  "
                  f"{CYAN}Runway:{RESET} {colour_runway(runway)}  "
                  f"{CYAN}D/E:{RESET} {f'{de:.2f}' if de else na()}  "
                  f"{CYAN}Current Ratio:{RESET} {f'{cr:.2f}' if cr else na()}")

    # Dilution & ownership
    shares  = fin.get("shares_out"); dil_yoy = fin.get("dilution_yoy_pct")
    sbc     = fin.get("stock_based_comp"); sh_iss = fin.get("shares_issued")
    ins_own = fin.get("insider_ownership"); inst_own = fin.get("institutional_ownership")

    if any(v is not None for v in [shares, dil_yoy, ins_own, sbc]):
        print()
        shares_s = f"{shares/1e6:.1f}M" if shares else na()
        if dil_yoy is not None:
            dc = RED if dil_yoy > 10 else (YELLOW if dil_yoy > 3 else GREEN)
            dil_s = f"{dc}{dil_yoy:+.1f}%{RESET}"
        else: dil_s = na()
        print(f"  {CYAN}Shares Out:{RESET} {shares_s}  "
              f"{CYAN}Dilution YoY:{RESET} {dil_s}  "
              f"{CYAN}SBC:{RESET} {fmt_large(sbc) if sbc else na()}")
        print(f"  {CYAN}Insider Own:{RESET} {f'{ins_own*100:.1f}%' if ins_own else na()}  "
              f"{CYAN}Institutional:{RESET} {f'{inst_own*100:.1f}%' if inst_own else na()}")

    # Multiples (context only)
    pe = fin.get("pe_ratio"); ps = fin.get("ps_ratio")
    eveb = fin.get("ev_ebitda"); roe = fin.get("roe")

    if any(v is not None for v in [pe, ps, eveb]):
        print()
        print(f"  {GREY}[Multiples — context only, not weighted in conviction]{RESET}")
        pe_s   = f"{pe:.1f}x"   if pe and pe > 0    else f"{GREY}N/A (loss){RESET}"
        ps_s   = f"{ps:.1f}x"   if ps               else na()
        eveb_s = f"{eveb:.1f}x" if eveb and eveb > 0 else f"{GREY}N/A{RESET}"
        roe_s  = fmt_pct(roe * 100 if roe else None, 0)
        print(f"  {CYAN}P/E:{RESET} {pe_s}  {CYAN}P/S:{RESET} {ps_s}  "
              f"{CYAN}EV/EBITDA:{RESET} {eveb_s}  {CYAN}ROE:{RESET} {roe_s}")

    # AI brief
    if brief:
        print()
        for key, (colour, icon) in SECTION_STYLE.items():
            match = re.search(rf"{key}:\s*(.+?)(?=\n[A-Z]+:|$)", brief, re.DOTALL)
            if not match: continue
            text = match.group(1).strip()
            if not text or text.lower() in ("n/a", "none", "unknown"): continue

            if key == "CONVICTION":
                sm = re.search(r"(\d+)\s*/\s*10", text)
                if sm:
                    score = int(sm.group(1))
                    bar   = f"{CYAN}{'#' * score}{GREY}{'.' * (10 - score)}{RESET}"
                    rest  = re.sub(r"\d+\s*/\s*10\s*[-]?\s*", "", text).strip()
                    print(f"  {colour}{BOLD}[{icon}] {key}:{RESET} {score}/10  {bar}")
                    if rest:
                        for line in textwrap.wrap(rest, WIDTH - 2):
                            print(f"  {GREY}{line}{RESET}")
                    continue

            print(f"  {colour}{BOLD}[{icon}] {key}:{RESET}")
            for line in textwrap.wrap(text, WIDTH - 2):
                print(f"    {line}")

    divider()


# ── Summary table ─────────────────────────────────────────────────────────────

def render_summary_table(companies: list, fin_map: dict):
    header("SECTOR OVERVIEW")
    print(f"\n  {BOLD}{'#':<3} {'Ticker':<9} {'Name':<24} {'Mkt Cap':>9} "
          f"{'Revenue':>9} {'Cash':>9} {'Debt':>9} {'Runway':>8} {'EBITDA':>9}{RESET}")
    divider()

    for i, co in enumerate(companies, 1):
        t   = co.get("ticker","?")
        n   = co.get("name","")[:22]
        fin = fin_map.get(t, {})
        p   = co.get("pure_play", False)
        tag = f"{GREEN}*{RESET}" if p else " "

        mc   = fmt_large(fin.get("market_cap"))   if fin.get("market_cap")           else na()
        rv   = fmt_large(fin.get("revenue"))       if fin.get("revenue")              else na()
        ca   = fmt_large(fin.get("cash"))          if fin.get("cash") is not None     else na()
        db   = fmt_large(fin.get("total_debt"))    if fin.get("total_debt") is not None else na()
        ru   = fin.get("runway_months")
        ru_s = f"{ru:.0f}mo"                       if ru                              else na()
        eb   = fmt_large(fin.get("ebitda"))        if fin.get("ebitda") is not None   else na()

        print(f"  {GREY}{i:<3}{RESET}{tag}{CYAN}{t:<9}{RESET}{n:<24} "
              f"{mc:>9} {rv:>9} {ca:>9} {db:>9} {ru_s:>8} {eb:>9}")

    print(f"\n  {GREEN}*{RESET} = pure-play on sector\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Use REMAINDER to avoid argparse treating hyphens in sector names as flags
    parser = argparse.ArgumentParser(description="Sector Screener")
    parser.add_argument("--limit",    type=int, default=15,
                        help="Max companies to return (default 15, no hard cap)")
    parser.add_argument("--region",   type=str, default="both",
                        choices=["us","uk","global","both"])
    parser.add_argument("--no-brief", action="store_true",
                        help="Skip AI brief — financials only (much faster)")
    parser.add_argument("--refresh",  action="store_true",
                        help="Ignore cache and re-identify companies (uses API credit)")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Clear all cached company lists and exit")
    parser.add_argument("--sector",   type=str, default=None,
                        help="Sector to screen (wrap in quotes: --sector 'helium-3')")
    args = parser.parse_args()

    # Key checks
    if not ANTHROPIC_KEY:
        print(f"\n  {RED}[AUTH ERROR]{RESET} {GREY}ANTHROPIC_API_KEY not set.{RESET}")
        print(f"  {CYAN}$env:ANTHROPIC_API_KEY='sk-ant-...'{RESET}\n")
        sys.exit(1)

    if getattr(args, "clear_cache", False):
        clear_cache(); sys.exit(0)

    # FMP key check
    fmp_ok = False
    if FMP_KEY:
        print(f"  {GREY}Verifying FMP key...{RESET}", end=" ", flush=True)
        fmp_ok = check_fmp_key()
        if fmp_ok:
            ok("FMP key valid")
        # check_fmp_key() prints its own error if invalid
    else:
        print(f"\n  {YELLOW}[FMP KEY MISSING]{RESET} {GREY}Financial data will be unavailable.{RESET}")
        print(f"  Free key at: {CYAN}financialmodelingprep.com{RESET}")
        print(f"  Set with: {CYAN}$env:FMP_API_KEY='your-key'{RESET}\n")

    # Interactive mode
    sector = args.sector
    if not sector:
        print(f"\n  {BOLD}{WHITE}Sector Screener Terminal{RESET}")
        print(f"  {GREY}AI-powered / Global exchanges / Comprehensive financials{RESET}\n")
        print(f"  {GREY}Examples: helium-3 / copper / nuclear / quantum computing")
        print(f"           semiconductors / synthetic biology / solid state batteries")
        print(f"           longevity biotech / space infrastructure / fusion energy{RESET}\n")

        sector = input(f"  {CYAN}Sector / theme:{RESET} ").strip()
        if not sector: sys.exit(0)

        ri = input(f"  {CYAN}Region — us / uk / global / both [both]:{RESET} ").strip().lower()
        args.region = ri if ri in ("us","uk","global","both") else "both"

        li = input(f"  {CYAN}Max companies [15, no hard cap]:{RESET} ").strip()
        args.limit = int(li) if li.isdigit() else 15

        nb = input(f"  {CYAN}Skip AI brief for speed? y/[n]:{RESET} ").strip().lower()
        args.no_brief = nb == "y"

    # Clean up sector string (remove leading -- if user typed it by mistake)
    sector = sector.lstrip("-").strip()

    header(f"SECTOR SCREEN  /  {sector.upper()}  /  {args.region.upper()}  /  MAX {args.limit}")

    # 1 — Identify (with cache + smart web search decision)
    cached = None if getattr(args, "refresh", False) else load_cache(sector, args.region, args.limit)
    if cached:
        companies = cached
        print(f"  {GREY}[1/3]{RESET} Using cached company list "
              f"{GREEN}({len(companies)} companies){RESET} "
              f"{GREY}— run with --refresh to update{RESET}")
    else:
        # Classify sector familiarity — cheap call, no web search
        print(f"  {GREY}[1/3]{RESET} Checking sector familiarity...", end=" ", flush=True)
        needs_web, reason = classify_sector_familiarity(sector)
        tag = f"{YELLOW}[web search]{RESET}" if needs_web else f"{GREEN}[training only]{RESET}"
        print(f"{tag} {GREY}{reason}{RESET}")

        print(f"        Identifying companies...", end=" ", flush=True)
        try:
            companies = identify_sector_companies(
                sector, args.region, args.limit, use_web_search=needs_web
            )
        except Exception as e:
            print_error("Failed to identify companies", str(e))
            sys.exit(1)

        if not companies:
            print(f"\n  {YELLOW}No companies found.{RESET} {GREY}Try a broader term "
                  f"(e.g. 'helium' instead of 'helium-3', 'nuclear energy' instead of 'SMR').{RESET}")
            sys.exit(1)

        save_cache(sector, args.region, args.limit, companies)
        ok(f"{len(companies)} companies identified + cached for 24h")

    # 2 — Financials
    fin_map = {}
    if fmp_ok:
        status(2, 3, "Fetching comprehensive financials...")
        print()
        for co in companies:
            ticker     = co.get("ticker","")
            fmp_ticker = co.get("fmp_ticker") or ticker
            exchange   = co.get("exchange","")
            print(f"    {GREY}-> {ticker:<12}{RESET}", end=" ", flush=True)
            try:
                fin = fetch_financials(ticker, fmp_ticker, exchange)
                fin_map[ticker] = fin
                fields = sum(1 for k, v in fin.items()
                             if k not in ("_ticker","_errors") and v is not None)
                note = fmp_data_quality_note(fin)
                if fields > 3:
                    print(f"{GREEN}{fields} data points{RESET}")
                else:
                    short = note[:60] if note else "limited data"
                    print(f"{YELLOW}limited  ({short}){RESET}")
            except Exception as e:
                fin_map[ticker] = {"_errors": [str(e)]}
                label, _ = classify_error(str(e))
                print(f"{RED}[{label}]{RESET}")
            time.sleep(0.4)
    else:
        status(2, 3, "Skipping financials...")
        ok("(no valid FMP key)")
        for co in companies:
            fin_map[co.get("ticker","")] = {}

    # 3 — Summary
    render_summary_table(companies, fin_map)

    # 4 — Detailed cards with adaptive delay
    if not args.no_brief:
        status(3, 3, "Running AI analysis per company...")
        delay_tracker = AdaptiveDelay()
        print(f"\n  {GREY}(web search per company — adaptive pacing to avoid rate limits){RESET}")
        subheader(f"COMPANY BRIEFS  /  {sector.upper()}")

        for i, co in enumerate(companies, 1):
            ticker = co.get("ticker","?")
            name   = co.get("name","")
            fin    = fin_map.get(ticker, {})
            try:
                brief = ai_mini_brief(ticker, name, sector, fin)
                delay_tracker.on_success()
            except Exception as e:
                label, explanation = classify_error(str(e))
                if label in ("RATE LIMITED", "SERVER BUSY"):
                    delay_tracker.on_rate_limit()
                brief = (f"THESIS: Brief unavailable due to {label}.\n"
                         f"RISK: {explanation}\nCONVICTION: N/A")
            render_company(co, fin, brief, i)
            if i < len(companies):  # no need to wait after the last one
                delay_tracker.wait()

        print(f"\n  {GREY}Rate limit summary: {delay_tracker.summary()}{RESET}")
    else:
        ok("done (brief skipped — run without --no-brief for AI analysis)")

    print(f"\n  {GREY}{'-' * WIDTH}{RESET}")
    print(f"  {GREY}Sources: Financial Modeling Prep / Claude AI + live web search{RESET}")
    print(f"  {GREY}For research and educational purposes only. Not financial advice.{RESET}")
    print(f"  {GREY}Always verify against primary filings before making investment decisions.{RESET}")
    print(f"  {GREY}{'-' * WIDTH}{RESET}\n")


if __name__ == "__main__":
    main()
