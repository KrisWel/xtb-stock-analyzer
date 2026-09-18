# xtb-stock-analyzer

Building blocks for a personal tool that tracks every instrument available on an
**XTB** account and scores each ticker as **buy / sell / hold** based on company
fundamentals, history and technical indicators.

> **Status: stage 6 of the roadmap.** The project downloads the full XTB instrument
> universe and reduces it to **cash equities and ETFs/ETNs only** (derivatives —
> stock CFDs, index CFDs, FX, commodities, crypto — are deliberately excluded), maps
> each surviving symbol onto a Yahoo Finance ticker and, optionally, a FIGI, pulls and
> incrementally refreshes OHLCV history per instrument, fetches raw company
> fundamentals where a free source has them, computes trend/momentum/volatility
> indicators from the stored OHLCV, and combines those into a transparent buy / hold /
> sell verdict with a plain-English rationale. No XTB account available? Two login-free
> alternative universes cover the rest of the pipeline unchanged: `fetch-sec` (US-listed
> stocks via SEC EDGAR) and `fetch-gpw` (PLN-denominated stocks + ETFs on the Warsaw
> Stock Exchange) — see below. **Every session tries to refresh as much of the GPW
> universe as possible — see `CLAUDE.md`.**

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
xtb-analyzer fetch-sec   # also writes data/us_stocks_cik.csv, the symbol -> CIK sidecar stage 4 needs
xtb-analyzer map --snapshot data/us_stocks.csv --output data/us_stocks_identity_map.csv
xtb-analyzer ohlcv --identity-map data/us_stocks_identity_map.csv --output-dir data/us_stocks_ohlcv

# stage 4: raw fundamentals per company via SEC EDGAR XBRL (us_stocks universe only)
xtb-analyzer fundamentals
xtb-analyzer fundamentals --symbols AAPL.US MSFT.US

# another login-free alternative universe: PLN-denominated stocks + ETFs on GPW
xtb-analyzer fetch-gpw   # also writes data/gpw_isin.csv (real ISINs, straight from GPW)
xtb-analyzer map --snapshot data/gpw_instruments.csv --output data/gpw_identity_map.csv --figi
xtb-analyzer ohlcv --identity-map data/gpw_identity_map.csv --output-dir data/gpw_ohlcv

# stage 5: trend/momentum/volatility indicators from stored OHLCV (any universe)
xtb-analyzer technicals --ohlcv-dir data/gpw_ohlcv --output data/gpw_technicals.csv

# stage 6: combine technicals (+ fundamentals, when available) into a verdict
xtb-analyzer score --technicals data/gpw_technicals.csv --output data/gpw_scores.csv
xtb-analyzer score --technicals data/us_stocks_technicals.csv \
  --fundamentals data/us_stocks_fundamentals.csv \
  --identity-map data/us_stocks_identity_map.csv \
  --output data/us_stocks_scores.csv
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

## Fundamentals (stage 4, `us_stocks` universe only)

`xtb_analyzer/fundamentals.py` pulls each company's own structured financial data
straight from its SEC filings — the free, no-login, no-API-key
`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` endpoint — keyed by the CIK
`fetch-sec` already writes to `data/us_stocks_cik.csv`. It's a fallback for the same
reason `sec_edgar.py` is: no XTB account has been available in any session, and this
needs none either.

```bash
xtb-analyzer fundamentals
```

* **Duration figures** (revenue, net income, gross profit, diluted EPS) use the most
  recent full fiscal year from a 10-K, plus the prior FY for a simple year-over-year
  growth figure.
