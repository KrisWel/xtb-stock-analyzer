from xtb_analyzer.filters import FilterConfig, classify, describe_universe, filter_instruments

CASH_SYMBOLS = {"AAPL.US", "CDR.PL", "IUSQ.DE"}


def test_only_cash_stocks_and_etfs_survive(sample_records):
    result = filter_instruments(sample_records)

    assert {i.symbol for i in result.instruments} == CASH_SYMBOLS
    assert result.total == len(sample_records)
    assert result.kept == 3


def test_asset_class_assignment(sample_records):
    result = filter_instruments(sample_records)
    by_symbol = {i.symbol: i.asset_class for i in result.instruments}

    assert by_symbol["AAPL.US"] == "STOCK"
    assert by_symbol["CDR.PL"] == "STOCK"
    assert by_symbol["IUSQ.DE"] == "ETF"


def test_results_are_sorted_by_symbol(sample_records):
    symbols = [i.symbol for i in filter_instruments(sample_records).instruments]
    assert symbols == sorted(symbols)


def test_every_rejection_rule_fires(sample_records):
    rejections = filter_instruments(sample_records).rejections

    assert rejections["cfd-symbol-suffix"] == 2  # AAPL.US_9, TSLA.US_4
    assert rejections["cfd-in-text"] == 1  # LYXGRE.FR
    assert rejections["not-long-only"] == 1  # SHORTONLY.US
    assert rejections["category=IND"] == 1
    assert rejections["category=FX"] == 1
    assert rejections["category=CMD"] == 1
    assert rejections["category=CRT"] == 1
    assert sum(rejections.values()) == len(sample_records) - 3


def test_leverage_rule_is_independent(sample_records):
    record = next(r for r in sample_records if r["symbol"] == "AAPL.US_9")
    config = FilterConfig(reject_cfd_suffix=False, reject_cfd_text=False, require_long_only=False)

    asset_class, reason = classify(record, config)

    assert asset_class is None
    assert reason == "leveraged(<100)"


def test_relaxed_config_keeps_more(sample_records):
    config = FilterConfig(
        reject_cfd_suffix=False, reject_cfd_text=False, min_leverage=None, require_long_only=False
    )
    result = filter_instruments(sample_records, config)

    # everything under the STC/ETF categories, CFD shadows included
    assert result.kept == 7


def test_unknown_category_is_reported_verbatim():
    asset_class, reason = classify({"symbol": "X", "categoryName": "WEIRD"})
    assert asset_class is None
    assert reason == "category=WEIRD"


def test_missing_category_is_reported():
    asset_class, reason = classify({"symbol": "X"})
    assert asset_class is None
    assert reason == "category=<empty>"


def test_describe_universe_counts_fields(sample_records):
    stats = describe_universe(sample_records)
    assert stats["categoryName"]["STC"] == 5
    assert stats["categoryName"]["ETF"] == 2
    assert set(stats) >= {"groupName", "currency", "leverage", "longOnly", "marginMode"}
