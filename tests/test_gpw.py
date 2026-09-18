from pathlib import Path

import pytest

from xtb_analyzer.gpw import (
    ETF_AJAX_BODY,
    USER_AGENT,
    GpwError,
    build_isin_map,
    etf_to_symbol_record,
    fetch_etf_html,
    fetch_stocks_html,
    parse_etfs,
    parse_stocks,
    stock_to_symbol_record,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _stocks_html() -> str:
    return (FIXTURES / "gpw_stocks_sample.html").read_text(encoding="utf-8")


def _etf_html() -> str:
    return (FIXTURES / "gpw_etf_sample.html").read_text(encoding="utf-8")


def test_parse_stocks_extracts_ticker_isin_and_name():
    stocks = parse_stocks(_stocks_html())

    assert len(stocks) == 3
    by_ticker = {s.ticker: s for s in stocks}
    assert by_ticker["11B"].isin == "PL11BTS00015"
    assert by_ticker["11B"].name == "11 BIT STUDIOS SPÓŁKA AKCYJNA"
    # a foreign-domiciled issuer cross-listed on GPW's main market
    assert by_ticker["EAT"].isin == "ES0105375002"


def test_parse_stocks_raises_on_empty_or_unrecognised_html():
    with pytest.raises(GpwError):
        parse_stocks("<html><body>nothing here</body></html>")


def test_parse_etfs_extracts_ticker_isin_and_currency():
    etfs = parse_etfs(_etf_html())

    assert len(etfs) == 2
    by_ticker = {e.ticker: e for e in etfs}
    assert by_ticker["ETFBCASH"].isin == "PLBETWT00010"
    assert by_ticker["ETFBCASH"].currency == "PLN"
    # a foreign (Luxembourg) ISIN, still quoted on GPW in PLN
    assert by_ticker["ETFDAX"].isin == "LU0252633754"
    assert by_ticker["ETFDAX"].currency == "PLN"


def test_parse_etfs_raises_on_empty_or_unrecognised_html():
    with pytest.raises(GpwError):
        parse_etfs("<html><body>nothing here</body></html>")


def test_parse_etfs_strips_a_status_marker_appended_to_the_ticker_text():
    # verified live (2026-09-18): a suspended/newly-listed ETN's ticker came
    # back as "ETNVIRXRP  /Z" — the "/Z" status suffix is plain text in the
    # same <b> tag, separated only by extra whitespace, not its own markup
    html = (
        '<tr><td><a href="etf?isin=SE0021486156"><b>ETNVIRXRP  /Z</b></a></td>'
        '<td id="id_ISIN">SE0021486156</td><td id="id_Waluta">PLN</td></tr>'
    )

    etfs = parse_etfs(html)

    assert len(etfs) == 1
    assert etfs[0].ticker == "ETNVIRXRP"


def test_stock_to_symbol_record_is_pln_and_stock_category():
    stock = parse_stocks(_stocks_html())[0]

    record = stock_to_symbol_record(stock)

    assert record["symbol"] == "11B.PL"
    assert record["categoryName"] == "STC"
    assert record["currency"] == "PLN"
    assert "CFD" not in record["groupName"]


def test_etf_to_symbol_record_is_etf_category():
    etf = parse_etfs(_etf_html())[0]

    record = etf_to_symbol_record(etf)

    assert record["symbol"] == "ETFBCASH.PL"
    assert record["categoryName"] == "ETF"
    assert record["currency"] == "PLN"


def test_build_isin_map_covers_both_stocks_and_etfs():
    stocks = parse_stocks(_stocks_html())
    etfs = parse_etfs(_etf_html())

    entries = build_isin_map(stocks, etfs)

    assert len(entries) == len(stocks) + len(etfs)
    by_symbol = {e.symbol: e.isin for e in entries}
    assert by_symbol["11B.PL"] == "PL11BTS00015"
    assert by_symbol["ETFBCASH.PL"] == "PLBETWT00010"


def test_fetch_stocks_html_uses_compliant_user_agent():
    calls = []

    def getter(url, headers):
        calls.append((url, headers))
        return _stocks_html().encode("utf-8")

    html = fetch_stocks_html(getter=getter)

    assert "11B" in html
    url, headers = calls[0]
    assert "gpw.pl/spolki" in url
    assert headers["User-Agent"] == USER_AGENT


def test_fetch_etf_html_posts_the_expected_ajax_body():
    calls = []

    def poster(url, body, headers):
        calls.append((url, body, headers))
        return _etf_html().encode("utf-8")

    html = fetch_etf_html(poster=poster)

    assert "ETFBCASH" in html
    url, body, headers = calls[0]
    assert "ajaxindex.php" in url
    assert body == ETF_AJAX_BODY.encode("ascii")
    assert headers["User-Agent"] == USER_AGENT
