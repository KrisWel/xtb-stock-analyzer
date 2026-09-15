"""Optional FIGI lookup via the OpenFIGI mapping API.

XTB's ``getAllSymbols`` never returns a standardised external identifier, so
identity mapping falls back to a public third-party service
(<https://www.openfigi.com/api>). The unauthenticated tier is rate-limited to
25 jobs / 6 s, which is enough for a personal instrument universe of a few
hundred symbols; pass an API key to go faster.

Verified live (2026-09-15): the free ``/v3/mapping`` endpoint does **not**
return an ISIN — Bloomberg's terms only let OpenFIGI publish the FIGI itself
(and related identifiers like the composite/share-class FIGI), not the ISIN
crosswalk. A real response for ``AAPL``/``US`` looks like::

    {"data": [{"figi": "BBG000B9XRY4", "name": "APPLE INC", "ticker": "AAPL",
               "exchCode": "US", "compositeFIGI": "BBG000B9XRY4",
               "shareClassFIGI": "BBG001S5N8V8", ...}]}

— no ``isin`` key. So this module resolves **FIGI**, not ISIN; an earlier
version of this module assumed the latter and that assumption was wrong.

Also verified live: the unauthenticated tier caps a single request at **10**
jobs, not 100 — a batch of 100 without an API key gets ``HTTP 413``. An API
key raises both the per-request batch size and the rate limit; this module
picks the right cap from whether a key is present.

The ``TICKER + exchCode`` job type expects Bloomberg-style composite exchange
codes. :data:`EXCH_CODE` is assembled from public references and still not
fully verified against every market in a live snapshot — run
``xtb-analyzer map --figi`` and check a few known tickers before trusting a
market's mapping blindly, same discipline as the open questions in
``docs/xtb-api-notes.md``.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import Instrument

log = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

#: Unauthenticated tier caps a request at 10 jobs; a registered API key raises
#: that to 100. Verified live — an anonymous batch of 100 gets HTTP 413.
MAX_JOBS_PER_REQUEST_ANONYMOUS = 10
MAX_JOBS_PER_REQUEST_WITH_KEY = 100
#: Public/unauthenticated tier: 25 requests / 6 seconds.
MIN_REQUEST_INTERVAL_S = 0.3

#: XTB market code -> Bloomberg-style composite exchange code, for the
#: ``TICKER + exchCode`` OpenFIGI job type. Unverified — see module docstring.
EXCH_CODE = {
    "US": "US",
    "UK": "LN",
    "DE": "GR",
    "FR": "FP",
    "IT": "IM",
    "ES": "SM",
    "NL": "NA",
    "PT": "PL",
    "BE": "BB",
    "CH": "SW",
    "PL": "PW",
    "CZ": "CP",
    "HU": "HB",
    "SE": "SS",
    "NO": "NO",
    "FI": "FH",
    "DK": "DC",
    "TR": "TI",
}

Poster = Callable[[str, bytes, dict[str, str]], bytes]


class OpenFigiError(RuntimeError):
    """The OpenFIGI request failed or returned an unexpected shape."""


@dataclass(frozen=True)
class FigiJob:
    symbol: str
    ticker: str
    exch_code: str


class OpenFigiClient:
    """Thin wrapper around the OpenFIGI ``/v3/mapping`` endpoint.

    ``poster`` is injectable so the request/response plumbing can be unit
    tested without hitting the network — see ``tests/test_openfigi.py``.
    """

    def __init__(self, api_key: str | None = None, poster: Poster | None = None) -> None:
        self._api_key = api_key
        self._poster = poster or _urllib_post
        self._last_request_at = 0.0
        self._max_jobs_per_request = (
            MAX_JOBS_PER_REQUEST_WITH_KEY if api_key else MAX_JOBS_PER_REQUEST_ANONYMOUS
        )

    def lookup_figis(self, jobs: list[FigiJob]) -> dict[str, str]:
        """Best-effort ``symbol -> FIGI`` map; unresolved symbols are omitted."""
        results: dict[str, str] = {}
        for batch in _chunks(jobs, self._max_jobs_per_request):
            results.update(self._lookup_batch(batch))
        return results

    def _lookup_batch(self, batch: list[FigiJob]) -> dict[str, str]:
        body = json.dumps(
            [
                {"idType": "TICKER", "idValue": job.ticker, "exchCode": job.exch_code}
                for job in batch
            ]
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-OPENFIGI-APIKEY"] = self._api_key

        self._throttle()
        raw = self._poster(OPENFIGI_URL, body, headers)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenFigiError(f"malformed response: {exc}") from exc
        if not isinstance(payload, list) or len(payload) != len(batch):
            raise OpenFigiError(f"expected {len(batch)} results, got {payload!r}")

        found: dict[str, str] = {}
        for job, entry in zip(batch, payload, strict=True):
            if "error" in entry:
                log.debug("%s (%s/%s): %s", job.symbol, job.ticker, job.exch_code, entry["error"])
                continue
            data = entry.get("data") or []
            if data and data[0].get("figi"):
                found[job.symbol] = data[0]["figi"]
        return found

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()


def build_jobs(instruments: list[Instrument]) -> tuple[list[FigiJob], list[str]]:
    """Split instruments into OpenFIGI jobs and symbols with no exchange mapping."""
    jobs: list[FigiJob] = []
    unmapped: list[str] = []
    for instrument in instruments:
        exch_code = EXCH_CODE.get(instrument.market)
        if exch_code is None:
            unmapped.append(instrument.symbol)
            continue
        jobs.append(
            FigiJob(symbol=instrument.symbol, ticker=instrument.ticker, exch_code=exch_code)
        )
    return jobs, unmapped


def _urllib_post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise OpenFigiError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
    except urllib.error.URLError as exc:
        raise OpenFigiError(f"request failed: {exc.reason}") from exc


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
