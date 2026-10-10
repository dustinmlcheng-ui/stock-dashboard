#!/usr/bin/env python3
"""Build the stock dashboard for local preview and GitHub Pages (python3 stdlib only).

Reads the Stock Watcher digest (default /workspace/stock-watcher/latest.json),
normalises it (tolerating common schema variations), merges it with the
watchlist, and writes:
  - index.html — self-contained (CSS, JS and data inlined); relative-only so it
    works from file:// and under a Pages subdirectory
    (e.g. https://dustinmlcheng-ui.github.io/stock-dashboard/)
  - latest.json — a copy of the source digest in the site folder so Pages can
    serve the raw file after each rebuild/commit

If latest.json is missing or unreadable, falls back to sample_data.json
(clearly flagged as EXAMPLE data, shown with a banner on the page). The sample
is regenerated from watchlist.csv if it doesn't exist.

Usage:
    python3 build.py                     # real data if present, else sample
    python3 build.py --source FILE.json  # build from a specific file (e.g. history/...)
    python3 build.py --sample            # force example data
    python3 build.py --make-sample       # (re)generate sample_data.json, then build

Idempotent: same input -> byte-identical output; files are only rewritten
when their content changes.
"""
import argparse, csv, datetime as dt, json, math, os, random, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WATCHER_DIR = Path("/workspace/stock-watcher")
DEFAULT_SOURCE = WATCHER_DIR / "latest.json"
WATCHLIST = WATCHER_DIR / "watchlist.csv"
SAMPLE = HERE / "sample_data.json"
SRC = HERE / "src"
HKT = dt.timezone(dt.timedelta(hours=8), "HKT")
MOVER_THRESHOLD = 3.0  # percent

# ---------------------------------------------------------------- key aliases
# Keys are compared after lower-casing and stripping non-alphanumerics, so
# "pct_change", "pctChange" and "Pct Change" all match "pctchange".
ALIASES = {
    "session_date": ["sessiondate", "session", "date", "tradingdate", "tradedate",
                     "marketdate", "asofdate", "asof", "sessionday"],
    "market_context": ["marketcontext", "context", "marketcontextline", "marketsummary",
                       "summary", "marketline", "contextline", "headline", "overview",
                       "market"],
    "generated_at": ["generatedat", "generated", "createdat", "timestamp", "runat",
                     "updatedat", "builtat"],
    "is_example": ["isexample", "example", "issample", "sample", "isdemo"],
    "stocks": ["tickers", "stocks", "results", "data", "quotes", "items", "watchlist",
               "rows", "securities", "symbols", "entries", "companies", "all"],
    "movers_list": ["movers", "topmovers", "bigmovers"],
    "threshold": ["thresholdpct", "threshold", "moverthreshold", "moverthresholdpct",
                  "movethreshold", "minmovepct"],
    "market_cap_basis": ["marketcapbasis", "capbasis", "mcapbasis", "marketcapnote"],
    "ticker": ["ticker", "symbol", "tickersymbol", "code", "sym"],
    "name": ["name", "company", "companyname", "displayname", "longname", "shortname",
             "security", "securityname"],
    "close": ["close", "closeprice", "price", "last", "lastprice", "lastclose",
              "lastsale", "closingprice", "currentprice", "regularmarketprice"],
    "prev_close": ["prevclose", "previousclose", "priorclose", "prevcloseprice",
                   "previousclosingprice", "lastclose_prev", "yesterdayclose",
                   "regularmarketpreviousclose", "pclose", "prev"],
    "pct_change": ["pctchange", "changepct", "percentchange", "changepercent", "pct",
                   "pctchg", "chgpct", "changeperc", "percchange", "dailychangepct",
                   "dailypctchange", "change_percentage", "changepercentage", "movepct",
                   "pctmove", "returnpct"],
    "abs_change": ["change", "netchange", "chg", "pricechange", "abschange"],
    "market_cap": ["marketcap", "marketcapusd", "mktcap", "marketcapitalization", "cap",
                   "marketvalue"],
    "mover": ["mover", "ismover", "flag", "moverflag", "flagged", "significant",
              "bigmove", "ismove"],
    "reason": ["reason", "reasontext", "explanation", "why", "rationale", "summary",
               "note", "notes", "commentary", "analysis", "driver", "drivers", "catalyst"],
    "sources": ["sources", "source", "links", "citations", "references", "news",
                "articles", "refs"],
    "outlet": ["outlet", "source", "publisher", "site", "provider", "publication", "domain"],
    "title": ["title", "headline", "name", "text"],
    "url": ["url", "link", "href", "uri"],
}


