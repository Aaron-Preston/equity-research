#!/usr/bin/env python3
"""
Equity Research Terminal — Global CLI
AI-powered analysis for US, UK, Canadian, Australian, OTC and other markets.
Routes each company to the correct filing source automatically.

Requirements:
    py -m pip install anthropic requests

API Keys:
    ANTHROPIC_API_KEY  — console.anthropic.com
    FMP_API_KEY        — financialmodelingprep.com (free tier)

Set in PowerShell:
    $env:ANTHROPIC_API_KEY="sk-ant-..."
    $env:FMP_API_KEY="your-key"

Usage:
    py equity_research.py
    py equity_research.py --ticker IONQ
    py equity_research.py --ticker ENS.L --market uk
    py equity_research.py --ticker SYA.AX --market australia
    py equity_research.py --ticker CRDL --market otc
    py equity_research.py --ticker RY.TO --market canada
    py equity_research.py --ticker IONQ --criteria thesis financials risk insider
"""

import os, sys, re, textwrap, argparse, time
import requests
import anthropic

# ── Keys ──────────────────────────────────────────────────────────────────────

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FMP_KEY       = os.environ.get("FMP_API_KEY", "")
FMP_BASE      = "https://financialmodelingprep.com/api/v3"
EDGAR_HEADERS = {"User-Agent": "equity-research-tool research@example.com"}

# ── Colours ───────────────────────────────────────────────────────────────────

RESET  = "\033[0m"; BOLD   = "\033[1m"
CYAN   = "\033[96m"; GREEN  = "\033[92m"
YELLOW = "\033[93m"; RED    = "\033[91m"
WHITE  = "\033[97m"; GREY   = "\033[90m"
BLUE   = "\033[94m"

WIDTH = 76

# ── Market definitions ────────────────────────────────────────────────────────

MARKETS = {
    "us":        {"label": "US (NYSE/NASDAQ)",    "filing": "edgar",   "currency": "USD"},
    "uk":        {"label": "UK (LSE/AIM)",        "filing": "companies_house", "currency": "GBp"},
    "canada":    {"label": "Canada (TSX/TSXV)",   "filing": "sedar",   "currency": "CAD"},
    "australia": {"label": "Australia (ASX)",     "filing": "asic",    "currency": "AUD"},
    "otc":       {"label": "US OTC Markets",      "filing": "edgar",   "currency": "USD"},
    "japan":     {"label": "Japan (TSE)",         "filing": "edinet",  "currency": "JPY"},
    "europe":    {"label": "Europe (Euronext/Frankfurt)", "filing": "oam", "currency": "EUR"},
    "global":    {"label": "Global / Unknown",    "filing": "web",     "currency": "USD"},
}

CRITERIA_OPTIONS = {
    "thesis":      "Investment thesis — what the company does, market opportunity, transformative potential",
    "financials":  "Financial health — revenue, cash, burn rate, runway, debt. Note if pre-revenue",
    "risk":        "Top 3-4 material risk factors from filings or public disclosures",
    "insider":     "Insider ownership %, notable recent buying or selling, institutional ownership",
    "competitive": "Key competitors, differentiation, moat or lack thereof",
    "contracts":   "Notable contracts, partnerships, government grants, commercial milestones",
    "dilution":    "Dilution risk — share issuance history, ATM facilities, warrant overhang",
}

