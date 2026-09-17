import pytest

from xtb_analyzer.market_data import Bar
from xtb_analyzer.technicals import (
    atr_series,
    bollinger_bands_series,
    compute_technicals,
    ema_series,
    macd_series,
    rsi_series,
    sma_series,
)


def _bar(date: str, close: float, high: float | None = None, low: float | None = None) -> Bar:
    return Bar(
        date=date,
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=1000,
    )


def test_sma_series_matches_hand_computed_averages():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]

    result = sma_series(closes, period=3)

    assert result == [None, None, 2.0, 3.0, 4.0]


def test_ema_series_seeds_with_sma_and_matches_linear_data():
    # for perfectly linear data the EMA recursion collapses onto the same
    # trend as the SMA seed, giving predictable hand-checkable values
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]

    result = ema_series(closes, period=3)

    assert result == [None, None, 2.0, 3.0, 4.0]


def test_ema_series_none_when_shorter_than_period():
    assert ema_series([1.0, 2.0], period=3) == [None, None]


def test_rsi_series_is_100_for_a_strictly_rising_series():
    closes = [float(i) for i in range(1, 21)]  # 1..20, every delta is +1

    result = rsi_series(closes, period=14)

    assert result[14] == 100.0
    assert result[-1] == 100.0
    assert result[:14] == [None] * 14


def test_rsi_series_is_0_for_a_strictly_falling_series():
    closes = [float(i) for i in range(20, 0, -1)]  # every delta is -1

    result = rsi_series(closes, period=14)

    assert result[14] == 0.0
    assert result[-1] == 0.0


def test_rsi_series_stays_near_50_for_alternating_equal_moves():
    # +1, -1, +1, -1, ... => gains and losses of equal size keep trading off,
    # so Wilder's smoothed averages stay close (not exactly equal, since the
    # recursion still carries a little of the starting phase) => RSI near 50
    closes = [10.0]
    for i in range(30):
        closes.append(closes[-1] + (1 if i % 2 == 0 else -1))

    result = rsi_series(closes, period=14)

    assert result[-1] == pytest.approx(50.0, abs=5.0)


def test_macd_series_is_zero_for_constant_prices():
    closes = [10.0] * 40

    macd, signal, histogram = macd_series(closes, fast=12, slow=26, signal=9)

    assert macd[-1] == pytest.approx(0.0)
    assert signal[-1] == pytest.approx(0.0)
    assert histogram[-1] == pytest.approx(0.0)
    assert len(macd) == len(signal) == len(histogram) == len(closes)


def test_macd_series_none_until_slow_ema_is_available():
    closes = [10.0] * 25  # one short of the 26-period slow EMA

    macd, signal, histogram = macd_series(closes)

    assert macd == [None] * 25
    assert signal == [None] * 25
    assert histogram == [None] * 25


def test_bollinger_bands_collapse_to_the_mean_for_constant_prices():
    closes = [10.0] * 20

    upper, middle, lower = bollinger_bands_series(closes, period=20, num_std=2.0)

    assert middle[-1] == 10.0
    assert upper[-1] == 10.0
    assert lower[-1] == 10.0


def test_bollinger_bands_widen_with_volatility():
    closes = [10.0, 12.0, 8.0, 11.0, 9.0, 13.0, 7.0, 10.0, 12.0, 8.0] * 2

    upper, middle, lower = bollinger_bands_series(closes, period=20, num_std=2.0)

    assert upper[-1] > middle[-1] > lower[-1]


def test_atr_series_converges_to_the_constant_true_range():
    # constant close of 100, high/low +-1 => true range is always 2 (the
    # high-low span always dominates |high - prev_close| / |low - prev_close|)
    bars = [_bar(f"2026-01-{i + 1:02d}", close=100.0, high=101.0, low=99.0) for i in range(20)]

    result = atr_series(bars, period=14)

    assert result[14] == pytest.approx(2.0)
    assert result[-1] == pytest.approx(2.0)
    assert result[:14] == [None] * 14


def test_atr_series_none_when_shorter_than_period():
    bars = [_bar(f"2026-01-{i + 1:02d}", close=100.0) for i in range(10)]

    assert atr_series(bars, period=14) == [None] * 10


def test_compute_technicals_returns_latest_bar_snapshot():
    bars = [_bar(f"2026-01-{i + 1:02d}", close=100.0 + i) for i in range(25)]

    result = compute_technicals("TEST.US", bars)

    assert result.symbol == "TEST.US"
    assert result.date == bars[-1].date
    assert result.close == bars[-1].close
    assert result.sma_20 is not None
    assert result.sma_200 is None  # not enough history
    assert result.rsi_14 == 100.0  # strictly rising closes
