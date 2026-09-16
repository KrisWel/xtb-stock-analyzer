"""Stage 4: company fundamentals via SEC EDGAR's XBRL company facts API.

Free, no login, no API key — the same compliant User-Agent as
:mod:`xtb_analyzer.sec_edgar`. Every US public company's structured financial
data, straight from its own 10-K/10-Q filings, is available at
``https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit-cik}.json``, keyed
by the CIK :func:`xtb_analyzer.sec_edgar.build_cik_map` already resolves.
Only the US-listed ``us_stocks`` universe has fundamentals this way — XTB's
own universe carries no CIK.

Verified live (2026-09-16) against Apple's real filings: a company's facts are
grouped by taxonomy (``us-gaap``, ``dei``) then by concept (e.g.
``NetIncomeLoss``), each concept holding a list of every value ever reported
for it, tagged with the filing (``form``, ``fy``, ``fp``, ``filed``) and the
period it covers (``start``/``end`` for a duration like revenue, ``end`` only
for a point-in-time balance-sheet figure like total assets).

Two extraction rules follow from that shape:

* **Duration concepts** (revenue, net income, gross profit, diluted EPS) use
  the most recent full fiscal year from a 10-K (``form == "10-K"``,
  ``fp == "FY"``, and the period spans roughly a year — tolerant of 52/53-week
  fiscal years), plus the prior FY for a simple year-over-year growth figure.
* **Point-in-time concepts** (total assets, total liabilities, stockholders'
  equity) use whichever filing is most recent, 10-K or 10-Q, since a balance
  sheet is a snapshot rather than a period.

Not every filer tags the same concept name for the same line item (US GAAP
taxonomy migrations, company-specific choices), so each metric tries a short
list of concept names and uses the first one present, rather than assuming
one canonical tag exists everywhere.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .sec_edgar import USER_AGENT

log = logging.getLogger(__name__)

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

#: SEC's fair-use policy states a soft cap of 10 requests/second; real-world
#: testing (see docs/PROGRESS.md) showed a burst of 50 sequential requests at
#: 1 req/s got the whole IP flagged as an "Undeclared Automated Tool" — a
#: stricter, IP-reputation-based block, not just a rate limit. Stay well
#: under the soft cap and expect bulk runs to need patience regardless.
MIN_REQUEST_INTERVAL_S = 2.0

#: Tried in order; the first concept present in a filer's facts wins. Not
#: every filer tags the same line item under the same US GAAP concept name.
REVENUE_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
]
NET_INCOME_CONCEPTS = ["NetIncomeLoss", "ProfitLoss"]
GROSS_PROFIT_CONCEPTS = ["GrossProfit"]
ASSETS_CONCEPTS = ["Assets"]
LIABILITIES_CONCEPTS = ["Liabilities"]
EQUITY_CONCEPTS = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
EPS_DILUTED_CONCEPTS = ["EarningsPerShareDiluted"]

Getter = Callable[[str, dict[str, str]], bytes]


class FundamentalsError(RuntimeError):
    """The SEC company facts request failed or returned an unexpected shape."""


@dataclass(frozen=True)
class Fundamentals:
    """The handful of raw, filed figures a later stage's ratios build on.

    Deliberately stores the raw numbers SEC filers reported, not derived
    ratios — those are cheap to compute from these (see the ``*_margin`` /
    ``*_growth`` properties below) and storing them redundantly risks the
    CSV and the computation drifting apart.
    """

    symbol: str
    cik: int
    fiscal_year: int | None
    fiscal_year_end: str | None
    revenue: float | None
    revenue_prior_year: float | None
    net_income: float | None
    net_income_prior_year: float | None
    gross_profit: float | None
    total_assets: float | None
    total_liabilities: float | None
    stockholders_equity: float | None
    eps_diluted: float | None

    @classmethod
    def csv_columns(cls) -> list[str]:
        return [
            "symbol",
            "cik",
            "fiscal_year",
            "fiscal_year_end",
            "revenue",
            "revenue_prior_year",
            "net_income",
            "net_income_prior_year",
            "gross_profit",
            "total_assets",
            "total_liabilities",
            "stockholders_equity",
            "eps_diluted",
        ]

    def as_dict(self) -> dict[str, str]:
        return {column: _to_csv_cell(getattr(self, column)) for column in self.csv_columns()}

    @property
    def net_margin(self) -> float | None:
        return _safe_ratio(self.net_income, self.revenue)

    @property
    def gross_margin(self) -> float | None:
        return _safe_ratio(self.gross_profit, self.revenue)

    @property
    def revenue_growth(self) -> float | None:
        return _safe_growth(self.revenue, self.revenue_prior_year)

    @property
    def net_income_growth(self) -> float | None:
        return _safe_growth(self.net_income, self.net_income_prior_year)

    @property
    def liabilities_to_equity(self) -> float | None:
        return _safe_ratio(self.total_liabilities, self.stockholders_equity)


class SecFactsClient:
    """Thin wrapper around SEC's ``xbrl/companyfacts`` endpoint.

    ``getter`` is injectable so the request/response plumbing can be unit
    tested without hitting the network — see ``tests/test_fundamentals.py``.
    """

    def __init__(self, getter: Getter | None = None) -> None:
        self._getter = getter or _urllib_get
        self._last_request_at = 0.0

    def get_company_facts(self, cik: int) -> dict:
        self._throttle()
        raw = self._getter(COMPANY_FACTS_URL.format(cik=cik), {"User-Agent": USER_AGENT})
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FundamentalsError(f"CIK {cik}: malformed response: {exc}") from exc
        if "facts" not in payload:
            raise FundamentalsError(f"CIK {cik}: no 'facts' key in response")
        return payload

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()


def extract_fundamentals(symbol: str, cik: int, payload: dict) -> Fundamentals:
    """Reshape one company's raw XBRL facts payload into :class:`Fundamentals`."""
    usgaap = (payload.get("facts") or {}).get("us-gaap") or {}

    revenue, revenue_prior, rev_fy, rev_end = _best_annual(usgaap, REVENUE_CONCEPTS)
    net_income, net_income_prior, ni_fy, ni_end = _best_annual(usgaap, NET_INCOME_CONCEPTS)
    gross_profit, *_ = _best_annual(usgaap, GROSS_PROFIT_CONCEPTS)
    eps_diluted, *_ = _best_annual(usgaap, EPS_DILUTED_CONCEPTS, unit="USD/shares")
    total_assets, _ = _best_point_in_time(usgaap, ASSETS_CONCEPTS)
    total_liabilities, _ = _best_point_in_time(usgaap, LIABILITIES_CONCEPTS)
    stockholders_equity, _ = _best_point_in_time(usgaap, EQUITY_CONCEPTS)

    return Fundamentals(
        symbol=symbol,
        cik=cik,
        fiscal_year=rev_fy or ni_fy,
        fiscal_year_end=rev_end or ni_end,
        revenue=revenue,
        revenue_prior_year=revenue_prior,
        net_income=net_income,
        net_income_prior_year=net_income_prior,
        gross_profit=gross_profit,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        stockholders_equity=stockholders_equity,
        eps_diluted=eps_diluted,
    )