DEFAULT_CRITERIA = ["thesis", "financials", "risk", "insider"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def divider(): print(f"  {GREY}{'─' * WIDTH}{RESET}")

def header(text):
    print(f"\n  {GREY}{'=' * WIDTH}{RESET}")
    print(f"  {BOLD}{WHITE}  {text}{RESET}")
    print(f"  {GREY}{'=' * WIDTH}{RESET}")

def status(text): print(f"  {GREY}>{RESET} {text}", end=" ", flush=True)
def ok(text="done"): print(f"{GREEN}{text}{RESET}")
def warn(text): print(f"  {YELLOW}!  {text}{RESET}")
def na(): return f"{GREY}N/A{RESET}"

def fmt_large(value, prefix="$", decimals=2):
    if value is None: return na()
    neg = value < 0; av = abs(value)
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
    return (f"{GREEN}{s}{RESET}" if v >= 100e6
            else f"{YELLOW}{s}{RESET}" if v >= 20e6
            else f"{RED}{s}{RESET}")

def colour_runway(m):
    if m is None: return na()
    s = f"{m:.0f} mo"
    return (f"{GREEN}{s}{RESET}" if m >= 24
            else f"{YELLOW}{s}{RESET}" if m >= 12
            else f"{RED}{s}{RESET}")

def classify_error(err_str):
    e = err_str.lower()
    if "429" in e or "rate_limit" in e:
        return ("RATE LIMITED",
                "Too many API requests. Wait 30-60 min or add credit at console.anthropic.com")
    if "401" in e or "authentication" in e:
        return ("AUTH ERROR", "API key invalid. Check console.anthropic.com")
    if "404" in e or "not_found" in e:
        return ("MODEL ERROR", "Model name unrecognised — may need updating")
    if "overloaded" in e or "529" in e:
        return ("SERVER BUSY", "Anthropic servers busy. Try again shortly.")
    if "timeout" in e:
        return ("TIMEOUT", "Request timed out. Check internet connection.")
    return ("ERROR", err_str[:120])

def call_claude(client, max_retries=3, **kwargs):
    delay = 30
    for attempt in range(max_retries):
        try:
            return client.messages.create(**kwargs)
        except Exception as e:
            err = str(e)
            label, explanation = classify_error(err)
            if attempt < max_retries - 1 and label in ("RATE LIMITED", "SERVER BUSY"):
                print(f"\n  {YELLOW}[{label}]{RESET} {GREY}Waiting {delay}s "
                      f"(attempt {attempt+1}/{max_retries-1})...{RESET}")
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise RuntimeError(f"[{label}] {explanation}")
    raise RuntimeError("Max retries exceeded")


# ── Market detection ──────────────────────────────────────────────────────────

def resolve_ticker(raw: str) -> tuple[str, str]:
    """
    If ticker has no suffix and is ambiguous, search FMP for matches
    across exchanges and let the user pick.
    Returns (resolved_ticker, market).
    """
    t = raw.upper().strip()

    # Already has a suffix — no ambiguity
    for suffix, market in [(".L","uk"),(".AX","australia"),(".TO","canada"),
                            (".V","canada"),(".T","japan")]:
        if t.endswith(suffix):
            return t, market

    # Plain ticker — check if it exists on US markets first via FMP
    candidates = []

    if FMP_KEY:
        try:
            r = requests.get(f"{FMP_BASE}/search",
                             params={"query": t, "limit": 8, "apikey": FMP_KEY},
                             timeout=8)
            if r.ok and r.json():
                for item in r.json():
                    sym      = item.get("symbol","")
                    name     = item.get("name","")
                    exchange = item.get("exchangeShortName","") or item.get("exchange","")
                    # Only include if the base ticker matches what user typed
                    base = sym.split(".")[0]
                    if base == t:
                        candidates.append({
                            "symbol": sym, "name": name, "exchange": exchange
                        })
        except Exception:
            pass

    # If only one candidate — use it silently
    if len(candidates) == 1:
        sym = candidates[0]["symbol"]
        print(f"  {GREY}Resolved: {sym} — {candidates[0]['name']} ({candidates[0]['exchange']}){RESET}")
        return sym, detect_market(sym)

    # Multiple candidates — show choices
    if len(candidates) > 1:
        print(f"\n  {YELLOW}Multiple matches for '{t}':{RESET}")
        for i, c in enumerate(candidates, 1):
            print(f"  {CYAN}{i}.{RESET} {c['symbol']:<12} {c['name'][:35]:<35} {GREY}{c['exchange']}{RESET}")
        print(f"  {CYAN}{len(candidates)+1}.{RESET} None of these — enter manually")
        print()
        choice = input(f"  {CYAN}Pick a number:{RESET} ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                sym = candidates[idx]["symbol"]
                return sym, detect_market(sym)
        # Fall through to manual entry
        manual = input(f"  {CYAN}Enter full ticker with suffix (e.g. ENS.L):{RESET} ").strip().upper()
        return manual, detect_market(manual)

    # No FMP results or no key — just use as-is and assume US
    return t, "us"


def detect_market(ticker: str, explicit: str = None) -> str:
    """Detect market from ticker format if not explicitly specified."""
    if explicit and explicit in MARKETS:
        return explicit
    t = ticker.upper()
    if t.endswith(".L"):   return "uk"
    if t.endswith(".AX"):  return "australia"
    if t.endswith(".TO") or t.endswith(".V"): return "canada"
    if t.endswith(".T"):   return "japan"
    if "." not in t and len(t) <= 5: return "us"
    return "global"


def get_fmp_ticker(ticker: str, market: str) -> str:
    """Format ticker for FMP API based on market."""
    t = ticker.upper()
    if market == "uk" and not t.endswith(".L"):       return f"{t}.L"
    if market == "canada" and not t.endswith(".TO"):  return f"{t}.TO"
    if market == "australia" and not t.endswith(".AX"): return f"{t}.AX"
    return t


# ── Filing routers ────────────────────────────────────────────────────────────

def get_us_filing(ticker: str, max_chars: int = 15_000) -> tuple[str, str]:
    """
    Fetch the most recent SEC filing — 10-Q if newer than 10-K, else 10-K.
    Returns (text, source_label) so Claude knows what period it covers.
    """
    try:
        # Get CIK
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers=EDGAR_HEADERS, timeout=10)
        r.raise_for_status()
        cik = None
        for entry in r.json().values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                break
        if not cik:
            return None, "SEC EDGAR (CIK not found)"

        # Get filings list
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         headers=EDGAR_HEADERS, timeout=10)
        r.raise_for_status()
        filings  = r.json()["filings"]["recent"]
        forms    = filings["form"]
        accnums  = filings["accessionNumber"]
        primary  = filings["primaryDocument"]
        dates    = filings.get("filingDate", [""] * len(forms))

        # Find most recent 10-K and most recent 10-Q
        annual_idx    = next((i for i, f in enumerate(forms) if f in ("10-K","10-K/A")), None)
        quarterly_idx = next((i for i, f in enumerate(forms) if f in ("10-Q","10-Q/A")), None)

        # Pick whichever is more recent
        chosen_idx  = None
        chosen_type = None

        if annual_idx is not None and quarterly_idx is not None:
            ak_date = dates[annual_idx]
            qq_date = dates[quarterly_idx]
            if qq_date > ak_date:
                chosen_idx  = quarterly_idx
                chosen_type = "10-Q"
            else:
                chosen_idx  = annual_idx
                chosen_type = "10-K"
        elif annual_idx is not None:
            chosen_idx  = annual_idx
            chosen_type = "10-K"
        elif quarterly_idx is not None:
            chosen_idx  = quarterly_idx
            chosen_type = "10-Q"
        else:
            return None, "SEC EDGAR (no 10-K or 10-Q found)"

        filing_date = dates[chosen_idx] if chosen_idx < len(dates) else "unknown date"
        accession   = accnums[chosen_idx].replace("-","")
        doc_name    = primary[chosen_idx]
        int_cik     = int(cik)
        doc_url     = (f"https://www.sec.gov/Archives/edgar/data/"
                       f"{int_cik}/{accession}/{doc_name}")

        r = requests.get(doc_url, headers=EDGAR_HEADERS, timeout=15)
        r.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s{3,}", "\n", text).strip()

        label = (f"SEC EDGAR {chosen_type} filed {filing_date} (CIK {int_cik}) — "
                 f"NOTE: This covers the period ending ~{filing_date[:7]}. "
                 f"Search the web for any developments AFTER this date.")
        return text[:max_chars], label

    except Exception as e:
        return None, f"SEC EDGAR (error: {str(e)[:50]})"


