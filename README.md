# Nasdaq 40 Stock Dashboard

Static dashboard for the Stock Watcher daily digest. Built for GitHub Pages at
`https://dustinmlcheng-ui.github.io/stock-dashboard/` (project-site subdirectory —
all asset references are relative / inlined; no root-absolute `/…` paths).

Open `index.html` locally via `file://` (offline, no server, no CDN) or serve the
folder with any static host.

## Rebuild

```bash
cd /workspace/sites/stock-dashboard
python3 build.py
```

- Reads `/workspace/stock-watcher/latest.json`. If it's missing or unreadable, falls back to
  `sample_data.json` and the page shows a yellow **"Example data — not real prices"** banner.
- Writes:
  - `index.html` — self-contained (CSS, JS and normalised data inlined)
  - `latest.json` — a copy of the Stock Watcher digest so Pages can serve the raw file
- Idempotent: the same input gives byte-identical output, and files are only rewritten when they
  change. Safe to run after each Stock Watcher run (the digest runs daily at 6:15am HKT).
  After each morning digest, rebuild, then commit `index.html` + `latest.json` so the live
  Pages site stays current.
- Python 3 standard library only.

Options:

| Command | Effect |
|---|---|
| `python3 build.py --source /workspace/stock-watcher/history/<file>.json` | build from a specific day |
| `python3 build.py --sample` | force example data |
| `python3 build.py --make-sample` | regenerate `sample_data.json` from `watchlist.csv` |
| `python3 build.py --out DIR` | write outputs somewhere else |

The script prints whether it used REAL or EXAMPLE data, the session date, the movers, and any
notes (for example, watchlist tickers missing from the source).

## GitHub Pages

1. Publish this folder as the `stock-dashboard` repo under `dustinmlcheng-ui` (or enable Pages
   from `/docs` / root of that repo). Use a **project site** URL path
   `/stock-dashboard/` — do not rely on absolute `/css/…` paths; this build inlines everything.
2. After each Stock Watcher digest: `python3 build.py`, then commit and push `index.html` and
   `latest.json`.
3. Live URL: `https://dustinmlcheng-ui.github.io/stock-dashboard/`
4. Raw digest URL (after publish): `https://dustinmlcheng-ui.github.io/stock-dashboard/latest.json`

After each morning Stock Watcher digest, rebuild **and push** so Pages stays current:

```bash
cd /workspace/sites/stock-dashboard
./publish.sh          # runs build.py, commits index.html + latest.json, pushes
# or: python3 build.py && git add index.html latest.json && git commit -m "…" && git push
```

The Web Builder weekday routine (~6:47am HKT) should call `build.py` (or `./publish.sh`);
a push is required for the live site to update — there is no separate cron for git push.


## Input schema (tolerant)

The loader matches keys case- and punctuation-insensitively (`pct_change`, `change_pct`,
`changePct`, `percent_change` … all work), and also handles:

- stocks under `tickers` / `stocks` / `results` / `data` / `quotes`…, as a **list** of objects
  with `ticker`/`symbol`, or as a **dict keyed by ticker**
- an optional separate `movers` list that gets merged into the per-ticker records
- `close`/`price`, `prev_close`/`previous_close`, `market_cap`/`market_cap_usd`, and numbers given
  as strings like `"$1,234.5"`, `"+3.2%"`, `"5.76T"`
- % change missing: worked out from close and previous close. Fractions (0.031 for 3.1%) are
  detected and scaled.
- `mover` flag missing: set when |% change| ≥ 3
- `reason` / `reason_text` / `explanation`; `sources` as a list of `{outlet, title, url}`
  (also `source`/`publisher`, `headline`, `link`), plain URL strings, or missing altogether
- top level: `session_date`/`date`, `market_context`/`context`/`summary`, an optional
  `is_example` (shows the banner when true)

Every watchlist ticker (`/workspace/stock-watcher/watchlist.csv`) shows in the table. A ticker
that's missing from the source shows "—" and falls back to the watchlist market cap.

## Files

- `build.py`: loader, normaliser and page generator (also syncs `latest.json`)
- `src/template.html`, `src/styles.css`, `src/app.js`: page sources (edit these, then rebuild)
- `sample_data.json`: EXAMPLE data (`"is_example": true`). Real tickers, names and market caps;
  invented prices, moves, reasons and `https://example.com` sources.
- `index.html`: the generated page (committed for Pages)
- `latest.json`: copy of the Stock Watcher digest (committed for Pages)
- `.gitignore`: excludes `__pycache__`, screenshots, editor junk
