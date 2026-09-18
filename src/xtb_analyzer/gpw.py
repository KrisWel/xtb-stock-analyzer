"""Another login-free alternative universe: the Warsaw Stock Exchange (GPW).

Complements :mod:`xtb_analyzer.sec_edgar` — same idea (no account, no API key,
just a compliant ``User-Agent``), different market: every PLN-denominated
company and ETF quoted on GPW's Main Market (**Główny Rynek**), which is the
market XTB's own ``PL`` symbols track. Two pages, both server-rendered (no
JavaScript needed):

* **Stocks** — ``https://www.gpw.pl/spolki?limit=1000&offset=0`` returns every
  Główny Rynek company in one GET, ticker/name/ISIN embedded in plain HTML.
  Verified live (2026-09-17): 402 companies, one request.
* **ETFs** — a POST to ``https://www.gpw.pl/ajaxindex.php`` with
  ``action=GPWQuotationsETF&start=ajaxList&page=etfy`` (the same call the
  ``/etfy`` page's search form makes) returns every GPW-listed ETF, including
  foreign-domiciled ones cross-listed and quoted on GPW in PLN (e.g. a DAX or
  S&P 500 tracker). Verified live: 40 ETFs, ISIN and currency both explicit
  in the response — every one PLN.

Both endpoints are undocumented HTML/AJAX internals of gpw.pl, not a public
API — same caution as ``market_data.py``'s Yahoo endpoint: useful, unofficial,
can change shape without notice.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

STOCKS_URL = "https://www.gpw.pl/spolki?limit=1000&offset=0"
ETF_AJAX_URL = "https://www.gpw.pl/ajaxindex.php"
ETF_AJAX_BODY = "action=GPWQuotationsETF&start=ajaxList&page=etfy"

USER_AGENT = "xtb-stock-analyzer/0.1 (personal research project; https://github.com/KrisWel/xtb-stock-analyzer)"

_STOCK_ROW_RE = re.compile(
    r'href="spolka\?isin=([A-Z0-9]+)">\s*<strong class="name">\s*(.*?)\s*'
    r'<span class="grey">\(([^)]*)\)</span>',
    re.S,
)
_ETF_ROW_RE = re.compile(
    r'href="etf\?isin=([A-Z0-9]+)">\s*<b>([^<]+?)\s*</b>\s*</a>\s*</td>\s*'
    r'<td[^>]*id="id_ISIN"[^>]*>([A-Z0-9]+)</td>\s*'
    r'<td[^>]*id="id_Waluta"[^>]*>([A-Z]+)</td>'
)

Getter = Callable[[str, dict[str, str]], bytes]
Poster = Callable[[str, bytes, dict[str, str]], bytes]


class GpwError(RuntimeError):
    """A GPW page/AJAX request failed or returned an unexpected shape."""


@dataclass(frozen=True)
class GpwStock:
    isin: str
    ticker: str
    name: str


@dataclass(frozen=True)
class GpwEtf:
    isin: str
    ticker: str
    currency: str


def fetch_stocks_html(getter: Getter | None = None) -> str:
    getter = getter or _urllib_get
    raw = getter(STOCKS_URL, {"User-Agent": USER_AGENT})
    return raw.decode("utf-8", errors="replace")


def fetch_etf_html(poster: Poster | None = None) -> str:
    poster = poster or _urllib_post
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
    }
    raw = poster(ETF_AJAX_URL, ETF_AJAX_BODY.encode("ascii"), headers)
    return raw.decode("utf-8", errors="replace")


def parse_stocks(html: str) -> list[GpwStock]:
    """Parse the Główny Rynek company list page into :class:`GpwStock` rows."""
    stocks = [
        GpwStock(isin=isin, ticker=ticker.strip(), name=re.sub(r"\s+", " ", name).strip())
        for isin, name, ticker in _STOCK_ROW_RE.findall(html)
        if ticker.strip()
    ]
    if not stocks:
        raise GpwError("no company rows found — page structure may have changed")
    return stocks


def parse_etfs(html: str) -> list[GpwEtf]:
    """Parse the ``/etfy`` AJAX fragment into :class:`GpwEtf` rows."""
    etfs = [
        GpwEtf(isin=isin, ticker=_clean_etf_ticker(ticker), currency=currency)
        for isin, ticker, isin_repeat, currency in _ETF_ROW_RE.findall(html)
        if isin == isin_repeat
    ]
    if not etfs:
        raise GpwError("no ETF rows found — page structure may have changed")
    return etfs


def _clean_etf_ticker(raw: str) -> str:
    """Strip a GPW instrument-status marker sometimes appended to the ticker text.

    Verified live (2026-09-18): a suspended/newly-listed leveraged ETN came
    back as ``ETNVIRXRP  /Z`` — the status suffix (``/Z``) is plain text in
    the same ``<b>`` tag as the ticker, separated only by extra whitespace,
    not its own markup, so the row regex can't isolate it on its own. A raw
    ticker with embedded spaces breaks the Yahoo symbol built from it
    (``f"{ticker}.PL"``), so split on the first run of 2+ spaces and keep
    only the leading token.
    """
    return re.split(r"\s{2,}", raw.strip())[0]


def stock_to_symbol_record(stock: GpwStock) -> dict[str, str]:
    """Reshape one GPW stock into a ``getAllSymbols``-like record.

    Główny Rynek equities are uniformly PLN-denominated, including
    foreign-domiciled issuers cross-listed there — verified live via Yahoo
    Finance (AmRest, a Spanish ISIN, trades as ``EAT.WA`` in PLN).
    """
    return {
        "symbol": f"{stock.ticker}.PL",
        "description": stock.name,
        "categoryName": "STC",
        "groupName": "GPW Glowny Rynek",
        "currency": "PLN",
        "currencyProfit": "PLN",
    }


def etf_to_symbol_record(etf: GpwEtf) -> dict[str, str]:
    return {
        "symbol": f"{etf.ticker}.PL",
        "description": etf.ticker,
        "categoryName": "ETF",
        "groupName": "GPW ETF",
        "currency": etf.currency,
        "currencyProfit": etf.currency,
    }


@dataclass(frozen=True)
class IsinEntry:
    """One symbol's real ISIN, straight from GPW — no OpenFIGI/FIGI needed for
    this universe, unlike the XTB-sourced one (see openfigi.py's docstring on
    why the free OpenFIGI tier can't provide ISIN at all).
    """

    symbol: str
    isin: str

    @classmethod
    def csv_columns(cls) -> list[str]:
        return ["symbol", "isin"]

    def as_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "isin": self.isin}


def build_isin_map(stocks: list[GpwStock], etfs: list[GpwEtf]) -> list[IsinEntry]:
    entries = [IsinEntry(symbol=f"{stock.ticker}.PL", isin=stock.isin) for stock in stocks]
    entries += [IsinEntry(symbol=f"{etf.ticker}.PL", isin=etf.isin) for etf in etfs]
    return entries


def _urllib_get(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise GpwError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    except urllib.error.URLError as exc:
        raise GpwError(f"request failed: {exc.reason}") from exc


def _urllib_post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise GpwError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    except urllib.error.URLError as exc:
        raise GpwError(f"request failed: {exc.reason}") from exc