def get_uk_filing(ticker: str, max_chars: int = 12_000) -> tuple[str, str]:
    """
    Fetch filing data from Companies House API.
    Returns filing text and source label.
    Companies House API is free but requires registration at developer.company-information.service.gov.uk
    """
    ch_key = os.environ.get("COMPANIES_HOUSE_KEY", "")
    clean  = ticker.upper().replace(".L","").replace(".AX","")

    if not ch_key:
        return None, "Companies House (no API key — set COMPANIES_HOUSE_KEY env var)"

    try:
        # Search for company
        r = requests.get(
            "https://api.company-information.service.gov.uk/search/companies",
            params={"q": clean, "items_per_page": 3},
            auth=(ch_key, ""), timeout=10
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return None, "Companies House (company not found)"

        company_number = items[0]["company_number"]
        company_name   = items[0]["title"]

        # Get filing history
        r = requests.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}/filing-history",
            params={"category": "accounts", "items_per_page": 5},
            auth=(ch_key, ""), timeout=10
        )
        r.raise_for_status()
        filings = r.json().get("items", [])

        if not filings:
            return None, f"Companies House ({company_name} — no accounts found)"

        # Return company metadata as context (full document download requires extra steps)
        meta = (f"Company: {company_name}\n"
                f"Company Number: {company_number}\n"
                f"Most recent accounts type: {filings[0].get('type','unknown')}\n"
                f"Filing date: {filings[0].get('date','unknown')}\n"
                f"Companies House profile: "
                f"https://find-and-update.company-information.service.gov.uk/company/{company_number}")
        return meta, f"Companies House ({company_name})"

    except Exception as e:
        return None, f"Companies House (error: {str(e)[:50]})"


