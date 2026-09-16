# data/

| File | Committed | Written by |
|------|-----------|------------|
| `instruments.csv` | yes | `xtb-analyzer fetch` — the filtered universe, and the offline fallback for every other command |
| `instruments.meta.json` | yes | `xtb-analyzer fetch` — timestamp, counts, rejection breakdown |
| `identity_map.csv` | yes | `xtb-analyzer map` — symbol -> Yahoo Finance ticker (offline) and FIGI (`--figi`, network) |
| `ohlcv/<ticker>.csv` | yes | `xtb-analyzer ohlcv` — OHLCV bar history per instrument, incrementally refreshed |
| `us_stocks.csv` + `.meta.json` | yes | `xtb-analyzer fetch-sec` — login-free alternative universe (US-listed stocks, SEC EDGAR) |
| `us_stocks_cik.csv` | yes | `xtb-analyzer fetch-sec` — symbol -> SEC CIK sidecar, needed for `fundamentals` |
| `us_stocks_identity_map.csv` | yes | identity map for the `us_stocks` universe |
| `us_stocks_ohlcv/<ticker>.csv` | yes | OHLCV history for `us_stocks` (currently: the 50 largest companies) |
| `us_stocks_fundamentals.csv` | yes | `xtb-analyzer fundamentals` — raw fundamentals per company, SEC EDGAR XBRL (currently: 1 company — see `docs/PROGRESS.md`) |
| `raw/all_symbols.json` | **no** (git-ignored) | `xtb-analyzer fetch` — untouched API payload, several MB |

`instruments.csv` and `identity_map.csv` are still empty — every session so far has
lacked XTB credentials. `us_stocks*` is real, live data fetched via the login-free path
(see the README's "No XTB account?" section) — has an XTB demo account become available?
Run `xtb-analyzer fetch` and commit the refreshed `instruments.csv` / `instruments.meta.json`
so the repository carries the real XTB universe too. Run `xtb-analyzer map` afterwards
(and commit `identity_map.csv`) to refresh the external-ticker mapping the same way. Then
`xtb-analyzer ohlcv` to fetch/refresh the bar history in `ohlcv/` — safe to re-run often,
since it only pulls bars newer than what's already on disk per symbol.
