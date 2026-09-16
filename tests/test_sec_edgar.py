import json

import pytest

from xtb_analyzer.sec_edgar import (
    USER_AGENT,
    CikEntry,
    SecEdgarError,
    build_cik_map,
    fetch_company_tickers,
    to_symbol_record,
)


def _fake_getter(payload):
    calls = []

    def getter(url, headers):
        calls.append((url, headers))
        return json.dumps(payload).encode("utf-8")

    return getter, calls


def test_fetch_company_tickers_parses_indexed_object():
    payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }
    getter, calls = _fake_getter(payload)

    entries = fetch_company_tickers(getter=getter)

    assert entries == [
        {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    ]
    url, headers = calls[0]
    assert url.endswith("company_tickers.json")
    assert headers["User-Agent"] == USER_AGENT


def test_fetch_company_tickers_rejects_non_object_payload():
    getter, _ = _fake_getter(["not", "a", "dict"])

    with pytest.raises(SecEdgarError):
        fetch_company_tickers(getter=getter)


def test_to_symbol_record_shapes_like_get_all_symbols():
    entry = {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."}

    record = to_symbol_record(entry)

    assert record["symbol"] == "AAPL.US"
    assert record["categoryName"] == "STC"
    assert record["currency"] == "USD"
    assert "CFD" not in record["groupName"]


def test_build_cik_map():
    entries = [
        {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
        {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    ]

    result = build_cik_map(entries)

    assert result == [
        CikEntry(symbol="AAPL.US", cik=320193),
        CikEntry(symbol="MSFT.US", cik=789019),
    ]


def test_build_cik_map_skips_unparseable_cik():
    entries = [{"cik_str": "not-a-number", "ticker": "X", "title": "X Corp"}]

    assert build_cik_map(entries) == []