def get_filing(ticker: str, market: str) -> tuple[str, str]:
    """Route to correct filing source based on market."""
    if market in ("us", "otc"):
        return get_us_filing(ticker)
    elif market == "uk":
        filing, label = get_uk_filing(ticker)
        if not filing:
            # Fallback note — Claude will use web search
            return None, label
        return filing, label
    else:
        # Canada (SEDAR+), Australia (ASIC), Japan (EDINET), Europe (OAM/BaFin)
        # No public API available — return note so AI uses web search instead
        source_map = {
            "canada":    "SEDAR+ (no public API — using web search for filing data)",
            "australia": "ASIC (no public API — using web search for filing data)",
            "japan":     "EDINET (API exists but returns Japanese — using web search)",
            "europe":    "OAM/BaFin (limited API — using web search for filing data)",
            "global":    "Unknown market — using web search for all data",
        }
        return None, source_map.get(market, "Unknown source")


# ── FMP financials ────────────────────────────────────────────────────────────

def fetch_fmp_financials(fmp_ticker: str) -> dict:
    """Fetch structured financials from FMP."""
    fin = {}
    if not FMP_KEY: return fin

    def get(endpoint, params=None):
        p = {"apikey": FMP_KEY}
        if params: p.update(params)
        try:
            r = requests.get(f"{FMP_BASE}/{endpoint}/{fmp_ticker}",
                             params=p, timeout=8)
            if not r.ok: return None
            d = r.json()
            if isinstance(d, dict) and "Error" in str(d): return None
            if isinstance(d, list) and len(d) == 0: return None
            return d
        except Exception:
            return None

    # Quote
    d = get("quote")
    if d:
        q = d[0]
        fin.update({
            "price": q.get("price"), "market_cap": q.get("marketCap"),
            "change_pct": q.get("changesPercentage"),
            "52w_high": q.get("yearHigh"), "52w_low": q.get("yearLow"),
            "shares_out": q.get("sharesOutstanding"),
            "pe_ratio": q.get("pe"), "eps": q.get("eps"),
        })

    # Income
    d = get("income-statement", {"limit": 2})
    if d:
        s = d[0]
        fin.update({
            "revenue": s.get("revenue"), "gross_profit": s.get("grossProfit"),
            "gross_margin": (s["grossProfit"]/s["revenue"]*100
                             if s.get("revenue") and s.get("grossProfit") else None),
            "ebitda": s.get("ebitda"), "net_income": s.get("netIncome"),
            "rd_expense": s.get("researchAndDevelopmentExpenses"),
            "report_date": s.get("date","")[:7],
        })
        if len(d) > 1:
            prev = d[1].get("revenue") or 0
            curr = s.get("revenue") or 0
            if prev: fin["revenue_growth"] = (curr-prev)/abs(prev)*100

    # Balance sheet
    d = get("balance-sheet-statement", {"limit": 2})
    if d:
        b = d[0]
        fin.update({
            "cash": b.get("cashAndCashEquivalents"),
            "total_debt": b.get("totalDebt"),
            "net_debt": ((b.get("totalDebt") or 0) - (b.get("cashAndCashEquivalents") or 0)),
            "equity": b.get("totalStockholdersEquity"),
            "total_assets": b.get("totalAssets"),
        })
        if len(d) > 1:
            cur = b.get("commonStock") or 0
            prev = d[1].get("commonStock") or 0
            if prev > 0: fin["dilution_yoy_pct"] = (cur-prev)/prev*100

    # Cash flow
    d = get("cash-flow-statement", {"limit": 1})
    if d:
        c = d[0]
        fin.update({
            "operating_cf": c.get("operatingCashFlow"),
            "fcf": c.get("freeCashFlow"),
            "stock_based_comp": c.get("stockBasedCompensation"),
            "shares_issued": c.get("commonStockIssued"),
            "capex": c.get("capitalExpenditure"),
        })
        ocf = c.get("operatingCashFlow")
        if ocf and ocf < 0 and fin.get("cash"):
            mb = abs(ocf)/12
            fin["monthly_burn"]  = mb
            fin["runway_months"] = fin["cash"]/mb if mb > 0 else None

    # Key metrics
    d = get("key-metrics-ttm")
    if d:
        m = d[0]
        fin.update({
            "ev_ebitda":     m.get("enterpriseValueOverEBITDATTM"),
            "ps_ratio":      m.get("priceToSalesRatioTTM"),
            "debt_equity":   m.get("debtToEquityTTM"),
            "current_ratio": m.get("currentRatioTTM"),
            "ev":            m.get("enterpriseValueTTM"),
        })

    # Insider ownership
    d = get("insider-roaster-statistic")
    if d:
        ins = d[0] if isinstance(d, list) else d
        fin.update({
            "insider_ownership":       ins.get("ownedByInsiders"),
            "institutional_ownership": ins.get("ownedByInstitutions"),
        })

    return fin


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(ticker, name_hint, market, criteria, filing_text,
                 filing_source, fin) -> str:

    market_info = MARKETS.get(market, MARKETS["global"])
    currency    = market_info["currency"]

    # Extract filing period from source label for the recency note
    period_match = re.search(r"filed (\d{4}-\d{2})", filing_source or "")
    filing_period = period_match.group(1) if period_match else "unknown period"

    # Filing context
    if filing_text:
        filing_block = (
            f"\nPRIMARY FILING DATA ({filing_source}):\n"
            f"IMPORTANT: This filing covers the period ending approximately {filing_period}. "
            f"You MUST supplement this with web searches for anything that has happened AFTER "
            f"this date — earnings releases, contract announcements, management changes, "
            f"litigation updates, capital raises, and any other material developments.\n"
            f"{'─'*40}\n{filing_text}\n{'─'*40}\n"
        )
    else:
        filing_block = (
            f"\nFILING DATA: Not available ({filing_source}).\n"
            f"Rely entirely on web search for all financial and filing data.\n"
            f"Label estimates clearly as (est.) or (source: web).\n"
        )

    # Structured financials from FMP
    def fv(key, fmt=fmt_large):
        v = fin.get(key)
        return fmt(v) if v is not None else "not available from FMP"

    fin_block = ""
    if fin:
        runway  = fin.get("runway_months")
        dil_yoy = fin.get("dilution_yoy_pct")
        fin_block = f"""
STRUCTURED FINANCIAL DATA (Financial Modeling Prep — most recent available):
  Price: {fv('price')} {currency} | Mkt Cap: {fv('market_cap')} | EV: {fv('ev')}
  52w range: {fv('52w_low')} - {fv('52w_high')}
  Revenue (TTM): {fv('revenue')} | YoY Growth: {f"{fin['revenue_growth']:+.1f}%" if fin.get('revenue_growth') else 'N/A'}
  Gross Margin: {f"{fin['gross_margin']:.0f}%" if fin.get('gross_margin') else 'N/A'}
  EBITDA: {fv('ebitda')} | Net Income: {fv('net_income')} | FCF: {fv('fcf')}
  Cash: {fv('cash')} | Total Debt: {fv('total_debt')} | Net Debt: {fv('net_debt')}
  Monthly Burn: {fv('monthly_burn')} | Runway: {f"{runway:.0f} months" if runway else 'N/A'}
  Shares Out: {f"{fin['shares_out']/1e6:.1f}M" if fin.get('shares_out') else 'N/A'}
  Dilution YoY: {f"{dil_yoy:+.1f}%" if dil_yoy is not None else 'N/A'}
  SBC: {fv('stock_based_comp')} | Shares Issued: {fv('shares_issued')}
  Insider Own: {f"{fin['insider_ownership']*100:.1f}%" if fin.get('insider_ownership') else 'N/A'}
  Inst. Own: {f"{fin['institutional_ownership']*100:.1f}%" if fin.get('institutional_ownership') else 'N/A'}
  P/E: {f"{fin['pe_ratio']:.1f}x" if fin.get('pe_ratio') else 'N/A'} | P/S: {f"{fin['ps_ratio']:.1f}x" if fin.get('ps_ratio') else 'N/A'} | EV/EBITDA: {f"{fin['ev_ebitda']:.1f}x" if fin.get('ev_ebitda') else 'N/A'}
  R&D: {fv('rd_expense')} | D/E: {f"{fin['debt_equity']:.2f}" if fin.get('debt_equity') else 'N/A'}
"""
    else:
        fin_block = "\nSTRUCTURED FINANCIAL DATA: Not available (no FMP key or ticker not in FMP).\n"

    # Criteria instructions
    criteria_map = {
        "thesis":      f"THESIS: Investment thesis — what they do, market opportunity, why transformative. Note market ({market_info['label']}), relevant regulatory or macro tailwinds. Search for the most recent analyst or investor commentary.",
        "financials":  f"FINANCIALS: Use FMP data above as base. Then search for the MOST RECENT earnings release or quarterly update AFTER {filing_period} and report those figures prominently, clearly labelled with the period they cover. Include cash runway.",
        "risk":        f"RISK: Top 3-4 material risks. Include market-specific risks (currency, regulatory, liquidity for {market}). Check for any NEW risks that emerged after the filing date.",
        "insider":     "INSIDER: Ownership % and ALL recent insider transactions. Search specifically for insider buys or sells in the last 6 months — name the individuals and amounts.",
        "competitive": "COMPETITIVE: Key competitors, differentiation, moat or lack thereof. Note any competitive developments since the last filing.",
        "contracts":   f"CONTRACTS: This is critical — search specifically for: (1) any contract renewals or new agreements with named customers (e.g. search '{ticker} contract renewal', '{ticker} partnership', '{ticker} agreement 2025 2026'), (2) government grants or awards, (3) licensing deals. Name the counterparties and deal values where findable. Flag if key contracts are at risk of non-renewal.",
        "dilution":    "DILUTION: Share issuance history, current ATM facilities, outstanding warrants (list exercise prices), any announced or likely upcoming raises. Be specific about overhang size.",
    }

    criteria_block = "\n".join(
        criteria_map.get(c, f"{c.upper()}: Analyse {c}.")
        for c in criteria if c in criteria_map
    )

    market_note = ""
    if market == "otc":
        market_note = ("\nNOTE: OTC-traded company. Flag liquidity risk, "
                       "bid-ask spreads, and reduced disclosure vs major exchanges.")
    elif market == "uk":
        market_note = ("\nNOTE: UK-listed. Reference Companies House and AIM/LSE rules. "
                       "Note disclosure standard differences vs US markets.")
    elif market == "canada":
        market_note = ("\nNOTE: Canadian-listed. Reference SEDAR+ if findable. "
                       "Note NI 43-101 resource estimates if mining/resource company.")
    elif market == "australia":
        market_note = ("\nNOTE: ASX-listed. Reference ASX announcements if findable. "
                       "Note JORC resource estimates if mining/resource company.")

    return f"""You are a senior equity research analyst specialising in deep tech, 
pre-revenue, and early-revenue public companies globally.

COMPANY: {ticker.upper()}{f" ({name_hint})" if name_hint else ""}
MARKET: {market_info['label']}
CURRENCY: {market_info['currency']}
{market_note}
{filing_block}
{fin_block}

Using all available data above plus web search, provide a structured research brief.
Cover ONLY these sections, using EXACTLY these headers:

{criteria_block}
CONVICTION: Overall investment conviction score X/10. One sentence rationale.
  Penalise heavily for: runway under 12 months, excessive dilution, no revenue traction,
  OTC liquidity risk, unproven technology, weak insider alignment.
  Note: P/E and EBITDA are NOT used in scoring for pre-revenue companies.

Rules:
- Be specific — include actual numbers and dates
- Flag uncertainty clearly: (est.) or (source: web)  
- Keep each section to 3-5 sentences — dense and useful
- For non-US companies, note any data gaps due to filing system limitations
- For educational research only, not financial advice"""


