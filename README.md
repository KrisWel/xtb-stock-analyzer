# xtb-stock-analyzer

Building blocks for a personal tool that tracks every instrument available on an
**XTB** account and — later — scores each ticker as **buy / sell / hold** based on
company fundamentals, history and technical indicators.

> **Status: stage 1 of the roadmap.** Right now the project does one thing well:
> it downloads the full XTB instrument universe and reduces it to **cash equities
> and ETFs/ETNs only**. Derivatives (stock CFDs, index CFDs, FX, commodities,
> crypto) are deliberately excluded — the analysis layer is meant for companies
> and funds, not leveraged contracts.

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

## Outputs

| Path | Committed | Contents |
|------|-----------|----------|
| `data/raw/all_symbols.json` | no (git-ignored) | untouched `getAllSymbols` payload |
| `data/instruments.csv` | yes | the filtered universe — the offline fallback source |
| `data/instruments.meta.json` | yes | fetch timestamp, counts, rejection breakdown |

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
  storage.py     CSV snapshot, metadata, raw dump I/O
  cli.py         fetch / inspect / show
tests/           pytest suite driven by a fixture payload — runs without an XTB account
docs/            API notes and progress log
```

## Development

```bash
pytest            # 27 tests, no network or credentials required
ruff check .
ruff format .
```

CI runs the same three commands on every push and pull request.

## Roadmap

- [x] **1. Instrument universe** — fetch, filter to cash stocks + ETFs/ETNs, snapshot
- [ ] **2. Identity mapping** — map XTB symbols to ISIN / external data-provider tickers
- [ ] **3. Market data** — OHLCV history per instrument, incremental refresh, local store
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
