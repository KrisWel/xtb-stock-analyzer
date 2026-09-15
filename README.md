# xtb-stock-analyzer

Building blocks for a personal tool that tracks every instrument available on an
**XTB** account and — later — scores each ticker as **buy / sell / hold** based on
company fundamentals, history and technical indicators.

> **Status: stage 3 of the roadmap.** The project downloads the full XTB instrument
> universe and reduces it to **cash equities and ETFs/ETNs only** (derivatives —
> stock CFDs, index CFDs, FX, commodities, crypto — are deliberately excluded), maps
> each surviving symbol onto a Yahoo Finance ticker and, optionally, an ISIN, then
> pulls and incrementally refreshes OHLCV history per instrument.

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

# stage 2: map the snapshot onto external tickers/ISIN
xtb-analyzer map                      # offline: adds the Yahoo Finance ticker per symbol
xtb-analyzer map --isin               # also resolves ISINs via OpenFIGI (network, unverified)

# stage 3: fetch/refresh OHLCV history per mapped instrument
xtb-analyzer ohlcv                    # first run: full --range history; later runs: incremental
xtb-analyzer ohlcv --range 1y --symbols AAPL.US CDR.PL
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

`getAllSymbols` never returns an ISIN, and every data provider suffixes tickers
differently, so mapping is split in two:

* **External tickers** — `xtb_analyzer/identity.py` reshapes `TICKER.MARKET` into the
  suffix Yahoo Finance expects (`CDR.PL` → `CDR.WA`, `IUSQ.DE` → `IUSQ.DE`, ...). Pure,
  offline, deterministic — no network involved.
* **ISIN** — `xtb_analyzer/openfigi.py` optionally resolves ISINs through the
  [OpenFIGI](https://www.openfigi.com/api) mapping API (`--isin`). Its market →
  exchange-code table is assembled from public references and **not yet verified**
  against a live snapshot — check a few known tickers before trusting a market's
  mapping blindly, the same discipline as the open questions in
  `docs/xtb-api-notes.md`.

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
useful, unofficial, can change shape without notice.

## Outputs

| Path | Committed | Contents |
|------|-----------|----------|
| `data/raw/all_symbols.json` | no (git-ignored) | untouched `getAllSymbols` payload |
| `data/instruments.csv` | yes | the filtered universe — the offline fallback source |
| `data/instruments.meta.json` | yes | fetch timestamp, counts, rejection breakdown |
| `data/identity_map.csv` | yes | symbol -> Yahoo Finance ticker, and ISIN when `--isin` was used |
| `data/ohlcv/<ticker>.csv` | yes | OHLCV bar history per instrument, incrementally refreshed |

`data/instruments.csv` doubles as the **fallback**: `xtb-analyzer show` and any later
analysis step can run from it with no XTB login at all. Commit it after each refresh
so the repo always carries a working universe.

## Project layout

```
src/xtb_analyzer/
  config.py      credentials + paths, loaded from .env
  xtb_client.py  minimal xAPI WebSocket client (login / getAllSymbols / logout)
  models.py      Instrument dataclass, symbol parsing (ticker + market)
  filters.py     cash-equity/ETF rules with per-rule rejection reasons
  identity.py    stage 2: offline symbol -> Yahoo Finance ticker mapping
  openfigi.py    stage 2: optional ISIN lookup via the OpenFIGI API (network)
  market_data.py stage 3: OHLCV bars via Yahoo Finance, incremental merge
  storage.py     CSV snapshot, identity map, OHLCV, metadata, raw dump I/O
  cli.py         fetch / inspect / show / map / ohlcv
tests/           pytest suite driven by a fixture payload — runs without an XTB account
docs/            API notes and progress log
```

## Development

```bash
pytest            # 56 tests, no network or credentials required
ruff check .
ruff format .
```

CI runs the same three commands on every push and pull request.

## Roadmap

- [x] **1. Instrument universe** — fetch, filter to cash stocks + ETFs/ETNs, snapshot
- [x] **2. Identity mapping** — map XTB symbols to ISIN / external data-provider tickers
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
