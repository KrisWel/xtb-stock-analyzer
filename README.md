# xtb-stock-analyzer

Building blocks for a personal tool that tracks every instrument available on an
**XTB** account and — later — scores each ticker as **buy / sell / hold** based on
company fundamentals, history and technical indicators.

> **Status: stage 3 of the roadmap.** The project downloads the full XTB instrument
> universe and reduces it to **cash equities and ETFs/ETNs only** (derivatives —
> stock CFDs, index CFDs, FX, commodities, crypto — are deliberately excluded), maps
> each surviving symbol onto a Yahoo Finance ticker and, optionally, a FIGI, then
> pulls and incrementally refreshes OHLCV history per instrument. No XTB account
> available? `fetch-sec` is a login-free alternative universe (US-listed stocks via
> SEC EDGAR) that the rest of the pipeline works with unchanged — see below.

---

## Why the filtering is the hard part

`getAllSymbols` returns the entire XTB offer in a single flat list, and there is no
field that says *"this is a real share"*. Cash shares and their CFD shadows share the
same `categoryName`, and the same underlying often appears twice (`AAPL.US` and
`AAPL.US_9`). So the filter combines several signals and — importantly — records a
reason for every rejection, so the rules can be verified against live data instead of
being trusted blindly:

| # | Rule | Rejection reason |
|---|------|------------------|
| 1 | `categoryName` must be `STC` (stocks) or `ETF` (ETFs/ETNs) | `category=<value>` |
| 2 | Symbol must not carry a CFD suffix (`AAPL.US_9`) | `cfd-symbol-suffix` |
| 3 | `groupName` / `description` must not contain "CFD" | `cfd-in-text` |
| 4 | `leverage` must be >= 100 (100 = full margin = no leverage) | `leveraged(<100)` |
| 5 | `longOnly` must not be `False` (cash shares cannot be shorted at XTB) | `not-long-only` |

Every rule is switchable via `FilterConfig`, and `xtb-analyzer inspect` prints the raw
field distributions so the thresholds can be re-tuned when XTB changes its data.

---

## Setup

```bash
git clone https://github.com/KrisWel/xtb-stock-analyzer.git
cd xtb-stock-analyzer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env    # then fill in your XTB credentials
```

`.env` is git-ignored — credentials never leave your machine. A **demo account is
enough** to download the instrument list; no real-money login is required.

```ini
XTB_USER_ID=1234567
XTB_PASSWORD=...
XTB_MODE=demo    # demo | real
```

## Usage

```bash
# download the universe, filter it, refresh data/instruments.csv
xtb-analyzer fetch

# inspect the raw payload to verify/tune the filter rules
xtb-analyzer inspect                 # from the last raw dump
xtb-analyzer inspect --live          # straight from the API

# work offline from the committed snapshot — no credentials needed
xtb-analyzer show --asset-class ETF
xtb-analyzer show --market PL --limit 0

# re-process an existing raw dump without hitting the API
xtb-analyzer fetch --from-raw data/raw/all_symbols.json

# keep the CFD rows too (debugging only)
xtb-analyzer fetch --keep-cfd

# stage 2: map the snapshot onto external tickers/FIGI
xtb-analyzer map                      # offline: adds the Yahoo Finance ticker per symbol
xtb-analyzer map --figi               # also resolves FIGIs via OpenFIGI (network)

# stage 3: fetch/refresh OHLCV history per mapped instrument
xtb-analyzer ohlcv                    # first run: full --range history; later runs: incremental
xtb-analyzer ohlcv --range 1y --symbols AAPL.US CDR.PL

# no XTB account? alternative, login-free universe: US-listed stocks via SEC EDGAR
xtb-analyzer fetch-sec
xtb-analyzer map --snapshot data/us_stocks.csv --output data/us_stocks_identity_map.csv
xtb-analyzer ohlcv --identity-map data/us_stocks_identity_map.csv --output-dir data/us_stocks_ohlcv
```

