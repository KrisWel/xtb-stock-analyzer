"""Stage 2: map XTB symbols onto external identifiers (FIGI, data-provider tickers).

``getAllSymbols`` never returns a standardised external identifier, and there
is no universal external ticker — every data provider suffixes the venue
differently. The two problems are kept separate:

  * :func:`to_yahoo_symbol` reshapes the XTB ``TICKER.MARKET`` symbol into the
    suffix Yahoo Finance expects for that venue. Pure and offline — no network,
    no external service, safe to run against the committed snapshot.
  * FIGI lookup needs a third-party service, since XTB does not expose it —
    see :mod:`xtb_analyzer.openfigi` for that (network, optional, `--figi`).
    Note it's FIGI, not ISIN: OpenFIGI's free tier does not return ISIN
    (Bloomberg licensing) — verified live, see that module's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Instrument

#: XTB market code -> Yahoo Finance ticker suffix. ``""`` means no suffix (US).
#: Source: Yahoo Finance's published exchange suffix list. A market missing
#: here maps to ``None`` rather than a guess — add it once confirmed against
#: a real quote instead of assuming the pattern holds.
YAHOO_SUFFIX = {
    "US": "",
    "UK": ".L",
    "DE": ".DE",
    "FR": ".PA",
    "IT": ".MI",
    "ES": ".MC",
    "NL": ".AS",
    "PT": ".LS",
    "BE": ".BR",
    "CH": ".SW",
    "PL": ".WA",
    "CZ": ".PR",
    "HU": ".BD",
    "SE": ".ST",
    "NO": ".OL",
    "FI": ".HE",
    "DK": ".CO",
    "TR": ".IS",
}


@dataclass(frozen=True)
class IdentityMapping:
    """One row of the identity map — an instrument plus its external identifiers."""

    symbol: str
    ticker: str
    market: str
    currency: str
    yahoo_symbol: str | None
    figi: str | None = None

    @classmethod
    def csv_columns(cls) -> list[str]:
        return ["symbol", "ticker", "market", "currency", "yahoo_symbol", "figi"]

    def as_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "ticker": self.ticker,
            "market": self.market,
            "currency": self.currency,
            "yahoo_symbol": self.yahoo_symbol or "",
            "figi": self.figi or "",
        }


def to_yahoo_symbol(ticker: str, market: str) -> str | None:
    """Return the Yahoo Finance ticker for an XTB ``(ticker, market)`` pair.

    ``None`` when the market has no known suffix mapping yet.
    """
    suffix = YAHOO_SUFFIX.get(market)
    if suffix is None:
        return None
    return f"{ticker}{suffix}"


def map_instruments(
    instruments: list[Instrument], figi_by_symbol: dict[str, str] | None = None
) -> list[IdentityMapping]:
    """Build the identity map for a filtered instrument list.

    ``figi_by_symbol`` is an optional pre-resolved ``symbol -> FIGI`` lookup
    (typically from :func:`xtb_analyzer.openfigi.OpenFigiClient.lookup_figis`);
    omit it to produce ticker-only rows.
    """
    figi_by_symbol = figi_by_symbol or {}
    return [
        IdentityMapping(
            symbol=instrument.symbol,
            ticker=instrument.ticker,
            market=instrument.market,
            currency=instrument.currency,
            yahoo_symbol=to_yahoo_symbol(instrument.ticker, instrument.market),
            figi=figi_by_symbol.get(instrument.symbol),
        )
        for instrument in instruments
    ]
