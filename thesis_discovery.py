#!/usr/bin/env python3
"""
Thesis Discovery Terminal — AI-powered emerging sector intelligence
Monitors Substack, newsletters, arXiv, YC, tech news to surface emerging themes
before they become mainstream investment narratives.

Requirements:
    py -m pip install anthropic requests

API Keys needed:
    ANTHROPIC_API_KEY  — console.anthropic.com

Set in PowerShell:
    $env:ANTHROPIC_API_KEY="sk-ant-..."

Usage:
    py thesis_discovery.py
    py thesis_discovery.py --area "deep tech"
    py thesis_discovery.py --area "energy transition" --depth broad
    py thesis_discovery.py --area "biotech" --top 10
"""

import os, sys, re, json, time, textwrap, argparse
import anthropic

# ── Keys ──────────────────────────────────────────────────────────────────────

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── Colours ───────────────────────────────────────────────────────────────────

RESET   = "\033[0m";  BOLD    = "\033[1m"
CYAN    = "\033[96m"; GREEN   = "\033[92m"
YELLOW  = "\033[93m"; RED     = "\033[91m"
WHITE   = "\033[97m"; GREY    = "\033[90m"
BLUE    = "\033[94m"; MAGENTA = "\033[95m"

WIDTH = 76

# ── Helpers ───────────────────────────────────────────────────────────────────

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

def signal_bar(score: int, width: int = 10) -> str:
    """Visual signal strength bar."""
    filled = min(score, width)
    if score >= 8:   col = GREEN
    elif score >= 5: col = YELLOW
    else:            col = RED
    return f"{col}{'█' * filled}{GREY}{'░' * (width - filled)}{RESET}"

def momentum_tag(momentum: str) -> str:
    m = momentum.lower()
    if "accelerat" in m or "rapid" in m or "surging" in m:
        return f"{GREEN}[ACCELERATING]{RESET}"
    if "emerg" in m or "early" in m or "nascent" in m:
        return f"{CYAN}[EMERGING]{RESET}"
    if "steady" in m or "growing" in m or "building" in m:
        return f"{YELLOW}[BUILDING]{RESET}"
    if "matur" in m or "establish" in m:
        return f"{GREY}[MATURING]{RESET}"
    return f"{GREY}[{momentum.upper()[:12]}]{RESET}"

def classify_error(err_str: str) -> tuple:
    e = err_str.lower()
    if "429" in e or "rate_limit" in e:
        return ("RATE LIMITED",
                "Too many API requests. Wait 30-60 minutes or add credit at console.anthropic.com")
    if "401" in e or "authentication" in e:
        return ("AUTH ERROR",
                "API key invalid. Reset: $env:ANTHROPIC_API_KEY='sk-ant-...'")
    if "404" in e or "not_found" in e:
        return ("MODEL ERROR",
                "Model name unrecognised — script may need updating.")
    if "overloaded" in e or "529" in e:
        return ("SERVER BUSY", "Anthropic servers busy. Try again in a few minutes.")
    if "timeout" in e:
        return ("TIMEOUT", "Request timed out. Check your internet connection.")
    return ("ERROR", err_str[:120])

def call_claude(client, max_retries=3, **kwargs):
    """Claude API call with retry on rate limit."""
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


# ── Source definitions ────────────────────────────────────────────────────────

# These are the source categories Claude searches across
SOURCE_CATEGORIES = {
    "newsletters": [
        "Substack newsletters", "Morning Brew", "The Generalist",
        "Stratechery", "Not Boring by Packy McCormick",
        "Exponential View by Azeem Azhar", "Import AI", "The Diff",
        "Doomberg", "Apricitas Economics", "Noahpinion",
    ],
    "academic": [
        "arXiv preprints", "Nature", "Science", "Cell",
        "IEEE Spectrum", "MIT Technology Review",
    ],
    "venture": [
        "Y Combinator batch companies", "a16z portfolio announcements",
        "Sequoia memos", "Founders Fund thesis posts",
        "Lux Capital", "Breakthrough Energy Ventures",
    ],
    "media": [
        "TechCrunch", "Wired", "The Information", "Bloomberg Technology",
        "FT Alphaville", "Hacker News front page",
    ],
    "social": [
        "X/Twitter deep tech threads", "Reddit r/investing r/stocks r/MachineLearning",
        "LinkedIn thought leadership posts",
    ],
    "government": [
        "DARPA programme announcements", "DOE grant awards",
        "UK ARIA funding", "EU Horizon grants", "NSF awards",
    ],
}