def _best_annual(
    usgaap: dict, concept_names: list[str], unit: str = "USD"
) -> tuple[float | None, float | None, int | None, str | None]:
    """Evaluate every candidate concept name and keep whichever has the most
    recent annual figure.

    A filer can carry more than one candidate concept in its facts at once —
    verified live against Apple, which still lists ``Revenues`` but stopped
    updating it after FY2018 when it adopted ASC 606 and switched to
    ``RevenueFromContractWithCustomerExcludingAssessedTax``. Taking the first
    *present* name (rather than the most *current* one) silently pairs a
    seven-year-stale revenue figure with a fresh net income — comparing
    recency across every candidate instead of stopping at the first hit
    avoids that.
    """
    best: tuple[float | None, float | None, int | None, str | None] = (None, None, None, None)
    for name in concept_names:
        candidate = _latest_annual(usgaap.get(name), unit=unit)
        if candidate[3] is not None and (best[3] is None or candidate[3] > best[3]):
            best = candidate
    return best


def _best_point_in_time(
    usgaap: dict, concept_names: list[str], unit: str = "USD"
) -> tuple[float | None, str | None]:
    best: tuple[float | None, str | None] = (None, None)
    for name in concept_names:
        candidate = _latest_point_in_time(usgaap.get(name), unit=unit)
        if candidate[1] is not None and (best[1] is None or candidate[1] > best[1]):
            best = candidate
    return best


def _is_full_year(entry: dict) -> bool:
    try:
        span = (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
    except (KeyError, ValueError):
        return False
    return 300 <= span <= 380  # tolerant of 52/53-week fiscal years


def _latest_annual(
    concept: dict | None, unit: str = "USD"
) -> tuple[float | None, float | None, int | None, str | None]:
    """Return ``(latest, prior_year, fiscal_year, period_end)`` for a duration concept."""
    entries = ((concept or {}).get("units") or {}).get(unit, [])
    annual = sorted(
        (
            e
            for e in entries
            if e.get("form") == "10-K" and e.get("fp") == "FY" and _is_full_year(e)
        ),
        key=lambda e: e["end"],
    )
    if not annual:
        return None, None, None, None
    latest = annual[-1]
    prior = annual[-2] if len(annual) >= 2 else None
    return latest["val"], (prior["val"] if prior else None), latest.get("fy"), latest["end"]


def _latest_point_in_time(
    concept: dict | None, unit: str = "USD"
) -> tuple[float | None, str | None]:
    entries = ((concept or {}).get("units") or {}).get(unit, [])
    if not entries:
        return None, None
    latest = max(entries, key=lambda e: e["end"])
    return latest["val"], latest["end"]


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _safe_growth(latest: float | None, prior: float | None) -> float | None:
    if latest is None or not prior:
        return None
    return (latest - prior) / abs(prior)


def _to_csv_cell(value: float | int | str | None) -> str:
    if value is None:
        return ""
    return repr(value) if isinstance(value, float) else str(value)


def _urllib_get(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise FundamentalsError(
            f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise FundamentalsError(f"request failed: {exc.reason}") from exc
