"""Stage 3: OHLCV market data per instrument, incrementally refreshed and stored locally.

Bars are pulled from Yahoo Finance's public chart endpoint (the same one behind
finance.yahoo.com and widely used by open-source tooling), keyed off the
``yahoo_symbol`` column of ``data/identity_map.csv`` (stage 2). Only symbols with a
resolved Yahoo ticker can be fetched — symbols XTB carries for a market
:mod:`xtb_analyzer.identity` doesn't map yet are skipped, not guessed.

The endpoint is undocumented and can change shape or start throttling aggressive
callers without notice; :class:`YahooChartClient` throttles itself and sends a
descriptive User-Agent, but treat a fetch failure here the same way as an XTB one —
log it and move on, don't retry-loop.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

#: Undocumented endpoint, no published rate limit — keep requests infrequent.
MIN_REQUEST_INTERVAL_S = 0.5

Getter = Callable[[str, dict[str, str]], bytes]


class YahooFinanceError(RuntimeError):
    """The chart endpoint failed or returned an unexpected shape."""


@dataclass(frozen=True)
class Bar:
    """One OHLCV daily (or coarser) bar."""

    date: str  # ISO date, e.g. "2026-09-12"
    open: float
    high: float
    low: float
    close: float
    volume: int

    @classmethod
    def csv_columns(cls) -> list[str]:
        return ["date", "open", "high", "low", "close", "volume"]

    def as_dict(self) -> dict[str, str]:
        return {
            "date": self.date,
            "open": repr(self.open),
            "high": repr(self.high),
            "low": repr(self.low),
            "close": repr(self.close),
            "volume": str(self.volume),
        }


class YahooChartClient:
    """Thin wrapper around the Yahoo Finance ``/v8/finance/chart`` endpoint.

    ``getter`` is injectable so the request/response plumbing can be unit tested
    without hitting the network — see ``tests/test_market_data.py``.
    """

    def __init__(self, getter: Getter | None = None) -> None:
        self._getter = getter or _urllib_get
        self._last_request_at = 0.0

    def get_bars(
        self,
        symbol: str,
        *,
        range_: str = "5y",
        interval: str = "1d",
        period1: int | None = None,
        period2: int | None = None,
    ) -> list[Bar]:
        """Fetch bars for ``symbol``.

        Pass ``period1``/``period2`` (unix seconds) for an incremental refresh window;
        omit them to fall back to ``range_`` (e.g. ``"1y"``, ``"5y"``, ``"max"``) for a
        first-time fetch.
        """
        params = {"interval": interval}
        if period1 is not None and period2 is not None:
            params["period1"] = str(period1)
            params["period2"] = str(period2)
        else:
            params["range"] = range_

        self._throttle()
        raw = self._getter(CHART_URL.format(symbol=urllib.parse.quote(symbol)), params)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YahooFinanceError(f"{symbol}: malformed response: {exc}") from exc

        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise YahooFinanceError(f"{symbol}: {chart['error']}")

        results = chart.get("result") or []
        if not results:
            raise YahooFinanceError(f"{symbol}: empty chart result")

        return _parse_result(symbol, results[0])

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()


def merge_bars(existing: list[Bar], new: list[Bar]) -> list[Bar]:
    """Combine a stored history with freshly-fetched bars, sorted by date.

    Newly-fetched bars win on a date collision — Yahoo commonly restates the most
    recent one or two sessions as a trading day closes out.
    """
    by_date = {bar.date: bar for bar in existing}
    for bar in new:
        by_date[bar.date] = bar
    return sorted(by_date.values(), key=lambda bar: bar.date)


def safe_filename(yahoo_symbol: str) -> str:
    """Sanitise a Yahoo ticker (``BRK-B``, ``CDR.WA``) into a safe CSV filename stem."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", yahoo_symbol)


def _parse_result(symbol: str, result: dict) -> list[Bar]:
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators", {}) or {}).get("quote") or [{}]
    quote = quotes[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars: list[Bar] = []
    for i, ts in enumerate(timestamps):
        try:
            o, h, low, c, v = opens[i], highs[i], lows[i], closes[i], volumes[i]
        except IndexError:
            continue
        if None in (o, h, low, c, v):
            # Yahoo returns nulls for sessions with no trade (holidays, gaps).
            continue
        date = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        bars.append(
            Bar(
                date=date,
                open=float(o),
                high=float(h),
                low=float(low),
                close=float(c),
                volume=int(v),
            )
        )

    if not bars and timestamps:
        log.debug("%s: chart result had %d timestamps but no usable bars", symbol, len(timestamps))
    return bars


def _urllib_get(url: str, params: dict[str, str]) -> bytes:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={
            "User-Agent": "xtb-stock-analyzer/0.1 (+https://github.com/KrisWel/xtb-stock-analyzer)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise YahooFinanceError(
            f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise YahooFinanceError(f"request failed: {exc.reason}") from exc
