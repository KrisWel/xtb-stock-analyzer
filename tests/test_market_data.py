import json

import pytest

from xtb_analyzer.market_data import (
    Bar,
    YahooChartClient,
    YahooFinanceError,
    merge_bars,
    safe_filename,
)


def _chart_payload(timestamps, opens, highs, lows, closes, volumes, error=None):
    return {
        "chart": {
            "result": None
            if error
            else [
                {
                    "meta": {"symbol": "AAPL"},
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": volumes,
                            }
                        ]
                    },
                }
            ],
            "error": error,
        }
    }


def _fake_getter(payload):
    calls = []

    def getter(url, params):
        calls.append((url, params))
        return json.dumps(payload).encode("utf-8")

    return getter, calls


def test_get_bars_parses_a_clean_payload():
    payload = _chart_payload(
        timestamps=[1694000000, 1694086400],
        opens=[180.0, 181.5],
        highs=[182.0, 183.0],
        lows=[179.0, 180.5],
        closes=[181.0, 182.5],
        volumes=[1_000_000, 1_200_000],
    )
    getter, calls = _fake_getter(payload)
    client = YahooChartClient(getter=getter)

    bars = client.get_bars("AAPL", range_="5y")

    assert len(bars) == 2
    assert bars[0] == Bar(
        date="2023-09-06", open=180.0, high=182.0, low=179.0, close=181.0, volume=1_000_000
    )
    url, params = calls[0]
    assert url.endswith("/AAPL")
    assert params == {"interval": "1d", "range": "5y"}


def test_get_bars_skips_null_sessions():
    payload = _chart_payload(
        timestamps=[1694000000, 1694086400],
        opens=[180.0, None],
        highs=[182.0, None],
        lows=[179.0, None],
        closes=[181.0, None],
        volumes=[1_000_000, None],
    )
    getter, _ = _fake_getter(payload)
    client = YahooChartClient(getter=getter)

    bars = client.get_bars("AAPL")

    assert len(bars) == 1
    assert bars[0].date == "2023-09-06"


def test_get_bars_uses_period1_period2_for_incremental_fetch():
    payload = _chart_payload([1694000000], [1.0], [1.0], [1.0], [1.0], [1])
    getter, calls = _fake_getter(payload)
    client = YahooChartClient(getter=getter)

    client.get_bars("AAPL", period1=1694000000, period2=1694999999)

    _, params = calls[0]
    assert params == {"interval": "1d", "period1": "1694000000", "period2": "1694999999"}
    assert "range" not in params


def test_get_bars_raises_on_chart_error():
    payload = _chart_payload(
        [], [], [], [], [], [], error={"code": "Not Found", "description": "x"}
    )
    getter, _ = _fake_getter(payload)
    client = YahooChartClient(getter=getter)

    with pytest.raises(YahooFinanceError):
        client.get_bars("NOPE")


def test_get_bars_raises_on_empty_result():
    getter, _ = _fake_getter({"chart": {"result": [], "error": None}})
    client = YahooChartClient(getter=getter)

    with pytest.raises(YahooFinanceError):
        client.get_bars("AAPL")


def test_merge_bars_dedups_and_new_wins():
    existing = [
        Bar(date="2026-01-01", open=1, high=2, low=0.5, close=1.5, volume=100),
        Bar(date="2026-01-02", open=1.5, high=2.5, low=1, close=2, volume=110),
    ]
    new = [
        Bar(date="2026-01-02", open=1.6, high=2.6, low=1.1, close=2.1, volume=999),
        Bar(date="2026-01-03", open=2, high=3, low=1.5, close=2.5, volume=120),
    ]

    merged = merge_bars(existing, new)

    assert [b.date for b in merged] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert merged[1].volume == 999


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("AAPL", "AAPL"), ("CDR.WA", "CDR.WA"), ("BRK-B", "BRK-B"), ("^GSPC", "_GSPC")],
)
def test_safe_filename(symbol, expected):
    assert safe_filename(symbol) == expected
