# XTB xStation5 API (xAPI) — working notes

Reference: <http://developers.xstore.pro/documentation/>

## Transport

* WebSocket, one JSON object per frame.
  * demo: `wss://ws.xtb.com/demo`
  * real: `wss://ws.xtb.com/real`
* Request: `{"command": "<name>", "arguments": {...}}`
* Response: `{"status": true, "returnData": ...}` or
  `{"status": false, "errorCode": "...", "errorDescr": "..."}`
* Rate limit: **max 1 request per 200 ms**, max 50 queued. The client keeps 250 ms
  between commands (`MIN_REQUEST_INTERVAL_S`).
* The session drops after ~15 min of inactivity; long jobs must re-login.
* A **demo account works** for `getAllSymbols` — no real-money login needed.

## Commands used

| Command | Purpose |
|---------|---------|
| `login` | `{userId, password, appName}` → `streamSessionId` |
| `getAllSymbols` | full instrument list (several MB, ~10k+ records) |
| `getServerTime` | connectivity check |
| `getTrades` | `{openedOnly}` → open positions (stage 7) — **not verified live**, see below |
| `logout` | clean session close |

## Fields of a symbol record that matter here

| Field | Notes |
|-------|-------|
| `symbol` | `AAPL.US`, `CDR.PL`, `IUSQ.DE`; a `_<digits>` suffix marks a CFD variant |
| `categoryName` | `STC` stocks, `ETF` ETFs/ETNs, `IND` indices, `FX`, `CMD`, `CRT` crypto |
| `groupName` | venue/product grouping; sometimes spells out "CFD" |
| `description` | issuer name — the human-readable label |
| `currency` / `currencyProfit` | quote currency |
| `leverage` | **100 means full margin, i.e. no leverage** — the cash-instrument marker |
| `longOnly` | `true` for cash shares at XTB (no shorting) |
| `shortSelling` | mirror of the above for derivatives |
| `marginMode` / `profitMode` / `type` | product plumbing; kept for later analysis |
| `contractSize`, `precision` | 1 and 2 for most cash shares |

## Open questions to verify against live data

These drive the thresholds in `filters.py` and should be re-checked with
`xtb-analyzer inspect` on a real payload:

1. Do **all** cash shares really report `leverage == 100`, or do some markets differ?
2. Are ETNs published under `categoryName == "ETF"` or under a separate code?
3. Is the `_<digits>` symbol suffix used consistently for every CFD shadow?
4. Does `groupName` carry a stable venue code that can replace the symbol-suffix parsing?

If the answer to any of these turns out to be "no", loosen the corresponding rule in
`FilterConfig` rather than hard-coding an exception.

## `getTrades` (stage 7) — not verified live

No session so far has had XTB credentials, so `xtb_client.py::get_trades` has never
run against a real response. The shape below is taken from xAPI's published
documentation, not confirmed against live data:

| Field | Notes |
|-------|-------|
| `symbol` | same `TICKER.MARKET` shape as `getAllSymbols` |
| `cmd` | numeric trade direction; `0` = BUY, `1` = SELL (`portfolio.py`'s `TRADE_CMD_*`) |
| `volume` | position size, in the instrument's own units (shares for cash equities) |
| `open_price` | average entry price |

Before trusting this against a real account: confirm `cmd`'s numeric codes for a cash
equity specifically (xAPI's docs list more trade-direction codes for derivatives that
shouldn't apply to a long-only stock/ETF position), and confirm `open_price` is in the
instrument's quote currency (matching what `market_data.py`'s OHLCV close is in) rather
than the account's deposit currency — `portfolio.py::build_portfolio_row` assumes they
match.