# ── Run analysis ──────────────────────────────────────────────────────────────

def run_analysis(ticker, name_hint, market, criteria, filing_text,
                 filing_source, fin) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = build_prompt(ticker, name_hint, market, criteria,
                          filing_text, filing_source, fin)

    response = call_claude(
        client,
        model="claude-sonnet-4-5",
        max_tokens=1200,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(b.text for b in response.content if b.type == "text")


# ── Render output ─────────────────────────────────────────────────────────────

SECTION_ICONS = {
    "THESIS":      (CYAN,   "o"),
    "FINANCIALS":  (GREEN,  "$"),
    "RISK":        (RED,    "!"),
    "INSIDER":     (BLUE,   "*"),
    "COMPETITIVE": (WHITE,  "#"),
    "CONTRACTS":   (GREEN,  "+"),
    "DILUTION":    (YELLOW, "^"),
    "CONVICTION":  (WHITE,  "S"),
}

def render(ticker, market, filing_source, fin, raw):
    market_info = MARKETS.get(market, MARKETS["global"])

    header(f"{ticker.upper()}  /  {market_info['label']}  /  EQUITY BRIEF")

    # Quick financials snapshot at top
    if fin:
        price  = fin.get("price")
        mktcap = fin.get("market_cap")
        chg    = fin.get("change_pct")
        cash   = fin.get("cash")
        runway = fin.get("runway_months")
        rev    = fin.get("revenue")

        print()
        if price:
            print(f"  {CYAN}Price:{RESET} {fmt_large(price,'',3)} {market_info['currency']}  "
                  f"{fmt_pct(chg)}", end="")
            if mktcap: print(f"  {CYAN}Mkt Cap:{RESET} {fmt_large(mktcap)}", end="")
            print()
        if cash or rev:
            print(f"  {CYAN}Cash:{RESET} {colour_cash(cash)}  "
                  f"{CYAN}Runway:{RESET} {colour_runway(runway)}  "
                  f"{CYAN}Revenue:{RESET} {fmt_large(rev) if rev else na()}")

        # Data source note
        print(f"\n  {GREY}Filing source: {filing_source}{RESET}")
        if not fin.get("price"):
            print(f"  {YELLOW}FMP data unavailable — analysis based on web search and filings only{RESET}")

    print()
    divider()

    # Parse and render sections
    sections = re.split(r"\n(?=[A-Z]{3,12}:)", raw.strip())
    for section in sections:
        if not section.strip(): continue
        colon = section.find(":")
        if colon == -1:
            print(textwrap.fill(section.strip(), WIDTH-4, initial_indent="  "))
            continue
        key  = section[:colon].strip().upper()
        body = section[colon+1:].strip()
        icon_col, icon = SECTION_ICONS.get(key, (WHITE, "-"))

        if key == "CONVICTION":
            sm = re.search(r"(\d+)\s*/\s*10", body)
            if sm:
                score = int(sm.group(1))
                bar   = f"{CYAN}{'#'*score}{GREY}{'.'*(10-score)}{RESET}"
                rest  = re.sub(r"\d+\s*/\s*10\s*[-]?\s*", "", body).strip()
                print(f"\n  {icon_col}{BOLD}[{icon}] {key}:{RESET} {score}/10  {bar}")
                if rest:
                    for line in textwrap.wrap(rest, WIDTH-4):
                        print(f"  {GREY}{line}{RESET}")
                continue

        print(f"\n  {icon_col}{BOLD}[{icon}] {key}:{RESET}")
        for line in textwrap.wrap(body, WIDTH-4):
            print(f"    {line}")

    print()
    divider()
    print(f"  {GREY}For educational purposes only. Not financial advice.{RESET}")
    print(f"  {GREY}Verify against primary sources before any investment decision.{RESET}")
    divider()
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Equity Research Terminal — Global")
    parser.add_argument("--ticker",   type=str, help="Ticker symbol")
    parser.add_argument("--market",   type=str, default=None,
                        choices=list(MARKETS.keys()),
                        help="Market: us / uk / canada / australia / otc / japan / europe / global")
    parser.add_argument("--criteria", nargs="+",
                        choices=list(CRITERIA_OPTIONS.keys()),
                        default=DEFAULT_CRITERIA)
    parser.add_argument("--no-fmp",   action="store_true",
                        help="Skip FMP financials — faster, uses less API credit")
    args = parser.parse_args()

    if not ANTHROPIC_KEY:
        print(f"\n  {RED}[AUTH ERROR]{RESET} ANTHROPIC_API_KEY not set.")
        print(f"  {CYAN}$env:ANTHROPIC_API_KEY='sk-ant-...'{RESET}\n")
        sys.exit(1)

    # Interactive
    ticker = args.ticker
    if not ticker:
        print(f"\n  {BOLD}{WHITE}Equity Research Terminal — Global{RESET}")
        print(f"  {GREY}US / UK / Canada / Australia / OTC / Japan / Europe{RESET}\n")
        print(f"  {GREY}Just type the ticker — suffixes optional:{RESET}")
        print(f"  {CYAN}ENS  or  ENS.L      IONQ      SYA  or  SYA.AX{RESET}")
        print(f"  {CYAN}SHOP or  SHOP.TO    RKLB      6758 or  6758.T{RESET}\n")
        print(f"  {GREY}If multiple companies share a ticker, you'll be shown a list to pick from.{RESET}\n")

        ticker = input(f"  {CYAN}Ticker:{RESET} ").strip().upper()
        if not ticker: sys.exit(0)

        print(f"\n  {GREY}Criteria: {', '.join(CRITERIA_OPTIONS.keys())}{RESET}")
        ci = input(f"  {CYAN}Criteria (space-separated) [{' '.join(DEFAULT_CRITERIA)}]:{RESET} ").strip()
        args.criteria = ci.split() if ci else DEFAULT_CRITERIA

    # Resolve ticker — handles ambiguity and auto-detects market
    ticker, auto_market = resolve_ticker(ticker)
    market = args.market if args.market in MARKETS else auto_market
    fmp_ticker = get_fmp_ticker(ticker, market)
    market_info = MARKETS[market]

    print()
    header(f"RESEARCHING  {ticker.upper()}  /  {market_info['label']}")

    # Step 1: Filing
    status(f"Fetching filing ({market_info['filing'].upper()})...")
    filing_text, filing_source = get_filing(ticker, market)
    if filing_text:
        ok(f"{len(filing_text):,} chars")
    else:
        print(f"{YELLOW}not available{RESET}")
        print(f"  {GREY}  {filing_source}{RESET}")

    # Step 2: FMP financials
    fin = {}
    if not args.no_fmp and FMP_KEY:
        status(f"Fetching financials (FMP: {fmp_ticker})...")
        fin = fetch_fmp_financials(fmp_ticker)
        fields = sum(1 for v in fin.values() if v is not None)
        if fields > 3:
            ok(f"{fields} data points")
        else:
            print(f"{YELLOW}limited ({fields} points — ticker may not be in FMP){RESET}")
    elif not FMP_KEY:
        print(f"  {GREY}Skipping FMP (no key set){RESET}")

    # Step 3: AI analysis
    status("Running AI analysis (web search enabled)...")
    try:
        raw = run_analysis(ticker, None, market, args.criteria,
                           filing_text, filing_source, fin)
        ok()
    except RuntimeError as e:
        label, explanation = classify_error(str(e))
        print(f"\n  {RED}[{label}]{RESET} {explanation}")
        sys.exit(1)

    # Render
    render(ticker, market, filing_source, fin, raw)


if __name__ == "__main__":
    main()
