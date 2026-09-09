import pytest

from xtb_analyzer.filters import filter_instruments
from xtb_analyzer.identity import map_instruments, to_yahoo_symbol
from xtb_analyzer.models import Instrument


@pytest.mark.parametrize(
    ("ticker", "market", "expected"),
    [
        ("AAPL", "US", "AAPL"),
        ("CDR", "PL", "CDR.WA"),
        ("IUSQ", "DE", "IUSQ.DE"),
        ("ISF", "UK", "ISF.L"),
        ("XYZ", "ZZ", None),
    ],
)
def test_to_yahoo_symbol(ticker, market, expected):
    assert to_yahoo_symbol(ticker, market) == expected


def test_map_instruments_without_isin(sample_records):
    instruments = filter_instruments(sample_records).instruments
    mappings = map_instruments(instruments)

    by_symbol = {m.symbol: m for m in mappings}
    assert by_symbol["AAPL.US"].yahoo_symbol == "AAPL"
    assert by_symbol["CDR.PL"].yahoo_symbol == "CDR.WA"
    assert all(m.isin is None for m in mappings)


def test_map_instruments_applies_isin_lookup(sample_records):
    instruments = filter_instruments(sample_records).instruments
    mappings = map_instruments(instruments, isin_by_symbol={"AAPL.US": "US0378331005"})

    by_symbol = {m.symbol: m for m in mappings}
    assert by_symbol["AAPL.US"].isin == "US0378331005"
    assert by_symbol["CDR.PL"].isin is None


def test_identity_mapping_as_dict_uses_empty_strings_for_none():
    instrument = Instrument.from_record({"symbol": "X.ZZ"}, "STOCK")
    mappings = map_instruments([instrument])

    row = mappings[0].as_dict()
    assert row["yahoo_symbol"] == ""
    assert row["isin"] == ""