def nk(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def pick(d, field, default=None):
    """Return d[<first alias of field present>] (case/punctuation-insensitive)."""
    if not isinstance(d, dict):
        return default
    norm = {nk(k): v for k, v in d.items()}
    for alias in ALIASES[field]:
        a = nk(alias)
        if a in norm and norm[a] not in (None, ""):
            return norm[a]
    return default


def num(v):
    """Parse numbers like 123.4, "123.4", "$1,234.5", "+3.2%", "5.76T"."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, dict):  # e.g. {"raw": 1.23, "fmt": "1.23"}
        for k in ("raw", "value", "v", "amount"):
            if k in v:
                return num(v[k])
        return None
    s = str(v).strip().replace(",", "").replace("$", "").replace("%", "")
    s = s.replace("\u2212", "-")
    mult = 1.0
    m = re.fullmatch(r"([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s*([KMBT])?", s, re.I)
    if not m:
        return None
    if m.group(2):
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]
    try:
        return float(m.group(1)) * mult
    except ValueError:
        return None


def truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "y", "1", "mover", "up", "down", "x")
    return bool(v)


def clean_name(name):
    """'NVIDIA Corporation Common Stock' -> 'NVIDIA Corporation'."""
    if not name:
        return name
    n = re.sub(r"\s+(Class [A-Z] )?(Common Stock|Ordinary Shares|Subordinate Voting Shares|"
               r"American Depositary Shares|New York Registry Shares)\b.*$", "", name)
    return n.strip() or name


# ---------------------------------------------------------------- watchlist
def load_watchlist():
    rows = []
    if WATCHLIST.exists():
        with WATCHLIST.open(newline="") as f:
            for r in csv.DictReader(f):
                rows.append({"ticker": r["ticker"].strip().upper(),
                             "name": r.get("name", "").strip(),
                             "market_cap": num(r.get("market_cap_usd")),
                             "as_of_date": r.get("as_of_date", "").strip()})
    return rows


# ---------------------------------------------------------------- sources
def norm_sources(raw):
    if raw is None:
        return []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for s in raw:
        if isinstance(s, str):
            s = s.strip()
            if re.match(r"https?://", s):
                out.append({"outlet": re.sub(r"^https?://(www\.)?", "", s).split("/")[0],
                            "title": s, "url": s})
            elif s:
                out.append({"outlet": s, "title": "", "url": ""})
            continue
        if isinstance(s, (list, tuple)) and s:  # [outlet, title, url]
            s = dict(zip(("outlet", "title", "url"), s))
        if not isinstance(s, dict):
            continue
        url = str(pick(s, "url", "") or "").strip()
        outlet = pick(s, "outlet")
        title = pick(s, "title")
        if not outlet and url:
            outlet = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        out.append({"outlet": str(outlet or "Source"), "title": str(title or url or ""),
                    "url": url if re.match(r"https?://", url) else ""})
    return out


# ---------------------------------------------------------------- normalise
def extract_stock_records(data):
    """Return list of (ticker_hint, record_dict) from list- or dict-shaped data."""
    if isinstance(data, list):
        return [(None, r) for r in data if isinstance(r, dict)]
    container = pick(data, "stocks")
    if container is None:
        # maybe the top level itself is keyed by ticker
        cand = {k: v for k, v in data.items()
                if isinstance(v, dict) and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", str(k))}
        container = cand if cand else []
    if isinstance(container, dict):
        # dict keyed by ticker, or a wrapper like {"items": [...]}
        inner = pick(container, "stocks")
        if isinstance(inner, (list, dict)) and not pick(container, "ticker"):
            return extract_stock_records({"stocks": inner})
        return [(k, v) for k, v in container.items() if isinstance(v, dict)]
    if isinstance(container, list):
        return [(None, r) for r in container if isinstance(r, dict)]
    return []


def normalise(data, watchlist, source_label, is_example):
    notes = []
    top = data if isinstance(data, dict) else {}
    recs = extract_stock_records(data)

    # Separate movers list (e.g. {"movers": [{ticker, reason, sources}]}) merged in.
    movers_extra = {}
    ml = pick(top, "movers_list")
    if isinstance(ml, dict):
        ml = [dict(v, ticker=v.get("ticker", k)) if isinstance(v, dict) else {"ticker": k}
              for k, v in ml.items()]
    if isinstance(ml, list):
        for m in ml:
            if isinstance(m, str):
                movers_extra[m.upper()] = {}
            elif isinstance(m, dict) and pick(m, "ticker"):
                movers_extra[str(pick(m, "ticker")).upper()] = m
    if not recs and movers_extra:
        recs = [(None, m) for m in movers_extra.values()]

    wl = {w["ticker"]: w for w in watchlist}
    stocks = {}
    for hint, r in recs:
        t = str(pick(r, "ticker") or hint or "").strip().upper()
        if not t:
            continue
        extra = movers_extra.get(t, {})
        close = num(pick(r, "close"))
        prev = num(pick(r, "prev_close"))
        pct = num(pick(r, "pct_change"))
        if pct is None:
            pct = num(pick(extra, "pct_change"))
        if pct is None and close is not None and prev:
            pct = (close - prev) / prev * 100
        if prev is None and close is not None and pct is not None and pct != -100:
            prev = close / (1 + pct / 100)
        if prev is None and close is not None:
            chg = num(pick(r, "abs_change"))
            if chg is not None:
                prev = close - chg
                if pct is None and prev:
                    pct = chg / prev * 100
        mcap = num(pick(r, "market_cap"))
        if mcap is None and t in wl:
            mcap = wl[t]["market_cap"]
        reason = pick(r, "reason") or pick(extra, "reason")
        if isinstance(reason, list):
            reason = " ".join(str(x) for x in reason)
        if isinstance(reason, dict):
            reason = pick(reason, "reason") or json.dumps(reason)
        srcs = norm_sources(pick(r, "sources") if pick(r, "sources") is not None
                            else pick(extra, "sources"))
        mflag = pick(r, "mover")
        if mflag is None:
            mover = (t in movers_extra) or (pct is not None and abs(pct) >= MOVER_THRESHOLD)
        else:
            mover = truthy(mflag) or t in movers_extra
        name = pick(r, "name")
        if not isinstance(name, str):
            name = None
        name = clean_name(name or (wl.get(t) or {}).get("name") or t)
        stocks[t] = {"ticker": t, "name": name, "close": close, "prev_close": prev,
                     "pct_change": None if pct is None else round(pct, 4),
                     "market_cap": mcap, "mover": bool(mover),
                     "reason": str(reason).strip() if reason else "",
                     "sources": srcs, "missing": False}

    # Heuristic: values like 0.031 meaning 3.1% (fraction rather than percent).
    pcts = [s["pct_change"] for s in stocks.values() if s["pct_change"] is not None]
    if pcts and max(abs(p) for p in pcts) < 0.25 and any(
            s["close"] and s["prev_close"] for s in stocks.values()):
        s0 = next(s for s in stocks.values() if s["close"] and s["prev_close"]
                  and s["pct_change"] is not None)
        implied = (s0["close"] - s0["prev_close"]) / s0["prev_close"] * 100
        if abs(implied - s0["pct_change"] * 100) < abs(implied - s0["pct_change"]):
            for s in stocks.values():
                if s["pct_change"] is not None:
                    s["pct_change"] = round(s["pct_change"] * 100, 4)
            notes.append("pct_change looked like a fraction; multiplied by 100")

    # Ensure every watchlist ticker appears (shown with dashes if absent).
    for w in watchlist:
        if w["ticker"] not in stocks:
            stocks[w["ticker"]] = {"ticker": w["ticker"], "name": clean_name(w["name"]),
                                   "close": None, "prev_close": None, "pct_change": None,
                                   "market_cap": w["market_cap"], "mover": False,
                                   "reason": "", "sources": [], "missing": True}
    missing = [t for t, s in stocks.items() if s["missing"]]
    if missing and recs:
        notes.append("No data in source for: " + ", ".join(missing))

    order = {w["ticker"]: i for i, w in enumerate(watchlist)}
    rows = sorted(stocks.values(), key=lambda s: (order.get(s["ticker"], 10_000),
                                                   -(s["market_cap"] or 0)))

    session = pick(top, "session_date")
    if isinstance(session, dict):
        session = pick(session, "session_date") or json.dumps(session)
    context = pick(top, "market_context")
    if isinstance(context, dict):
        context = pick(context, "market_context") or pick(context, "reason") or \
            "; ".join(f"{k}: {v}" for k, v in context.items())
    if isinstance(context, list):
        context = " ".join(str(c) for c in context)
    generated = pick(top, "generated_at")
    basis = pick(top, "market_cap_basis")
    if isinstance(basis, str) and basis.strip():
        notes.append("Market-cap basis: " + basis.strip())
    thr = num(pick(top, "threshold"))
    if thr is not None and 0 < thr < 0.25:  # given as a fraction
        thr *= 100

    # Flag market caps that are just the watchlist snapshot (not session-updated).
    present = [s for s in rows if not s["missing"] and s["market_cap"] is not None]
    as_of = {w["as_of_date"] for w in watchlist if w["as_of_date"]}
    if present and all(wl.get(s["ticker"], {}).get("market_cap") == s["market_cap"]
                       for s in present) and as_of and str(session or "") not in as_of:
        notes.append("Market caps equal watchlist.csv values as of " + ", ".join(sorted(as_of))
                     + " (not updated for this session's close)")

    return {"is_example": bool(is_example), "session_date": str(session or ""),
            "market_context": str(context or ""), "generated_at": str(generated or ""),
            "source": source_label,
            "mover_threshold": thr if thr is not None else MOVER_THRESHOLD,
            "notes": notes, "stocks": rows}


# ---------------------------------------------------------------- sample data
def make_sample(watchlist, path=SAMPLE):
    """Deterministic made-up prices built on the real watchlist tickers/caps."""
    rng = random.Random(20261006)
    big = {"MU": 6.8, "SKHY": 5.1, "PLTR": -4.6, "TSLA": -3.4, "SNDK": 7.9, "INTC": 3.3}
    stocks = []
    for w in watchlist:
        t = w["ticker"]
        pct = big.get(t, round(rng.uniform(-2.4, 2.4), 2))
        prev = round(rng.uniform(40, 950), 2)
        close = round(prev * (1 + pct / 100), 2)
        pct = round((close - prev) / prev * 100, 2)
        rec = {"ticker": t, "name": w["name"], "close": close, "previous_close": prev,
               "pct_change": pct,
               "market_cap": round((w["market_cap"] or 0) * (1 + pct / 100)),
               "mover": abs(pct) >= MOVER_THRESHOLD}
        if rec["mover"]:
            rec["reason"] = (f"EXAMPLE reason text for {t}: placeholder explanation of a "
                             f"{'rally' if pct > 0 else 'sell-off'} used only to preview the "
                             "layout. Not real news.")
            rec["sources"] = [
                {"outlet": "Example News", "title": f"Placeholder headline about {t}",
                 "url": "https://example.com"},
                {"outlet": "Sample Wire", "title": f"Another placeholder story on {t}",
                 "url": "https://example.com"}]
        stocks.append(rec)
    sample = {"is_example": True,
              "note": "EXAMPLE DATA - tickers/names/market caps from watchlist.csv; "
                      "prices, moves, reasons and sources are invented.",
              "session_date": "2026-10-06",
              "market_context": "EXAMPLE: Nasdaq Composite +0.4%, S&P 500 +0.2% in a "
                                "made-up session; memory chipmakers led (placeholder text).",
              "tickers": stocks}
    write_if_changed(path, json.dumps(sample, indent=2) + "\n")
    return sample


# ---------------------------------------------------------------- output
def write_if_changed(path, text):
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def render(payload, out_dir):
    tpl = (SRC / "template.html").read_text(encoding="utf-8")
    css = (SRC / "styles.css").read_text(encoding="utf-8")
    js = (SRC / "app.js").read_text(encoding="utf-8")
    data_js = json.dumps(payload, indent=1, ensure_ascii=False)
    # keep "</script>" etc. from terminating the inline script
    data_js = data_js.replace("</", "<\\/").replace("<!--", "<\\!--")
    title = "Nasdaq 40 Dashboard" + (f" · {payload['session_date']}"
                                     if payload["session_date"] else "")
    if payload["is_example"]:
        title += " (example data)"
    html = (tpl.replace("{{TITLE}}", title)
               .replace("/*{{CSS}}*/", css)
               .replace("/*{{DATA}}*/", "window.DASHBOARD_DATA = " + data_js + ";")
               .replace("/*{{JS}}*/", js))
    changed = write_if_changed(Path(out_dir) / "index.html", html)
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--sample", action="store_true", help="force example data")
    ap.add_argument("--make-sample", action="store_true", help="regenerate sample_data.json")
    ap.add_argument("--out", type=Path, default=HERE)
    a = ap.parse_args()

    watchlist = load_watchlist()
    if a.make_sample or not SAMPLE.exists():
        make_sample(watchlist)

    data, label, is_example, warn = None, "", False, None
    if not a.sample:
        if a.source.exists():
            try:
                data = json.loads(a.source.read_text(encoding="utf-8"))
                mtime = dt.datetime.fromtimestamp(a.source.stat().st_mtime, HKT)
                label = f"{a.source} (modified {mtime:%Y-%m-%d %H:%M} HKT)"
                is_example = truthy(pick(data, "is_example", False)) if isinstance(data, dict) else False
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                warn = f"{a.source} unreadable ({e}); using EXAMPLE data"
        else:
            warn = f"{a.source} not found; using EXAMPLE data"
    if data is None:
        data = json.loads(SAMPLE.read_text(encoding="utf-8"))
        label, is_example = f"{SAMPLE.name} (example data)", True

    payload = normalise(data, watchlist, label, is_example)
    if warn:
        payload["notes"].insert(0, warn)
    if not payload["stocks"] or all(s["missing"] for s in payload["stocks"]):
        print("WARNING: no stock records recognised in source", file=sys.stderr)

    a.out.mkdir(parents=True, exist_ok=True)
    # Friendlier source label for the published page (no absolute box paths).
    if not payload["is_example"] and a.source.exists():
        mtime = dt.datetime.fromtimestamp(a.source.stat().st_mtime, HKT)
        payload["source"] = f"latest.json (Stock Watcher, modified {mtime:%Y-%m-%d %H:%M} HKT)"
    elif payload["is_example"]:
        payload["source"] = "sample_data.json (example data)"

    changed = render(payload, a.out)

    # Sync latest.json into the site dir so GitHub Pages can serve it after commit.
    site_latest = a.out / "latest.json"
    if not a.sample and a.source.exists() and data is not None and not is_example:
        src_text = a.source.read_text(encoding="utf-8")
        # Normalise trailing newline for stable diffs
        if not src_text.endswith("\n"):
            src_text += "\n"
        latest_changed = write_if_changed(site_latest, src_text)
    else:
        # EXAMPLE / sample build: write the sample payload used
        sample_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        latest_changed = write_if_changed(site_latest, sample_text)

    movers = [s["ticker"] for s in payload["stocks"] if s["mover"]]
    print(f"{'EXAMPLE' if payload['is_example'] else 'REAL'} data from {label}")
    if warn:
        print("note:", warn)
    for n in payload["notes"]:
        if n != warn:
            print("note:", n)
    print(f"session={payload['session_date'] or '?'} stocks={len(payload['stocks'])} "
          f"movers={','.join(movers) or 'none'}")
    print(f"{'wrote' if changed else 'unchanged'}: {a.out / 'index.html'}")
    print(f"{'wrote' if latest_changed else 'unchanged'}: {site_latest}")


if __name__ == "__main__":
    main()