Sample output:

```
kept 3 of 11 records
  rejected      2  cfd-symbol-suffix
  rejected      1  cfd-in-text
  rejected      1  not-long-only
  rejected      1  category=IND

total: 3
by asset class: ETF=1, STOCK=2
by market:      US=1, PL=1, DE=1
```

## Identity mapping (stage 2)

`getAllSymbols` never returns a standardised external identifier, and every data
provider suffixes tickers differently, so mapping is split in two:

* **External tickers** — `xtb_analyzer/identity.py` reshapes `TICKER.MARKET` into the
  suffix Yahoo Finance expects (`CDR.PL` → `CDR.WA`, `IUSQ.DE` → `IUSQ.DE`, ...). Pure,
  offline, deterministic — no network involved.
* **FIGI, not ISIN** — `xtb_analyzer/openfigi.py` optionally resolves
  [FIGIs](https://www.openfigi.com/) through the OpenFIGI mapping API (`--figi`). An
  earlier version of this project assumed OpenFIGI's free tier returns an ISIN; running
  it live (2026-09-15) showed that's wrong — Bloomberg's licensing terms mean the free
  API only ever returns the FIGI itself, never the ISIN. Also verified live: the
  unauthenticated tier caps a request at **10** jobs (a batch of 100 gets `HTTP 413`) and
  is rate-limited tightly enough that mapping a large universe takes a while — see
  `docs/PROGRESS.md`. The market → exchange-code table is still not fully verified for
  every market — check a few known tickers before trusting one blindly, same discipline
  as the open questions in `docs/xtb-api-notes.md`.

## Market data (stage 3)

`xtb_analyzer/market_data.py` pulls OHLCV bars from Yahoo Finance's public chart
endpoint, keyed off the `yahoo_symbol` column of `data/identity_map.csv`. One CSV per
instrument under `data/ohlcv/<yahoo-ticker>.csv`:

* **First run** for a symbol fetches a full `--range` window (default `5y`).
* **Later runs** fetch only bars newer than the last stored date (`period1`/`period2`)
  and merge them in — the incremental refresh from the roadmap. A date already on disk
  is overwritten by the freshly-fetched bar, since Yahoo commonly restates the most
  recent session or two as a trading day closes out.
* Instruments with no `yahoo_symbol` (stage 2 couldn't map their market) are skipped,
  not guessed; a failed fetch for one symbol is logged and skipped, not fatal to the run.

The endpoint is undocumented — same caution as `openfigi.py`'s exchange-code table:
useful, unofficial, can change shape without notice. Verified live: works fine with a
descriptive `User-Agent` and the default throttle; an empty/generic `User-Agent` gets a
`429` even at a low request rate.

## No XTB account? `fetch-sec` — a login-free alternative universe

`xtb-analyzer fetch` needs XTB credentials (a free demo account is enough, but still an
account). `xtb_analyzer/sec_edgar.py` is a fallback that needs **no account and no API
key at all**: it pulls the SEC's public `company_tickers.json`
(<https://www.sec.gov/files/company_tickers.json>), which lists every US-listed
company with an active ticker — only a descriptive `User-Agent` is required, per SEC's
fair-use policy.

```bash
xtb-analyzer fetch-sec   # -> data/us_stocks.csv, data/us_stocks.meta.json
```

Worth knowing before treating this as equivalent to the real XTB universe:

* **US-listed common stock (and ETFs mixed in) only** — none of the other markets XTB
  covers (PL, DE, UK, ...), and SEC's file doesn't distinguish an operating company from
  a fund, so every row comes through as `asset_class=STOCK` even where the ticker is
  really an ETF (e.g. `AAAU.US`, a gold ETF).
* No CFD noise to filter — SEC only lists real issuers, so nothing here is rejected.
* No leverage/margin/long-only fields — those are XTB account concepts; they're `None`
  here, same tolerant handling `Instrument.from_record` already gives any record with
  missing fields.
* **SEC rate-limits fairly aggressively** even for compliant requests (`HTTP 429
  Request Rate Threshold Exceeded`) — seen firsthand fetching the live data committed in
  this repo; a shared egress IP (e.g. a shared cloud sandbox) makes it worse. Space out
  repeated runs.

`map` and `ohlcv` work unchanged against this alternative universe — just point
`--snapshot`/`--identity-map`/`--output-dir` at the `us_stocks*` paths, as in the
Usage section above.

## Outputs

| Path | Committed | Contents |
|------|-----------|----------|
| `data/raw/all_symbols.json` | no (git-ignored) | untouched `getAllSymbols` payload |
| `data/instruments.csv` | yes | the filtered universe — the offline fallback source |
| `data/instruments.meta.json` | yes | fetch timestamp, counts, rejection breakdown |
| `data/identity_map.csv` | yes | symbol -> Yahoo Finance ticker, and FIGI when `--figi` was used |
| `data/ohlcv/<ticker>.csv` | yes | OHLCV bar history per instrument, incrementally refreshed |
| `data/us_stocks.csv` + `.meta.json` | yes | `fetch-sec`'s login-free alternative universe (US-listed stocks) |
| `data/us_stocks_identity_map.csv` | yes | identity map for the `us_stocks` universe |
| `data/us_stocks_ohlcv/<ticker>.csv` | yes | OHLCV history for the 50 largest `us_stocks` companies (by SEC's own ordering) |

`data/instruments.csv` doubles as the **fallback**: `xtb-analyzer show` and any later
analysis step can run from it with no XTB login at all. Commit it after each refresh
so the repo always carries a working universe. `data/instruments.csv` and
`data/identity_map.csv` are still empty — no XTB credentials have been available in any
session so far; `data/us_stocks*` is real, live-fetched data from the login-free path.

## Project layout

```
src/xtb_analyzer/
  config.py      credentials + paths, loaded from .env
  xtb_client.py  minimal xAPI WebSocket client (login / getAllSymbols / logout)
  models.py      Instrument dataclass, symbol parsing (ticker + market)
  filters.py     cash-equity/ETF rules with per-rule rejection reasons
  identity.py    stage 2: offline symbol -> Yahoo Finance ticker mapping
  openfigi.py    stage 2: optional FIGI lookup via the OpenFIGI API (network)
  market_data.py stage 3: OHLCV bars via Yahoo Finance, incremental merge
  sec_edgar.py   login-free alternative universe: US-listed stocks via SEC EDGAR
  storage.py     CSV snapshot, identity map, OHLCV, metadata, raw dump I/O
  cli.py         fetch / fetch-sec / inspect / show / map / ohlcv
tests/           pytest suite driven by a fixture payload — runs without an XTB account
docs/            API notes and progress log
```

## Development

```bash
pytest            # 62 tests, no network or credentials required
ruff check .
ruff format .
```

CI runs the same three commands on every push and pull request.

## Roadmap

- [x] **1. Instrument universe** — fetch, filter to cash stocks + ETFs/ETNs, snapshot
- [x] **2. Identity mapping** — map XTB symbols to FIGI / external data-provider tickers
- [x] **3. Market data** — OHLCV history per instrument, incremental refresh, local store
- [ ] **4. Fundamentals** — valuation, profitability, growth, balance-sheet metrics
- [ ] **5. Technicals** — trend, momentum, volatility indicators
- [ ] **6. Scoring** — combine into a transparent buy / sell / hold verdict with rationale
- [ ] **7. Portfolio view** — overlay actual XTB holdings and report per-position condition

See `docs/PROGRESS.md` for the running log.

## Disclaimer

A personal research project. Nothing it produces is investment advice, and the
buy/sell/hold output is a mechanical score — not a recommendation. XTB is not
affiliated with this project.

## License

MIT — see [LICENSE](LICENSE).
