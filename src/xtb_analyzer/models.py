"""Normalised representation of an XTB instrument."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from typing import Any

#: XTB symbols look like ``AAPL.US``, ``CDR.PL``, ``IUSQ.DE``, ``ISF.UK``.
#: CFD variants of the same underlying carry a numeric suffix, e.g. ``AAPL.US_9``.
SYMBOL_RE = re.compile(r"^(?P<ticker>[^.]+)\.(?P<market>[A-Z0-9]+?)(?P<cfd_suffix>_\d+)?$")

#: Market code -> human readable venue. Used later to map onto external data providers.
MARKETS = {
    "US": "United States",
    "UK": "United Kingdom",
    "DE": "Germany (Xetra)",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "NL": "Netherlands",
    "PT": "Portugal",
    "BE": "Belgium",
    "CH": "Switzerland",
    "PL": "Poland (GPW)",
    "CZ": "Czechia",
    "HU": "Hungary",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "DK": "Denmark",
    "TR": "Turkey",
}


@dataclass(frozen=True)
class Instrument:
    """A single tradable instrument, trimmed down to the fields we care about."""

    symbol: str
    description: str
    asset_class: str  # STOCK | ETF
    category_name: str
    group_name: str
    currency: str
    currency_profit: str
    ticker: str
    market: str
    market_name: str
    precision: int | None
    contract_size: float | None
    leverage: float | None
    long_only: bool | None
    short_selling: bool | None
    margin_mode: int | None
    instrument_type: int | None

    @classmethod
    def csv_columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any], asset_class: str) -> Instrument:
        symbol = str(record.get("symbol", "")).strip()
        ticker, market = split_symbol(symbol)
        return cls(
            symbol=symbol,
            description=str(record.get("description", "") or "").strip(),
            asset_class=asset_class,
            category_name=str(record.get("categoryName", "") or "").strip(),
            group_name=str(record.get("groupName", "") or "").strip(),
            currency=str(record.get("currency", "") or "").strip(),
            currency_profit=str(record.get("currencyProfit", "") or "").strip(),
            ticker=ticker,
            market=market,
            market_name=MARKETS.get(market, ""),
            precision=_as_int(record.get("precision")),
            contract_size=_as_float(record.get("contractSize")),
            leverage=_as_float(record.get("leverage")),
            long_only=_as_bool(record.get("longOnly")),
            short_selling=_as_bool(record.get("shortSelling")),
            margin_mode=_as_int(record.get("marginMode")),
            instrument_type=_as_int(record.get("type")),
        )


def split_symbol(symbol: str) -> tuple[str, str]:
    """Split ``AAPL.US`` into ``("AAPL", "US")``. Unknown shapes return ``(symbol, "")``."""
    match = SYMBOL_RE.match(symbol.upper())
    if not match:
        return symbol, ""
    return match.group("ticker"), match.group("market")


def has_cfd_suffix(symbol: str) -> bool:
    """True for CFD variants such as ``AAPL.US_9`` that shadow a cash symbol."""
    match = SYMBOL_RE.match(symbol.upper())
    return bool(match and match.group("cfd_suffix"))


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None
