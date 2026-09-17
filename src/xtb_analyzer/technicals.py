"""Stage 5: trend, momentum and volatility indicators from stored OHLCV bars.

Pure computation over whatever :mod:`xtb_analyzer.market_data` already fetched
— no network, no account, works against any of the OHLCV directories the
project produces (``data/ohlcv``, ``data/us_stocks_ohlcv``,
``data/gpw_ohlcv``, ...). Each ``*_series`` function returns one value per bar
(``None`` wherever there isn't enough history yet, e.g. the first 19 bars of
a 20-period SMA); :func:`compute_technicals` takes the latest value of each
into one per-instrument snapshot, the same shape stage 4's ``Fundamentals``
uses.

Formulas follow the standard definitions (Wilder's original smoothing for
RSI/ATR, the usual 12/26/9 MACD, a 20-period/2-standard-deviation Bollinger
Band) — see the docstring on each ``*_series`` function for the exact
reference and the tests for hand-checked values.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .market_data import Bar

#: Bars needed for the slowest indicator (SMA 200) to produce a single value.
#: Below this, compute_technicals still runs — later indicators just stay None.
MIN_BARS_FOR_SMA_200 = 200


@dataclass(frozen=True)
class Technicals:
    """Latest-bar snapshot of every indicator, one row per instrument."""

    symbol: str
    date: str
    close: float
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_12: float | None
    ema_26: float | None
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None
    atr_14: float | None

    @classmethod
    def csv_columns(cls) -> list[str]:
        return [
            "symbol",
            "date",
            "close",
            "sma_20",
            "sma_50",
            "sma_200",
            "ema_12",
            "ema_26",
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_histogram",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "atr_14",
        ]

    def as_dict(self) -> dict[str, str]:
        return {column: _to_csv_cell(getattr(self, column)) for column in self.csv_columns()}


def sma_series(closes: list[float], period: int) -> list[float | None]:
    """Simple moving average — the mean of the trailing ``period`` closes."""
    result: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1 : i + 1]) / period
    return result


def ema_series(closes: list[float], period: int) -> list[float | None]:
    """Exponential moving average, seeded with the first SMA(period)."""
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period:
        return result
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    result[period - 1] = seed
    prev = seed
    for i in range(period, len(closes)):
        prev = closes[i] * k + prev * (1 - k)
        result[i] = prev
    return result


def rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    """Relative Strength Index, Wilder's original smoothing.

    The first value uses a simple average of the first ``period`` gains/losses;
    every value after that smooths in the new gain/loss at weight ``1/period``
    (Wilder's method — not a plain EMA, which uses ``2/(period+1)``).
    """
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def macd_series(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Return ``(macd, signal, histogram)`` — the standard 12/26/9 MACD."""
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    macd: list[float | None] = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow, strict=True)
    ]

    macd_values = [m for m in macd if m is not None]
    signal_on_values = ema_series(macd_values, signal)
    signal_line: list[float | None] = [None] * len(macd)
    offset = len(macd) - len(macd_values)
    for i, value in enumerate(signal_on_values):
        signal_line[offset + i] = value

    histogram: list[float | None] = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(macd, signal_line, strict=True)
    ]
    return macd, signal_line, histogram


def bollinger_bands_series(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Return ``(upper, middle, lower)`` — SMA(period) +/- num_std sample std-devs."""
    middle = sma_series(closes, period)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mid = sum(window) / period  # == middle[i]
        std = statistics.pstdev(window)
        upper[i] = mid + num_std * std
        lower[i] = mid - num_std * std
    return upper, middle, lower


def atr_series(bars: list[Bar], period: int = 14) -> list[float | None]:
    """Average True Range, Wilder's original smoothing (same method as RSI)."""
    result: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return result

    true_ranges = []
    for i in range(1, len(bars)):
        high, low, prev_close = bars[i].high, bars[i].low, bars[i - 1].close
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    avg_tr = sum(true_ranges[:period]) / period
    result[period] = avg_tr
    for i in range(period, len(true_ranges)):
        avg_tr = (avg_tr * (period - 1) + true_ranges[i]) / period
        result[i + 1] = avg_tr

    return result


def compute_technicals(symbol: str, bars: list[Bar]) -> Technicals:
    """Compute every indicator and keep only the latest (most recent bar) value."""
    closes = [bar.close for bar in bars]

    sma_20 = sma_series(closes, 20)
    sma_50 = sma_series(closes, 50)
    sma_200 = sma_series(closes, 200)
    ema_12 = ema_series(closes, 12)
    ema_26 = ema_series(closes, 26)
    rsi_14 = rsi_series(closes, 14)
    macd, macd_signal, macd_hist = macd_series(closes)
    bb_upper, bb_middle, bb_lower = bollinger_bands_series(closes)
    atr_14 = atr_series(bars, 14)

    return Technicals(
        symbol=symbol,
        date=bars[-1].date,
        close=closes[-1],
        sma_20=sma_20[-1],
        sma_50=sma_50[-1],
        sma_200=sma_200[-1],
        ema_12=ema_12[-1],
        ema_26=ema_26[-1],
        rsi_14=rsi_14[-1],
        macd=macd[-1],
        macd_signal=macd_signal[-1],
        macd_histogram=macd_hist[-1],
        bb_upper=bb_upper[-1],
        bb_middle=bb_middle[-1],
        bb_lower=bb_lower[-1],
        atr_14=atr_14[-1],
    )


def _to_csv_cell(value: float | str | None) -> str:
    if value is None:
        return ""
    return repr(value) if isinstance(value, float) else str(value)