* **Balance-sheet figures** (total assets, total liabilities, stockholders' equity) use
  whichever filing is most recent — a balance sheet is a snapshot, not a period.
* Not every filer tags the same line item under the same US GAAP concept name (taxonomy
  migrations, company-specific choices), so each metric tries a short list of concept
  names. **Verified live and fixed once already**: naively taking the *first present*
  concept name is wrong — Apple's facts still carry the legacy `Revenues` concept
  (stale since FY2018, when it adopted ASC 606) alongside the current
  `RevenueFromContractWithCustomerExcludingAssessedTax`; picking whichever is *present*
  paired a seven-year-stale revenue with a fresh net income. `fundamentals.py` compares
  every candidate concept's recency and keeps the most current one — see the regression
  test in `tests/test_fundamentals.py` and `docs/PROGRESS.md`.
* Stores raw filed numbers, not ratios — `Fundamentals.net_margin`, `.gross_margin`,
  `.revenue_growth`, `.net_income_growth`, `.liabilities_to_equity` compute them on
  demand so the CSV and the computation can't drift apart.
* **SEC's bot detection is stricter than its published rate limit, and can outlast a
  well-behaved throttle.** A sequential 50-request run at 1 request/second — under the
  documented 10 req/s cap — got flagged `"Your Request Originates from an Undeclared
  Automated Tool"`, a harsher, IP-reputation-based block than the ordinary `429`. It
  held even after a 12-minute cooldown with zero further requests, which points at the
  block being scoped to a **shared egress IP** (other tenants of the same cloud sandbox
  keeping the aggregate rate up) rather than this session's own history. Bulk-fetching
  `us_stocks_fundamentals.csv` is realistically a job for a machine with its own,
  unshared IP — see `docs/PROGRESS.md` for the full account.

## Another login-free universe: `fetch-gpw` — PLN stocks + ETFs on GPW

`xtb_analyzer/gpw.py` covers the Warsaw Stock Exchange's Main Market
(**Główny Rynek**) — every PLN-denominated stock and ETF quoted there, no account, no
API key, two requests total:

* **Stocks** — a GET to `gpw.pl/spolki?limit=1000&offset=0` returns the whole company
  list (ticker, name, ISIN) server-rendered in one page. Verified live (2026-09-17):
  402 companies, one request.
* **ETFs** — a POST to `gpw.pl/ajaxindex.php` (`action=GPWQuotationsETF&start=ajaxList
  &page=etfy`, the same call the site's own `/etfy` search form makes) returns every
  GPW-listed ETF, including foreign-domiciled ones cross-listed and quoted on GPW in
  PLN — a DAX tracker, an S&P 500 tracker, etc. Verified live: 40 ETFs, ISIN and
  currency both explicit in the response, every one PLN.

```bash
xtb-analyzer fetch-gpw   # -> data/gpw_instruments.csv, data/gpw_isin.csv
```

* **Every Główny Rynek equity is PLN-denominated, even foreign issuers** — verified
  live via Yahoo Finance: AmRest (a Spanish ISIN) trades as `EAT.WA` in PLN, same as
  any Polish-domiciled company.
* Real **ISIN**, not just a ticker — GPW's own pages give it directly, so this universe
  doesn't need OpenFIGI's FIGI at all for that (though `map --figi` still works the same
  way as any other universe, if wanted alongside).
* Both `gpw.pl` endpoints are undocumented HTML/AJAX internals, not a public API — same
  caution as `market_data.py`'s Yahoo endpoint and `openfigi.py`'s exchange-code table.
  **Verified live and fixed once already** (2026-09-18): GPW marks a suspended/newly
  listed ETN's status with plain text (`/Z`) appended straight into the ticker's `<b>`
  tag, not its own markup — `parse_etfs` now strips it (`gpw.py::_clean_etf_ticker`)
  instead of building a broken Yahoo symbol from it; see `docs/PROGRESS.md`.
* Unlike the US/SEC universe (10k+ symbols, deliberately scoped down for `ohlcv`), the
  GPW universe (~440 instruments) is small enough that a **full** OHLCV backfill
  completes in one sitting — see `CLAUDE.md` for the standing instruction to do exactly
  that every session.

`map` and `ohlcv` work unchanged against this universe too — point `--snapshot` /
`--identity-map` / `--output-dir` at the `gpw_*` paths, as in Usage above.

## Technical indicators (stage 5)

`xtb_analyzer/technicals.py` computes trend, momentum and volatility indicators purely
from OHLCV bars already on disk — no network, works against any of the OHLCV
directories the project produces.

```bash
xtb-analyzer technicals --ohlcv-dir data/gpw_ohlcv --output data/gpw_technicals.csv
```

One row per instrument, the **latest** value of each indicator (not a full time
series — see the module docstring if a per-bar series is ever needed, the
`*_series` functions underneath already compute one):

| Indicator | Kind | Notes |
|---|---|---|
| SMA 20 / 50 / 200 | trend | simple moving average; 200 needs 200 bars of history |
| EMA 12 / 26 | trend | exponential moving average, seeded with the SMA |
| RSI 14 | momentum | Wilder's original smoothing (not a plain EMA) |
| MACD (12/26/9) + signal + histogram | trend/momentum | standard MACD |
| Bollinger Bands (20, 2σ) | volatility | SMA 20 ± 2 sample standard deviations |
| ATR 14 | volatility | Wilder-smoothed average true range |

Instruments with fewer than 20 bars of history are skipped entirely (nothing here means
anything with less); an instrument with, say, 60 bars still gets SMA 20/50, RSI, MACD
and Bollinger values — SMA 200 just stays `None` until there's enough history.

## Scoring (stage 6)

`xtb_analyzer/scoring.py` combines a `Technicals` row (and, when available, a matching
`Fundamentals` row) into one auditable **BUY / HOLD / SELL** verdict with a
plain-English rationale — a deliberately rule-based approach, not a black-box model, so
every verdict can be explained by listing exactly which signals fired.

```bash
xtb-analyzer score --technicals data/gpw_technicals.csv --output data/gpw_scores.csv

# blend in fundamentals where they exist (currently us_stocks only) via the identity
# map that bridges fundamentals' XTB-style symbol to technicals' Yahoo ticker
xtb-analyzer score --technicals data/us_stocks_technicals.csv \
  --fundamentals data/us_stocks_fundamentals.csv \
  --identity-map data/us_stocks_identity_map.csv \
  --output data/us_stocks_scores.csv
```

Two independent sub-scores, each normalised onto the same `-100..100` scale so they're
comparable regardless of how many of their inputs an instrument actually has data for:

* **Technical score** — trend (price vs SMA 20/50/200), momentum (RSI, MACD) and
  mean-reversion (Bollinger Bands). Works for every instrument with enough OHLCV
  history, in any universe — this is the only score GPW instruments get today.
* **Fundamental score** — profitability (net margin), growth (revenue YoY) and
  balance-sheet risk (liabilities/equity). Only computed where a `Fundamentals` row
  exists for that symbol; currently that's the `us_stocks` universe (and even there,
  only 1 company so far — see `docs/PROGRESS.md`).

The **composite score** blends the two — 40% fundamentals, 60% technicals — when a
fundamentals row is available, and falls back to the technical score alone otherwise
(`--fundamentals` and `--identity-map` are both optional). `verdict` is `BUY` at
composite >= 40, `SELL` at <= -40, `HOLD` in between; `rationale` lists every signal
that fired, e.g. `"price above SMA200 (long-term uptrend); RSI oversold (18.2 < 30);
strong net margin (26.9% > 15%)"`.

**Why GPW instruments are technicals-only for now**: GPW-listed companies report to
the KNF/ESPI system, not SEC's XBRL — no free, structured fundamentals source for them
has been found yet (an open question tracked in `docs/PROGRESS.md`). `score` still runs
against the full GPW universe; it's just working from a smaller, purely technical set
of signals until that gap is closed.

## Outputs

| Path | Committed | Contents |
|------|-----------|----------|
| `data/raw/all_symbols.json` | no (git-ignored) | untouched `getAllSymbols` payload |
| `data/instruments.csv` | yes | the filtered universe — the offline fallback source |
| `data/instruments.meta.json` | yes | fetch timestamp, counts, rejection breakdown |
| `data/identity_map.csv` | yes | symbol -> Yahoo Finance ticker, and FIGI when `--figi` was used |
| `data/ohlcv/<ticker>.csv` | yes | OHLCV bar history per instrument, incrementally refreshed |
| `data/us_stocks.csv` + `.meta.json` | yes | `fetch-sec`'s login-free alternative universe (US-listed stocks) |
| `data/us_stocks_cik.csv` | yes | symbol -> SEC CIK sidecar, written by `fetch-sec` |
| `data/us_stocks_identity_map.csv` | yes | identity map for the `us_stocks` universe |
| `data/us_stocks_ohlcv/<ticker>.csv` | yes | OHLCV history for the 50 largest `us_stocks` companies (by SEC's own ordering) |
| `data/us_stocks_fundamentals.csv` | yes | raw fundamentals per company, via SEC EDGAR XBRL (partial — see `docs/PROGRESS.md`) |
| `data/us_stocks_technicals.csv` | yes | latest trend/momentum/volatility indicators for the `us_stocks` universe |
| `data/us_stocks_scores.csv` | yes | buy/hold/sell verdicts for `us_stocks`, technicals + fundamentals blended where both exist |
| `data/gpw_instruments.csv` + `.meta.json` | yes | `fetch-gpw`'s login-free universe (PLN stocks + ETFs on GPW) |
| `data/gpw_isin.csv` | yes | symbol -> real ISIN sidecar, straight from GPW |
| `data/gpw_identity_map.csv` | yes | identity map for the `gpw` universe (Yahoo ticker + FIGI) |
| `data/gpw_ohlcv/<ticker>.csv` | yes | OHLCV history for the `gpw` universe — full coverage, not a subset |
| `data/gpw_technicals.csv` | yes | latest trend/momentum/volatility indicators for the `gpw` universe |
| `data/gpw_scores.csv` | yes | buy/hold/sell verdicts for `gpw`, technicals-only (no free GPW fundamentals source yet) |

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
  fundamentals.py stage 4: raw company fundamentals via SEC EDGAR XBRL
  gpw.py         login-free alternative universe: PLN stocks + ETFs on GPW
  technicals.py  stage 5: trend/momentum/volatility indicators from stored OHLCV
  scoring.py     stage 6: technicals (+ fundamentals) -> buy/hold/sell verdict + rationale
  storage.py     CSV snapshot, identity map, OHLCV, fundamentals, technicals, scores I/O
  cli.py         fetch / fetch-sec / fetch-gpw / inspect / show / map / ohlcv /
                 fundamentals / technicals / score
tests/           pytest suite driven by a fixture payload — runs without an XTB account
docs/            API notes and progress log
```

## Development

```bash
pytest            # 124 tests, no network or credentials required
ruff check .
ruff format .
```

CI runs the same three commands on every push and pull request.

## Roadmap

- [x] **1. Instrument universe** — fetch, filter to cash stocks + ETFs/ETNs, snapshot
- [x] **2. Identity mapping** — map XTB symbols to FIGI / external data-provider tickers
- [x] **3. Market data** — OHLCV history per instrument, incremental refresh, local store
- [x] **4. Fundamentals** — valuation, profitability, growth, balance-sheet metrics
- [x] **5. Technicals** — trend, momentum, volatility indicators
- [x] **6. Scoring** — combine into a transparent buy / sell / hold verdict with rationale
- [ ] **7. Portfolio view** — overlay actual XTB holdings and report per-position condition

See `docs/PROGRESS.md` for the running log.

## Disclaimer

A personal research project. Nothing it produces is investment advice, and the
buy/sell/hold output is a mechanical score — not a recommendation. XTB is not
affiliated with this project.

## License

MIT — see [LICENSE](LICENSE).
