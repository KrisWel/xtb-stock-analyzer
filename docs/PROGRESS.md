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
