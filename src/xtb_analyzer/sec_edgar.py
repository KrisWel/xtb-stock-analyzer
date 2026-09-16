"""Alternative, login-free instrument universe: US-listed companies via SEC EDGAR.

Stage 1's primary universe is XTB's own offer (``fetch``), reduced to cash
stocks/ETFs — but that requires XTB account credentials. This module is a
fallback that needs no account and no API key at all: the SEC publishes a
plain JSON file of every company with an active ticker,
<https://www.sec.gov/files/company_tickers.json>, refreshed regularly. The
only requirement is a descriptive ``User-Agent`` identifying the caller, per
SEC's fair-use / rate-limit policy (<https://www.sec.gov/os/webmaster-faq>) —
no registration, no key.

Trade-offs versus the real XTB universe, worth knowing before treating this
as equivalent:

* **US-listed common stock only** — no ETFs, no other market XTB also
  covers (PL, DE, UK, ...). It is not a substitute for the XTB universe, just
  something real to develop and test stages 2-3 against without XTB access.
* No CFD noise to filter: SEC only lists actual issuers, not XTB's derivative
  shadow instruments — so unlike :mod:`xtb_analyzer.filters`, there is
  nothing to reject here.
* No leverage/margin/long-only fields (those are XTB account concepts) — the
  resulting :class:`~xtb_analyzer.models.Instrument` rows leave them ``None``,
  same tolerant handling as any XTB record with missing fields.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

#: SEC's fair-use policy requires a descriptive User-Agent identifying the
#: caller, in practice something close to "Company/App name contact-info" —
#: requests without one are frequently rejected with a 403. A vaguer one
#: ("contact via GitHub issues", no concrete link) still got flagged live as
#: an "Undeclared Automated Tool" on a bulk companyfacts run (see
#: docs/PROGRESS.md) alongside SEC's IP-level traffic classification, so this
#: includes a real, checkable contact URL.
USER_AGENT = "xtb-stock-analyzer/0.1 (personal research project; https://github.com/KrisWel/xtb-stock-analyzer)"

Getter = Callable[[str, dict[str, str]], bytes]


class SecEdgarError(RuntimeError):
    """The SEC EDGAR request failed or returned an unexpected shape."""


def fetch_company_tickers(getter: Getter | None = None) -> list[dict[str, Any]]:
    """Return every ``{cik_str, ticker, title}`` entry from SEC's ticker file."""
    getter = getter or _urllib_get
    raw = getter(COMPANY_TICKERS_URL, {"User-Agent": USER_AGENT})
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecEdgarError(f"malformed response: {exc}") from exc

    if not isinstance(payload, dict):
        raise SecEdgarError(
            f"expected a JSON object keyed by row index, got {type(payload).__name__}"
        )

    return list(payload.values())


def to_symbol_record(entry: dict[str, Any]) -> dict[str, Any]:
    """Reshape one SEC entry into a ``getAllSymbols``-like record.

    Lets the existing :meth:`xtb_analyzer.models.Instrument.from_record` do the
    same tolerant parsing it already does for XTB payloads, instead of a
    parallel model just for this one alternate source.
    """
    ticker = str(entry.get("ticker", "")).strip().upper()
    return {
        "symbol": f"{ticker}.US",
        "description": str(entry.get("title", "")).strip(),
        "categoryName": "STC",
        "groupName": "SEC EDGAR company_tickers.json",
        "currency": "USD",
        "currencyProfit": "USD",
    }


@dataclass(frozen=True)
class CikEntry:
    """One symbol's SEC CIK (Central Index Key) — the id stage 4's fundamentals

    lookup (:mod:`xtb_analyzer.fundamentals`) needs. Kept as its own small
    sidecar file rather than a field on :class:`~xtb_analyzer.models.Instrument`,
    since CIK is meaningless for the XTB-sourced universe.
    """

    symbol: str
    cik: int

    @classmethod
    def csv_columns(cls) -> list[str]:
        return ["symbol", "cik"]

    def as_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "cik": str(self.cik)}


def build_cik_map(entries: list[dict[str, Any]]) -> list[CikEntry]:
    """Build the ``symbol -> CIK`` sidecar from the raw SEC ticker entries."""
    result = []
    for entry in entries:
        ticker = str(entry.get("ticker", "")).strip().upper()
        try:
            cik = int(entry["cik_str"])
        except (KeyError, TypeError, ValueError):
            continue
        result.append(CikEntry(symbol=f"{ticker}.US", cik=cik))
    return result


def _urllib_get(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise SecEdgarError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    except urllib.error.URLError as exc:
        raise SecEdgarError(f"request failed: {exc.reason}") from exc