# ── Step 1: Broad signal sweep ────────────────────────────────────────────────

def sweep_for_signals(area: str, depth: str) -> str:
    """
    Ask Claude to search broadly across all source types and identify
    what topics are gaining momentum right now.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    depth_instructions = {
        "focused": f"Focus tightly on '{area}' and its immediate adjacencies.",
        "broad":   f"Start with '{area}' but include adjacent and cross-disciplinary themes that could intersect with it.",
        "open":    "Cast the net very wide — look for any emerging deep tech or investment theme gaining traction recently, not limited to a specific area.",
    }
    depth_note = depth_instructions.get(depth, depth_instructions["broad"])

    sources_flat = ", ".join(
        s for cat in SOURCE_CATEGORIES.values() for s in cat
    )

    prompt = f"""You are an expert technology and investment trend analyst.
Your job is to identify emerging themes and sectors that are gaining momentum RIGHT NOW
— things that are being discussed increasingly in the last 1-3 months but haven't yet
become mainstream investment narratives.

Search focus: {depth_note}

Search across these source types:
{sources_flat}

Look for signals such as:
- Clusters of Substack posts or newsletters covering the same new theme
- arXiv paper volume spikes in a specific technology area
- New Y Combinator or VC-backed companies clustering in a space
- Government grant programmes being announced in a technical area
- A technology transitioning from academic to commercial discussion
- Prominent investors or researchers starting to publicly discuss a new area
- A commodity, material, or resource suddenly becoming strategically discussed
- Regulatory changes creating new investable opportunities

For each theme you identify, note:
- What specific sources are discussing it
- Whether the signal is growing or plateauing
- What the investable angle is (which companies or sectors benefit)
- How early or late the signal appears to be

Search thoroughly before responding. Be specific about sources and timing.
Return your findings as raw material — we will structure them in the next step."""

    response = call_claude(
        client,
        model="claude-sonnet-4-5",
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(b.text for b in response.content if b.type == "text")


# ── Step 2: Structure into ranked themes ──────────────────────────────────────

def structure_themes(raw_signals: str, area: str, top_n: int) -> list[dict]:
    """
    Take the raw signal sweep and structure it into ranked, actionable themes.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""You are a senior investment analyst. Based on the following raw signal research,
identify and rank the top {top_n} most compelling emerging investment themes.

RAW RESEARCH:
{raw_signals}

For each theme, return a JSON object. Return ONLY a raw JSON array, no markdown, no explanation.

Each object must have EXACTLY these fields:
  "rank"          : integer rank 1 to {top_n} (1 = strongest signal)
  "theme"         : short name for the theme (3-6 words, e.g. "Solid-State Battery Manufacturing")
  "sector_query"  : the exact search term to use in the sector screener for this theme
                    (optimised for finding public companies, e.g. "solid state batteries")
  "signal_score"  : integer 1-10 rating of signal strength and conviction
  "momentum"      : one word or short phrase describing trajectory (e.g. "accelerating", "emerging", "building")
  "stage"         : "very early" / "early" / "mid" / "late" — how far along the narrative cycle
  "sources"       : list of 2-4 specific sources where this signal was found (newsletter names, journals, etc.)
  "why_now"       : 2 sentences — what has specifically changed in the last 1-3 months to make this relevant
  "investable"    : 2 sentences — what the investable angle is and what types of companies benefit
  "risks"         : 1 sentence — the key risk to this thesis
  "time_horizon"  : estimated time horizon for this to play out (e.g. "6-18 months", "2-5 years", "5-10 years")
  "tags"          : list of 2-4 relevant tags (e.g. ["deep tech", "materials", "defence"])

Rank by: signal strength + earliness of the opportunity. 
An early-stage theme with strong signals ranks higher than a late-stage well-known theme.
Return valid JSON array only."""

    response = call_claude(
        client,
        model="claude-sonnet-4-5",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = "\n".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\[[\s\S]+\]", raw)
    if not match: return []
    try:
        return json.loads(match.group())
    except Exception:
        return []


# ── Step 3: Deep dive on top themes ──────────────────────────────────────────

def deep_dive_theme(theme: dict) -> dict:
    """
    For the top-ranked themes, do a deeper search for specific signals,
    key people, companies, and catalysts.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""You are a deep tech investment analyst. Do a focused deep dive on this emerging theme:

