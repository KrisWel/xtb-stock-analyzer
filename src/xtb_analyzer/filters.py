"""Separating cash equities / ETFs from everything else XTB offers.

``getAllSymbols`` returns the whole offer in one list: cash stocks, ETFs, but also
stock CFDs, index CFDs, FX, commodities and crypto. There is no single boolean that
says "this is a real share", so the filter combines several signals and records the
reason for every rejection — run ``xtb-analyzer inspect`` to see the breakdown and
re-tune the thresholds against live data before trusting the output.

Signals used, in order:
  1. ``categoryName`` must be STC (stocks) or ETF (ETFs/ETNs).
  2. The symbol must not carry a CFD suffix (``AAPL.US_9``).
  3. ``groupName`` / ``description`` must not advertise a CFD.
  4. Leverage must be >= 100 (100 == full margin == no leverage; CFDs sit well below).
  5. ``longOnly`` must not be False (cash shares at XTB cannot be shorted).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .models import Instrument, has_cfd_suffix

#: XTB category codes for the cash offer. ETNs are published under the ETF category.
ASSET_CLASS_BY_CATEGORY = {
    "STC": "STOCK",
    "ETF": "ETF",
}

CFD_TEXT_RE = re.compile(r"\bCFD\b", re.IGNORECASE)


@dataclass(frozen=True)
class FilterConfig:
    """Tunable thresholds — every rule can be switched off for experiments."""

    categories: dict[str, str] = field(default_factory=lambda: dict(ASSET_CLASS_BY_CATEGORY))
    reject_cfd_suffix: bool = True
    reject_cfd_text: bool = True
    min_leverage: float | None = 100.0
    require_long_only: bool = True


@dataclass(frozen=True)
class FilterResult:
    instruments: list[Instrument]
    rejections: Counter
    total: int

    @property
    def kept(self) -> int:
        return len(self.instruments)

    def summary(self) -> str:
        lines = [f"kept {self.kept} of {self.total} records"]
        for reason, count in self.rejections.most_common():
            lines.append(f"  rejected {count:>6}  {reason}")
        return "\n".join(lines)


def classify(record: dict[str, Any], config: FilterConfig | None = None) -> tuple[str | None, str]:
    """Return ``(asset_class, reason)``. ``asset_class`` is None when the record is rejected."""
    config = config or FilterConfig()

    category = str(record.get("categoryName", "") or "").strip().upper()
    asset_class = config.categories.get(category)
    if asset_class is None:
        return None, f"category={category or '<empty>'}"

    symbol = str(record.get("symbol", "") or "")
    if config.reject_cfd_suffix and has_cfd_suffix(symbol):
        return None, "cfd-symbol-suffix"

    if config.reject_cfd_text:
        haystack = f"{record.get('groupName', '')} {record.get('description', '')}"
        if CFD_TEXT_RE.search(haystack):
            return None, "cfd-in-text"

    if config.min_leverage is not None:
        leverage = record.get("leverage")
        if isinstance(leverage, (int, float)) and leverage < config.min_leverage:
            return None, f"leveraged(<{config.min_leverage:g})"

    if config.require_long_only and record.get("longOnly") is False:
        return None, "not-long-only"

    return asset_class, "kept"


def filter_instruments(
    records: Iterable[dict[str, Any]],
    config: FilterConfig | None = None,
) -> FilterResult:
    """Apply :func:`classify` to every record and collect the survivors."""
    config = config or FilterConfig()
    instruments: list[Instrument] = []
    rejections: Counter = Counter()
    total = 0

    for record in records:
        total += 1
        asset_class, reason = classify(record, config)
        if asset_class is None:
            rejections[reason] += 1
            continue
        instruments.append(Instrument.from_record(record, asset_class))

    instruments.sort(key=lambda item: item.symbol)
    return FilterResult(instruments=instruments, rejections=rejections, total=total)


def describe_universe(records: Iterable[dict[str, Any]]) -> dict[str, Counter]:
    """Field distributions used by the ``inspect`` command to sanity-check the rules."""
    stats: dict[str, Counter] = {
        "categoryName": Counter(),
        "groupName": Counter(),
        "currency": Counter(),
        "leverage": Counter(),
        "longOnly": Counter(),
        "marginMode": Counter(),
    }
    for record in records:
        for key, counter in stats.items():
            counter[str(record.get(key))] += 1
    return stats
