# Progress log

## 2026-09-09 — stage 1: instrument universe

**Done**

* Minimal xAPI WebSocket client: `login` / `getAllSymbols` / `getServerTime` / `logout`,
  request throttling, typed API errors, context-manager lifecycle.
* `Instrument` model: normalised record, symbol split into ticker + market code,
  market-code → venue mapping, tolerant type coercion for missing fields.
* Cash-equity/ETF filter with five independent, switchable rules and a per-rule
  rejection counter (see the table in the README).
* Storage layer: raw JSON dump (git-ignored), committed CSV snapshot with a
  lossless round trip, metadata file with counts and rejection breakdown.
* CLI: `fetch`, `inspect`, `show` — `--from-raw` re-processes a dump without hitting
  the API, `--keep-cfd` disables the derivative rules for debugging.
* 27 pytest tests running off a fixture payload — no XTB account or network needed.
* GitHub Actions CI: ruff lint, format check, pytest on Python 3.10–3.12.

**Not done yet**

* `data/instruments.csv` is empty until the first `xtb-analyzer fetch` on a machine
  that can reach `ws.xtb.com` — commit the generated snapshot to activate the
  offline fallback.
* The filter thresholds are reasoned from the API docs, not yet confirmed against a
  live payload. Run `xtb-analyzer inspect --live` first and check the open questions
  in `docs/xtb-api-notes.md`.

**Next**

* Stage 2: map XTB symbols to ISIN / external provider tickers so market data and
  fundamentals can be pulled per instrument.

## 2026-09-09 — stage 2: identity mapping

**Done**

* `identity.py`: offline, deterministic `TICKER.MARKET` -> Yahoo Finance ticker
  mapping (`CDR.PL` -> `CDR.WA`, `IUSQ.DE` -> `IUSQ.DE`, ...). No network needed.
* `openfigi.py`: optional ISIN lookup via the OpenFIGI mapping API — injectable
  HTTP layer for unit testing, batching (100 jobs/request), throttling, and a
  market -> Bloomberg-style exchange-code table for the `TICKER + exchCode` job
  type.
* `xtb-analyzer map` CLI command: reads the committed snapshot (no credentials
  needed), writes `data/identity_map.csv`; `--isin` additionally hits OpenFIGI.
* Storage round-trip (`write_identity_map` / `read_identity_map`) and 16 new
  tests — 43 total, still no network or credentials required to run the suite.

**Not done yet**

* The OpenFIGI exchange-code table in `openfigi.py` is assembled from public
  references and has **not been checked against a live payload** — run
  `xtb-analyzer map --isin` once network + an XTB fetch are available and spot
  check a handful of well-known ISINs (e.g. `AAPL.US` -> `US0378331005`) before
  trusting a market's mapping.
* `data/identity_map.csv` is empty until `xtb-analyzer fetch` then `map` run on
  a machine that can reach both `ws.xtb.com` and (for `--isin`) `api.openfigi.com`.

**Next**

* Stage 3: OHLCV market data per instrument, incremental refresh, local store —
  keyed off the Yahoo Finance ticker from `identity_map.csv`.

## 2026-09-15 — stage 3: market data

**Done**

* `market_data.py`: `YahooChartClient` wraps Yahoo Finance's public
  `/v8/finance/chart/{symbol}` endpoint — injectable HTTP layer for tests, a
  throttle (undocumented endpoint, no published rate limit), and a parser that
  skips null sessions (holidays/gaps) instead of crashing on them.
* `merge_bars`: incremental-refresh logic — combines a stored history with
  freshly-fetched bars, sorted by date, with the new fetch winning on a
  collision (Yahoo commonly restates the last session or two as a trading day
  closes out).
* `xtb-analyzer ohlcv` CLI command: reads `data/identity_map.csv`, fetches a
  full `--range` window the first time per symbol and an incremental
  `period1`/`period2` window on every later run; one CSV per instrument under
  `data/ohlcv/<yahoo-ticker>.csv`. Instruments with no `yahoo_symbol` are
  skipped and logged, not guessed; a failed fetch for one symbol doesn't stop
  the run.
* Storage round-trip (`write_ohlcv` / `read_ohlcv`) and 13 new tests — 56
  total, still no network or credentials required to run the suite.

**Not done yet — and why**

* **No real data has been fetched in any stage yet.** `data/instruments.csv`,
  `data/identity_map.csv` and `data/ohlcv/` are still empty/absent — every
  stage so far has been developed and tested against the `tests/fixtures/`
  payload and injected fakes, in a sandbox whose egress policy denies
  `ws.xtb.com`, `query1.finance.yahoo.com` and `api.openfigi.com` outright
  (verified: `curl` to all three returns a 403 from the egress gateway, not a
  timeout), on top of there being no `.env` with XTB credentials there either.
  Run the pipeline for real on a machine with both — `xtb-analyzer fetch` →
  `map` → `ohlcv` — then commit the generated CSVs so the offline fallback
  (and the OpenFIGI/Yahoo-suffix tables) get their first live check.