THEME: {theme.get('theme')}
INITIAL THESIS: {theme.get('investable')}

Search for:
1. The 2-3 most prominent newsletter writers, investors, or researchers currently championing this theme
   (name them specifically — who should I follow to track this?)
2. Any specific Substack posts, essays, or threads in the last 60 days that are worth reading
   (give titles and authors if found)
3. Any recent government announcements, grants, or policy changes accelerating this
4. Early-stage private companies or recent YC batches in this space
   (even if not investable, signals where the public market might follow)
5. The single most important data point or development that makes this thesis compelling right now
6. What would have to be true for this thesis to be WRONG — the bear case in one sentence

Respond in this exact format (no markdown):
CHAMPIONS: [names and roles of 2-3 key people to follow]
READING: [specific posts/essays worth reading, with author names]
CATALYSTS: [government, regulatory, or macro developments]
PRIVATE_SIGNALS: [early-stage companies or YC batches as directional signals]
KEY_DATAPOINT: [the single most compelling piece of evidence for this theme]
BEAR_CASE: [one sentence bear case]"""

    response = call_claude(
        client,
        model="claude-sonnet-4-5",
        max_tokens=800,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )

    raw = "\n".join(b.text for b in response.content if b.type == "text")

    # Parse sections
    sections = {}
    keys = ["CHAMPIONS", "READING", "CATALYSTS", "PRIVATE_SIGNALS", "KEY_DATAPOINT", "BEAR_CASE"]
    for key in keys:
        match = re.search(rf"{key}:\s*(.+?)(?=\n[A-Z_]+:|$)", raw, re.DOTALL)
        if match:
            sections[key] = match.group(1).strip()

    theme["deep_dive"] = sections
    return theme


# ── Render functions ──────────────────────────────────────────────────────────

def render_theme_card(theme: dict, show_deep: bool = False):
    rank      = theme.get("rank", "?")
    name      = theme.get("theme", "Unknown")
    score     = theme.get("signal_score", 0)
    momentum  = theme.get("momentum", "")
    stage     = theme.get("stage", "")
    why_now   = theme.get("why_now", "")
    investable= theme.get("investable", "")
    risks     = theme.get("risks", "")
    horizon   = theme.get("time_horizon", "")
    sources   = theme.get("sources", [])
    tags      = theme.get("tags", [])
    query     = theme.get("sector_query", "")

    # Stage colour
    stage_colours = {
        "very early": MAGENTA, "early": CYAN,
        "mid": YELLOW, "late": GREY,
    }
    stage_col = stage_colours.get(stage.lower(), WHITE)

    print(f"\n  {BOLD}{WHITE}#{rank}  {name}{RESET}  "
          f"{momentum_tag(momentum)}  "
          f"{stage_col}[{stage.upper()}]{RESET}")
    divider()

    # Signal bar
    print(f"  {CYAN}Signal Strength:{RESET}  {signal_bar(score)}  {score}/10  "
          f"  {CYAN}Horizon:{RESET} {horizon}")

    # Tags
    if tags:
        tag_str = "  ".join(f"{GREY}#{t}{RESET}" for t in tags)
        print(f"  {tag_str}")

    # Why now
    if why_now:
        print(f"\n  {CYAN}{BOLD}WHY NOW:{RESET}")
        for line in textwrap.wrap(why_now, WIDTH - 2):
            print(f"    {line}")

    # Investable angle
    if investable:
        print(f"\n  {GREEN}{BOLD}INVESTABLE ANGLE:{RESET}")
        for line in textwrap.wrap(investable, WIDTH - 2):
            print(f"    {line}")

    # Sources
    if sources:
        print(f"\n  {CYAN}SIGNALS FOUND IN:{RESET}")
        for s in sources:
            print(f"    {GREY}· {s}{RESET}")

    # Risk
    if risks:
        print(f"\n  {RED}THESIS RISK:{RESET}")
        for line in textwrap.wrap(risks, WIDTH - 2):
            print(f"    {line}")

    # Screener shortcut
    if query:
        print(f"\n  {GREY}Run in sector screener:{RESET} "
              f"{CYAN}py sector_screener.py --sector \"{query}\"{RESET}")

    # Deep dive section
    if show_deep and theme.get("deep_dive"):
        dd = theme["deep_dive"]
        print(f"\n  {MAGENTA}{BOLD}--- DEEP DIVE ---{RESET}")

        dd_labels = {
            "CHAMPIONS":      ("WHO TO FOLLOW",    CYAN),
            "READING":        ("WORTH READING",     BLUE),
            "CATALYSTS":      ("CATALYSTS",         YELLOW),
            "PRIVATE_SIGNALS":("PRIVATE SIGNALS",   GREY),
            "KEY_DATAPOINT":  ("KEY DATA POINT",    GREEN),
            "BEAR_CASE":      ("BEAR CASE",         RED),
        }

        for key, (label, colour) in dd_labels.items():
            text = dd.get(key, "")
            if not text or text.lower() in ("none", "n/a", "none identified"):
                continue
            print(f"\n  {colour}{BOLD}{label}:{RESET}")
            for line in textwrap.wrap(text, WIDTH - 2):
                print(f"    {line}")

    divider()


def render_summary_rankings(themes: list):
    header("EMERGING THEMES — RANKED SUMMARY")
    print(f"\n  {BOLD}{'Rank':<5} {'Signal':>6}  {'Stage':<12} {'Horizon':<16} {'Theme'}{RESET}")
    divider()

    for t in themes:
        rank    = t.get("rank", "?")
        score   = t.get("signal_score", 0)
        stage   = t.get("stage", "")
        horizon = t.get("time_horizon", "")[:14]
        name    = t.get("theme", "")[:40]
        mom     = t.get("momentum", "")

        stage_colours = {
            "very early": MAGENTA, "early": CYAN,
            "mid": YELLOW, "late": GREY,
        }
        sc = stage_colours.get(stage.lower(), WHITE)

        bar_mini = signal_bar(score, 5)
        print(f"  {GREY}{rank:<5}{RESET}{bar_mini} {score}/10  "
              f"{sc}{stage:<12}{RESET} {GREY}{horizon:<16}{RESET} {WHITE}{name}{RESET}")

    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Thesis Discovery Terminal")
    parser.add_argument("--area",  type=str, default=None,
                        help="Broad area to scan (e.g. 'deep tech', 'energy', 'biotech')")
    parser.add_argument("--depth", type=str, default="broad",
                        choices=["focused", "broad", "open"],
                        help="focused=tight on area / broad=area+adjacencies / open=everything")
    parser.add_argument("--top",   type=int, default=8,
                        help="Number of top themes to surface (default 8)")
    parser.add_argument("--deep",  type=int, default=3,
                        help="Number of top themes to deep-dive (default 3, costs more API)")
    parser.add_argument("--no-deep", action="store_true",
                        help="Skip deep dive — faster and uses less API credit")
    args = parser.parse_args()

    if not ANTHROPIC_KEY:
        print(f"\n  {RED}[AUTH ERROR]{RESET} ANTHROPIC_API_KEY not set.")
        print(f"  {CYAN}$env:ANTHROPIC_API_KEY='sk-ant-...'{RESET}\n")
        sys.exit(1)

    area = args.area
    if not area:
        print(f"\n  {BOLD}{WHITE}Thesis Discovery Terminal{RESET}")
        print(f"  {GREY}Surfaces emerging investment themes from newsletters, arXiv,")
        print(f"  Substack, YC, VC blogs, government grants, and tech media.{RESET}\n")

        print(f"  {GREY}Broad area examples:")
        print(f"    deep tech / energy transition / biotech / defence tech")
        print(f"    materials science / space / climate / computing / food tech{RESET}\n")

        print(f"  {GREY}Or leave blank for a fully open scan across all emerging themes.{RESET}\n")

        area = input(f"  {CYAN}Area to scan (or press Enter for open scan):{RESET} ").strip()
        if not area:
            area = "emerging deep tech and investment themes"
            args.depth = "open"

        di = input(f"  {CYAN}Depth — focused / broad / open [broad]:{RESET} ").strip().lower()
        args.depth = di if di in ("focused","broad","open") else "broad"

        ti = input(f"  {CYAN}How many themes to surface [8]:{RESET} ").strip()
        args.top = int(ti) if ti.isdigit() else 8

        nd = input(f"  {CYAN}Skip deep dive to save API credit? y/[n]:{RESET} ").strip().lower()
        args.no_deep = nd == "y"

        if not args.no_deep:
            di2 = input(f"  {CYAN}How many themes to deep-dive [3]:{RESET} ").strip()
            args.deep = int(di2) if di2.isdigit() else 3

    area = area.strip().lstrip("-")

    header(f"THESIS DISCOVERY  /  {area.upper()}  /  DEPTH: {args.depth.upper()}")

    print(f"\n  {GREY}Sources being searched:{RESET}")
    for cat, sources in SOURCE_CATEGORIES.items():
        print(f"  {CYAN}{cat.capitalize():<14}{RESET} {GREY}{', '.join(sources[:3])}{'...' if len(sources)>3 else ''}{RESET}")

    print()

    # ── Step 1: Signal sweep ──────────────────────────────────────────────────
    status(1, 3 if not args.no_deep else 2, "Sweeping sources for signals (web search)...")
    try:
        raw_signals = sweep_for_signals(area, args.depth)
        ok()
    except RuntimeError as e:
        label, _ = classify_error(str(e))
        print(f"\n  {RED}[{label}]{RESET} {str(e)}")
        sys.exit(1)

    time.sleep(2)

    # ── Step 2: Structure themes ──────────────────────────────────────────────
    status(2, 3 if not args.no_deep else 2, f"Structuring top {args.top} themes...")
    try:
        themes = structure_themes(raw_signals, area, args.top)
        ok(f"{len(themes)} themes identified")
    except RuntimeError as e:
        print(f"\n  {RED}[ERROR]{RESET} {str(e)}")
        sys.exit(1)

    if not themes:
        print(f"\n  {YELLOW}No themes could be structured. Try a broader area.{RESET}")
        sys.exit(1)

    # ── Ranked summary table ──────────────────────────────────────────────────
    render_summary_rankings(themes)

    # ── Step 3: Deep dives on top N ───────────────────────────────────────────
    deep_count = 0 if args.no_deep else min(args.deep, len(themes))

    if deep_count > 0:
        status(3, 3, f"Deep-diving top {deep_count} themes (web search per theme)...")
        print(f"\n  {GREY}(This searches the web for each theme — ~20-30s each){RESET}")

        for i in range(deep_count):
            t = themes[i]
            print(f"  {GREY}  Diving: {t.get('theme','?')}...{RESET}", end=" ", flush=True)
            try:
                themes[i] = deep_dive_theme(t)
                ok()
            except RuntimeError as e:
                label, explanation = classify_error(str(e))
                print(f"{YELLOW}[{label}]{RESET}")
                themes[i]["deep_dive"] = {
                    "KEY_DATAPOINT": f"Deep dive unavailable: {explanation}"
                }
            time.sleep(3)

    # ── Full theme cards ──────────────────────────────────────────────────────
    subheader(f"THEME BRIEFS  /  {area.upper()}")

    for i, theme in enumerate(themes):
        show_deep = (not args.no_deep) and i < deep_count
        render_theme_card(theme, show_deep=show_deep)

    # ── Footer & next steps ───────────────────────────────────────────────────
    print(f"\n  {GREY}{'=' * WIDTH}{RESET}")
    print(f"  {BOLD}{WHITE}NEXT STEPS{RESET}")
    divider()
    print(f"  {GREY}Take any theme above directly into the sector screener:{RESET}")
    print()
    for t in themes[:5]:
        query = t.get("sector_query","")
        name  = t.get("theme","")[:35]
        if query:
            print(f"  {GREY}{name:<37}{RESET} "
                  f"{CYAN}py sector_screener.py --sector \"{query}\"{RESET}")
    print()
    print(f"  {GREY}Or run a deep-dive on a specific company:{RESET}")
    print(f"  {CYAN}py equity_research.py --ticker TICK{RESET}")
    print()
    print(f"  {GREY}Sources: Substack / arXiv / YC / VC blogs / tech media / government grants{RESET}")
    print(f"  {GREY}For research purposes only. Not financial advice.{RESET}")
    print(f"  {GREY}{'=' * WIDTH}{RESET}\n")


if __name__ == "__main__":
    main()
