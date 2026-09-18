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
| `us_stocks_technicals.csv` | yes | `xtb-analyzer technicals` — latest trend/momentum/volatility indicators, `us_stocks` universe |
| `us_stocks_scores.csv` | yes | `xtb-analyzer score` — buy/hold/sell verdicts for `us_stocks`, technicals + fundamentals blended where both exist |
| `gpw_instruments.csv` + `.meta.json` | yes | `xtb-analyzer fetch-gpw` — login-free alternative universe (PLN stocks + ETFs, GPW) |
| `gpw_isin.csv` | yes | `xtb-analyzer fetch-gpw` — symbol -> real ISIN sidecar, straight from GPW |
| `gpw_identity_map.csv` | yes | identity map for the `gpw` universe (Yahoo ticker + FIGI) |
| `gpw_ohlcv/<ticker>.csv` | yes | OHLCV history for the `gpw` universe — full coverage (438/442 symbols) |
| `gpw_technicals.csv` | yes | `xtb-analyzer technicals` — latest trend/momentum/volatility indicators, `gpw` universe |
| `gpw_scores.csv` | yes | `xtb-analyzer score` — buy/hold/sell verdicts for `gpw`, technicals-only (no free GPW fundamentals source yet) |
| `raw/all_symbols.json` | **no** (git-ignored) | `xtb-analyzer fetch` — untouched API payload, several MB |

`instruments.csv` and `identity_map.csv` are still empty — every session so far has
lacked XTB credentials. `us_stocks*` and `gpw*` are real, live data fetched via the
login-free paths (see the README's "No XTB account?" and "Another login-free universe"
sections) — **every session tries to keep the `gpw*` files fresh, see `CLAUDE.md`**.
Has an XTB demo account become available? Run `xtb-analyzer fetch` and commit the
refreshed `instruments.csv` / `instruments.meta.json` so the repository carries the real
XTB universe too. Run `xtb-analyzer map` afterwards (and commit `identity_map.csv`) to
refresh the external-ticker mapping the same way. Then `xtb-analyzer ohlcv` to
fetch/refresh the bar history in `ohlcv/` — safe to re-run often, since it only pulls
bars newer than what's already on disk per symbol.
