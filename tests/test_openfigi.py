import json

import pytest

from xtb_analyzer.filters import filter_instruments
from xtb_analyzer.openfigi import (
    FigiJob,
    OpenFigiClient,
    OpenFigiError,
    build_jobs,
)


def test_build_jobs_splits_mapped_and_unmapped(sample_records):
    instruments = filter_instruments(sample_records).instruments
    jobs, unmapped = build_jobs(instruments)

    assert unmapped == []
    by_symbol = {job.symbol: job for job in jobs}
    assert by_symbol["CDR.PL"].ticker == "CDR"
    assert by_symbol["CDR.PL"].exch_code == "PW"


def test_build_jobs_reports_unmapped_market():
    from xtb_analyzer.models import Instrument

    instrument = Instrument.from_record({"symbol": "X.ZZ"}, "STOCK")
    jobs, unmapped = build_jobs([instrument])

    assert jobs == []
    assert unmapped == ["X.ZZ"]


def _fake_poster(responses):
    calls = []

    def poster(url, body, headers):
        calls.append((url, json.loads(body), headers))
        return json.dumps(responses.pop(0)).encode("utf-8")

    return poster, calls


def test_lookup_isins_parses_matches_and_errors():
    jobs = [
        FigiJob(symbol="AAPL.US", ticker="AAPL", exch_code="US"),
        FigiJob(symbol="NOPE.US", ticker="NOPE", exch_code="US"),
    ]
    responses = [
        [
            {"data": [{"isin": "US0378331005", "figi": "BBG000B9XRY4"}]},
            {"error": "No identifier found."},
        ]
    ]
    poster, calls = _fake_poster(responses)
    client = OpenFigiClient(poster=poster)

    result = client.lookup_isins(jobs)

    assert result == {"AAPL.US": "US0378331005"}
    assert len(calls) == 1
    _, body, headers = calls[0]
    assert body == [
        {"idType": "TICKER", "idValue": "AAPL", "exchCode": "US"},
        {"idType": "TICKER", "idValue": "NOPE", "exchCode": "US"},
    ]
    assert "X-OPENFIGI-APIKEY" not in headers


def test_lookup_isins_sends_api_key_header():
    jobs = [FigiJob(symbol="AAPL.US", ticker="AAPL", exch_code="US")]
    poster, calls = _fake_poster([[{"data": [{"isin": "US0378331005"}]}]])
    client = OpenFigiClient(api_key="secret-key", poster=poster)

    client.lookup_isins(jobs)

    assert calls[0][2]["X-OPENFIGI-APIKEY"] == "secret-key"


def test_lookup_isins_batches_over_100_jobs():
    jobs = [FigiJob(symbol=f"S{i}.US", ticker=f"S{i}", exch_code="US") for i in range(150)]
    responses = [
        [{"data": [{"isin": f"ISIN{i}"}]} for i in range(100)],
        [{"data": [{"isin": f"ISIN{i}"}]} for i in range(100, 150)],
    ]
    poster, calls = _fake_poster(responses)
    client = OpenFigiClient(poster=poster)

    result = client.lookup_isins(jobs)

    assert len(calls) == 2
    assert len(result) == 150
    assert result["S0.US"] == "ISIN0"
    assert result["S149.US"] == "ISIN149"


def test_lookup_isins_raises_on_shape_mismatch():
    jobs = [FigiJob(symbol="AAPL.US", ticker="AAPL", exch_code="US")]
    poster, _ = _fake_poster([[]])
    client = OpenFigiClient(poster=poster)

    with pytest.raises(OpenFigiError):
        client.lookup_isins(jobs)
