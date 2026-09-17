# CLAUDE.md

Guidance for Claude Code sessions working in this repository. See `README.md`
for the full project description and `docs/PROGRESS.md` for the running log
of what's been verified live, what's broken assumptions, and what's still
open — read that before assuming any endpoint, rate limit, or data shape
works the way its docstring says without a "verified live" date on it.

## Standing instruction: maximize free data on every session

**Every time you work on this project, try to fetch/refresh as much data as
possible for as many companies as possible, using only free sources that
need no account and no API key.** Prioritize, in order:

1. **Polish stocks on GPW (Warsaw Stock Exchange), PLN-denominated** — the
   `Główny Rynek` (Main Market) universe, via `xtb_analyzer.gpw` /
   `xtb-analyzer fetch-gpw`.
2. **ETFs quoted on GPW in PLN** — including globally-focused ones (DAX,
   S&P 500, Nasdaq trackers, etc.) cross-listed there; also via `fetch-gpw`.
3. Everything else the pipeline already covers (`fetch-sec` for US-listed
   stocks, the real XTB universe once credentials exist).

This is a standing preference from the project owner, not a one-off task —
don't wait to be asked again. Concretely, each session should default to:

```bash
xtb-analyzer fetch-gpw                                              # stocks + ETFs, one shot
xtb-analyzer map --snapshot data/gpw_instruments.csv \
  --output data/gpw_identity_map.csv --figi                         # Yahoo tickers + FIGI
xtb-analyzer ohlcv --identity-map data/gpw_identity_map.csv \
  --output-dir data/gpw_ohlcv                                       # full history, all symbols
xtb-analyzer technicals --ohlcv-dir data/gpw_ohlcv \
  --output data/gpw_technicals.csv                                  # stage 5 indicators
```

The GPW universe (~440 instruments) is small enough that a full `ohlcv` run
completes in one sitting (a few minutes) — unlike the US/SEC universe
(10k+ symbols), there's no need to scope it down to a subset. Re-run these
each session to keep the committed data fresh; `ohlcv` is incremental
(only pulls bars newer than what's on disk), so repeated runs are cheap.

**Be a good citizen of the free sources being used** — GPW's endpoints,
Yahoo Finance's chart API and SEC EDGAR are all undocumented or
rate-limited internals of someone else's production site, not a public API
meant for bulk scraping. Keep the existing throttles, don't parallelize
requests, and if a source starts blocking (`403`, `429`, or SEC's stricter
"Undeclared Automated Tool" flag — see `docs/PROGRESS.md`), stop and
document it rather than retry-looping or working around it.

## Key facts to know before touching this repo

* **Multiple independent universes, never conflated**: the real XTB
  universe (`data/instruments.csv`, still empty — no session has had XTB
  credentials), the login-free US universe (`data/us_stocks*`, via SEC
  EDGAR), and the login-free GPW universe (`data/gpw_*`). Each has its own
  snapshot/identity-map/OHLCV/fundamentals files; commands take
  `--snapshot`/`--identity-map`/`--output-dir` to point at the right one.
* **No new runtime dependencies without a good reason** — the project
  intentionally sticks to `websocket-client` + `python-dotenv` plus the
  standard library (`urllib`, `re`, `csv`, `json`) for every HTTP client and
  parser. Match that style rather than reaching for `requests` or
  `BeautifulSoup`.
* **Every external client is injectable** (`getter`/`poster` parameters) so
  its request/response plumbing can be unit tested without the network —
  follow that pattern for anything new that talks to an external service.
* **Verify live, then document it** — this codebase has already shipped and
  then corrected two wrong assumptions once real traffic exposed them
  (OpenFIGI returning ISIN; picking the first-present XBRL concept instead
  of the most current one). Don't trust an unverified assumption about an
  external source's shape or limits; when you do verify one, say so with a
  date in the docstring/README/PROGRESS entry, the same way the existing
  code does.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest              # fixture/fake-based, no network or credentials required
ruff check .
ruff format .
```

CI runs the same three on every push and pull request.
