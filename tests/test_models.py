import pytest

from xtb_analyzer.models import Instrument, has_cfd_suffix, split_symbol


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("AAPL.US", ("AAPL", "US")),
        ("CDR.PL", ("CDR", "PL")),
        ("AAPL.US_9", ("AAPL", "US")),
        ("EURUSD", ("EURUSD", "")),
    ],
)
def test_split_symbol(symbol, expected):
    assert split_symbol(symbol) == expected


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("AAPL.US", False), ("AAPL.US_9", True), ("TSLA.US_4", True), ("EURUSD", False)],
)
def test_has_cfd_suffix(symbol, expected):
    assert has_cfd_suffix(symbol) is expected


def test_from_record_maps_fields(sample_records):
    record = next(r for r in sample_records if r["symbol"] == "CDR.PL")
    instrument = Instrument.from_record(record, "STOCK")

    assert instrument.symbol == "CDR.PL"
    assert instrument.ticker == "CDR"
    assert instrument.market == "PL"
    assert instrument.market_name == "Poland (GPW)"
    assert instrument.asset_class == "STOCK"
    assert instrument.currency == "PLN"
    assert instrument.leverage == 100.0
    assert instrument.long_only is True


def test_from_record_tolerates_missing_fields():
    instrument = Instrument.from_record({"symbol": "X.US"}, "STOCK")
    assert instrument.description == ""
    assert instrument.leverage is None
    assert instrument.long_only is None