* The Yahoo chart endpoint is undocumented — same caution as `openfigi.py`'s
  exchange-code table: verify the response shape and the null-session handling
  against a real payload before trusting it at scale.

**Next**

* Stage 4: fundamentals (valuation, profitability, growth, balance-sheet
  metrics) per instrument.

## 2026-09-15 — live network access, real data, and two corrections

The sandbox's egress policy was widened from "trusted" (npm/PyPI/GitHub/Anthropic
only) to full internet access, and this session's XTB credentials remain unavailable
(no demo account created). Both together mean: XTB itself is still unreachable in
practice, but Yahoo Finance, OpenFIGI and SEC EDGAR are — and running the existing
code against them for the first time surfaced two wrong assumptions from stage 2,
now fixed, plus a genuine, committed alternative data source.

**Corrections (verified live, both were wrong)**

* **OpenFIGI's free tier does not return ISIN.** `openfigi.py` assumed it did; a real
  `AAPL`/`US` mapping request returns `figi`, `compositeFIGI`, `shareClassFIGI`, etc.
  but no `isin` key — Bloomberg's licensing terms don't allow OpenFIGI to publish that
  crosswalk for free. Renamed the feature throughout: `IdentityMapping.isin` ->
  `.figi`, `OpenFigiClient.lookup_isins` -> `.lookup_figis`, CLI `map --isin` ->
  `map --figi`, CSV column `isin` -> `figi`.
* **The unauthenticated OpenFIGI tier caps a request at 10 jobs, not 100.** A batch of
  100 without an API key gets `HTTP 413`. `MAX_JOBS_PER_REQUEST` is now
  `MAX_JOBS_PER_REQUEST_ANONYMOUS = 10` / `_WITH_KEY = 100`, picked automatically by
  whether `OpenFigiClient` has an API key.

**Done**

* `sec_edgar.py`: login-free alternative universe (no account, no API key — just a
  descriptive `User-Agent` per SEC's fair-use policy) pulling
  `https://www.sec.gov/files/company_tickers.json`. `to_symbol_record` reshapes each
  entry into a `getAllSymbols`-like record so `filters.filter_instruments` and the rest
  of the pipeline handle it unchanged.
* New `xtb-analyzer fetch-sec` CLI command, writing `data/us_stocks.csv` /
  `.meta.json` — kept as separate files from the XTB-specific `instruments.csv` so the
  two universes are never conflated.
* 6 new tests (62 total), still no network or credentials required to run the suite.
* **Real, live-fetched data committed for the first time**, via the SEC/Yahoo/OpenFIGI
  path (XTB itself still needs credentials no session has had):
  - `data/us_stocks.csv` + `.meta.json` — **10,422 real US-listed tickers**, fetched
    live from SEC EDGAR.
  - `data/us_stocks_identity_map.csv` — Yahoo Finance ticker for all 10,421 mappable
    symbols (one `NONE.` placeholder ticker in SEC's own data has no market code to
    map), plus real FIGIs for the 50 largest companies (see below).
  - `data/us_stocks_ohlcv/*.csv` — 5 years of real daily OHLCV bars for the 50 largest
    companies by SEC's own ordering (NVDA, AAPL, GOOGL, MSFT, AMZN, ...), fetched live
    from Yahoo Finance.

**Not done yet — and why**

* **XTB's own universe is still empty.** Network access is no longer the blocker;
  credentials are — no XTB demo account has been created in any session. `fetch-sec`
  is a substitute for developing/testing against real data, not a replacement: it's
  US-only and has no ETF/CFD distinction (see the README's "No XTB account?" section).
* **FIGI is only backfilled for 50 of the 10,422 `us_stocks` symbols.** The
  unauthenticated OpenFIGI tier's real rate limit is tighter than its documented
  25-requests/6s in practice — a bulk run at the library's 0.3s throttle hit `HTTP 429`
  after roughly 70 requests (~22s), whether from this session's own pace or contention
  on the sandbox's shared egress IP. FIGI-backfilling the rest is a slow, patient
  background job (roughly 1,000+ throttled batches), not something to run unsupervised
  in one shot — left for later, at a more conservative pace or with an API key.
* **OHLCV is only fetched for those same 50 symbols**, not the full 10,422 — a
  deliberate choice, both to avoid hammering Yahoo's undocumented endpoint with ten
  thousand requests in one session and because it would take roughly 90 minutes at the
  existing 0.5s throttle. `xtb-analyzer ohlcv --identity-map
  data/us_stocks_identity_map.csv --output-dir data/us_stocks_ohlcv` (no `--symbols`)
  backfills the rest whenever someone's willing to let it run.
* SEC EDGAR's rate limiting is aggressive even for a single compliant request spaced
  reasonably — hit `HTTP 429 Request Rate Threshold Exceeded` twice while developing
  this, recovered within roughly a minute. Worth remembering before assuming a failure
  there is a bug rather than a cooldown.

**Next**

* Either populate the real XTB universe (an XTB demo account, created outside any
  Claude session, plus `fetch` → `map --figi` → `ohlcv` on a machine with both), or
  continue stage 4 (fundamentals) against the `us_stocks` universe already committed.
