import json
from collections import Counter

from xtb_analyzer.filters import filter_instruments
from xtb_analyzer.fundamentals import Fundamentals
from xtb_analyzer.gpw import IsinEntry
from xtb_analyzer.identity import map_instruments
from xtb_analyzer.market_data import Bar
from xtb_analyzer.scoring import Score
from xtb_analyzer.sec_edgar import CikEntry
from xtb_analyzer.storage import (
    read_cik_map,
    read_fundamentals,
    read_identity_map,
    read_isin_map,
    read_ohlcv,
    read_raw,
    read_scores,
    read_snapshot,
    read_technicals,
    write_cik_map,
    write_fundamentals,
    write_identity_map,
    write_isin_map,
    write_metadata,
    write_ohlcv,
    write_raw,
    write_scores,
    write_snapshot,
    write_technicals,
)
from xtb_analyzer.technicals import Technicals


def test_snapshot_round_trip_preserves_values(tmp_path, sample_records):
    original = filter_instruments(sample_records).instruments
    path = write_snapshot(original, tmp_path / "instruments.csv")

    restored = read_snapshot(path)

    assert restored == original
    assert restored[0].long_only is True
    assert isinstance(restored[0].leverage, float)
    assert isinstance(restored[0].precision, int)


def test_snapshot_has_a_header_row(tmp_path, sample_records):
    instruments = filter_instruments(sample_records).instruments
    path = write_snapshot(instruments, tmp_path / "instruments.csv")

    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("symbol,description,asset_class")


def test_raw_round_trip(tmp_path, sample_records):
    path = write_raw(sample_records, tmp_path / "raw" / "all_symbols.json")
    assert read_raw(path) == sample_records


def test_metadata_contains_counts(tmp_path):
    path = write_metadata(
        tmp_path / "meta.json",
        source="unit-test",
        total=11,
        kept=3,
        rejections=Counter({"category=FX": 1}),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["records_returned"] == 11
    assert payload["instruments_kept"] == 3
    assert payload["rejections"] == {"category=FX": 1}
    assert payload["fetched_at"].endswith("+00:00")


def test_identity_map_round_trip_preserves_values(tmp_path, sample_records):
    instruments = filter_instruments(sample_records).instruments
    original = map_instruments(instruments, figi_by_symbol={"AAPL.US": "BBG000B9XRY4"})
    path = write_identity_map(original, tmp_path / "identity_map.csv")

    restored = read_identity_map(path)

    assert restored == original
    by_symbol = {m.symbol: m for m in restored}
    assert by_symbol["AAPL.US"].figi == "BBG000B9XRY4"
    assert by_symbol["CDR.PL"].figi is None
    assert by_symbol["CDR.PL"].yahoo_symbol == "CDR.WA"


def test_ohlcv_round_trip_sorts_by_date(tmp_path):
    bars = [
        Bar(date="2026-01-02", open=1.5, high=2.5, low=1.0, close=2.0, volume=110),
        Bar(date="2026-01-01", open=1.0, high=2.0, low=0.5, close=1.5, volume=100),
    ]
    path = write_ohlcv(bars, tmp_path / "ohlcv" / "AAPL.csv")

    restored = read_ohlcv(path)

    assert [b.date for b in restored] == ["2026-01-01", "2026-01-02"]
    assert restored[0] == bars[1]


def test_read_ohlcv_missing_file_returns_empty(tmp_path):
    assert read_ohlcv(tmp_path / "does-not-exist.csv") == []


def test_cik_map_round_trip(tmp_path):
    original = [CikEntry(symbol="AAPL.US", cik=320193), CikEntry(symbol="MSFT.US", cik=789019)]
    path = write_cik_map(original, tmp_path / "us_stocks_cik.csv")

    assert read_cik_map(path) == original


def test_fundamentals_round_trip_preserves_values_and_none(tmp_path):
    original = [
        Fundamentals(
            symbol="AAPL.US",
            cik=320193,
            fiscal_year=2025,
            fiscal_year_end="2025-09-30",
            revenue=1200.0,
            revenue_prior_year=1000.0,
            net_income=150.0,
            net_income_prior_year=100.0,
            gross_profit=500.0,
            total_assets=5000.0,
            total_liabilities=2000.0,
            stockholders_equity=3000.0,
            eps_diluted=6.5,
        ),
        Fundamentals(
            symbol="EMPTY.US",
            cik=1,
            fiscal_year=None,
            fiscal_year_end=None,
            revenue=None,
            revenue_prior_year=None,
            net_income=None,
            net_income_prior_year=None,
            gross_profit=None,
            total_assets=None,
            total_liabilities=None,
            stockholders_equity=None,
            eps_diluted=None,
        ),
    ]
    path = write_fundamentals(original, tmp_path / "us_stocks_fundamentals.csv")

    restored = read_fundamentals(path)

    assert restored == original


def test_isin_map_round_trip(tmp_path):
    original = [
        IsinEntry(symbol="11B.PL", isin="PL11BTS00015"),
        IsinEntry(symbol="EAT.PL", isin="ES0105375002"),
    ]
    path = write_isin_map(original, tmp_path / "gpw_isin.csv")

    assert read_isin_map(path) == original


def test_technicals_round_trip_preserves_values_and_none(tmp_path):
    original = [
        Technicals(
            symbol="AAPL.US",
            date="2026-09-16",
            close=333.08,
            sma_20=320.0,
            sma_50=310.0,
            sma_200=None,
            ema_12=325.0,
            ema_26=318.0,
            rsi_14=62.5,
            macd=7.0,
            macd_signal=5.5,
            macd_histogram=1.5,
            bb_upper=340.0,
            bb_middle=320.0,
            bb_lower=300.0,
            atr_14=8.25,
        )
    ]
    path = write_technicals(original, tmp_path / "technicals.csv")

    assert read_technicals(path) == original


def test_scores_round_trip_preserves_values_and_none_fundamental_score(tmp_path):
    original = [
        Score(
            symbol="AAPL.US",
            date="2026-09-16",
            close=333.08,
            technical_score=80.0,
            fundamental_score=100.0,
            composite_score=88.0,
            verdict="BUY",
            rationale="price above SMA200 (long-term uptrend); strong net margin (20.0% > 15%)",
        ),
        Score(
            symbol="XYZ.PL",
            date="2026-09-16",
            close=12.5,
            technical_score=-100.0,
            fundamental_score=None,
            composite_score=-100.0,
            verdict="SELL",
            rationale="price below SMA200 (long-term downtrend)",
        ),
    ]
    path = write_scores(original, tmp_path / "scores.csv")

    assert read_scores(path) == original
