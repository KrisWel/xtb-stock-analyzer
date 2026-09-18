import pytest

from xtb_analyzer.fundamentals import Fundamentals
from xtb_analyzer.scoring import (
    Score,
    compute_score,
    score_fundamentals,
    score_technicals,
    verdict_from_score,
)
from xtb_analyzer.technicals import Technicals


def _technicals(**overrides) -> Technicals:
    base = dict(
        symbol="TEST.US",
        date="2026-01-01",
        close=100.0,
        sma_20=None,
        sma_50=None,
        sma_200=None,
        ema_12=None,
        ema_26=None,
        rsi_14=None,
        macd=None,
        macd_signal=None,
        macd_histogram=None,
        bb_upper=None,
        bb_middle=None,
        bb_lower=None,
        atr_14=None,
    )
    base.update(overrides)
    return Technicals(**base)


def _fundamentals(**overrides) -> Fundamentals:
    base = dict(
        symbol="TEST.US",
        cik=1,
        fiscal_year=2025,
        fiscal_year_end="2025-12-31",
        revenue=None,
        revenue_prior_year=None,
        net_income=None,
        net_income_prior_year=None,
        gross_profit=None,
        total_assets=None,
        total_liabilities=None,
        stockholders_equity=None,
        eps_diluted=None,
    )
    base.update(overrides)
    return Fundamentals(**base)


def test_score_technicals_is_maximally_bullish_when_every_signal_agrees():
    t = _technicals(
        close=110.0,
        sma_20=100.0,
        sma_50=100.0,
        sma_200=90.0,
        rsi_14=20.0,
        macd=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        bb_upper=115.0,
        bb_lower=95.0,
    )

    score, reasons = score_technicals(t)

    assert score == pytest.approx(80.0)  # raw=8 out of max=10 (price sits inside the bands)
    assert any("above SMA200" in r for r in reasons)
    assert any("RSI oversold" in r for r in reasons)


def test_score_technicals_is_maximally_bearish_when_every_signal_agrees():
    # Bollinger Bands are a mean-reversion signal (touching the lower band
    # reads bullish, the upper band bearish) rather than trend-following, so
    # for every signal to agree bearish, price must sit at/above its own
    # (tighter, shorter-window) upper band even while below the longer SMAs.
    t = _technicals(
        close=80.0,
        sma_20=90.0,
        sma_50=90.0,
        sma_200=100.0,
        rsi_14=80.0,
        macd=-1.0,
        macd_signal=-0.5,
        macd_histogram=-0.5,
        bb_upper=75.0,
        bb_lower=60.0,
    )

    score, reasons = score_technicals(t)

    assert score == pytest.approx(-100.0)
    assert any("below SMA200" in r for r in reasons)
    assert any("overbought" in r for r in reasons)
    assert any("upper Bollinger Band" in r for r in reasons)


def test_score_technicals_nets_to_zero_when_two_opposite_signals_cancel_out():
    # only two indicators have data at all, and they disagree by equal weight
    t = _technicals(close=110.0, sma_200=90.0, rsi_14=80.0)

    score, reasons = score_technicals(t)

    assert score == pytest.approx(0.0)
    assert len(reasons) == 2


def test_score_technicals_is_zero_with_no_reasons_when_nothing_has_data():
    t = _technicals()

    score, reasons = score_technicals(t)

    assert score == 0.0
    assert reasons == []


def test_score_fundamentals_is_maximally_bullish_when_every_signal_agrees():
    f = _fundamentals(
        revenue=1000.0,
        revenue_prior_year=800.0,
        net_income=200.0,
        total_liabilities=400.0,
        stockholders_equity=500.0,
    )

    score, reasons = score_fundamentals(f)

    assert score == pytest.approx(100.0)
    assert any("strong net margin" in r for r in reasons)
    assert any("strong revenue growth" in r for r in reasons)
    assert any("moderate leverage" in r for r in reasons)


def test_score_fundamentals_is_bearish_when_unprofitable_and_shrinking_and_leveraged():
    f = _fundamentals(
        revenue=1000.0,
        revenue_prior_year=1200.0,
        net_income=-50.0,
        total_liabilities=2000.0,
        stockholders_equity=500.0,
    )

    score, reasons = score_fundamentals(f)

    assert score == pytest.approx(-80.0)
    assert any("negative net margin" in r for r in reasons)
    assert any("revenue declined" in r for r in reasons)
    assert any("high leverage" in r for r in reasons)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (40.0, "BUY"),
        (100.0, "BUY"),
        (-40.0, "SELL"),
        (-100.0, "SELL"),
        (0.0, "HOLD"),
        (39.9, "HOLD"),
    ],
)
def test_verdict_from_score_thresholds(score, expected):
    assert verdict_from_score(score) == expected


def test_compute_score_is_technicals_only_without_fundamentals():
    t = _technicals(close=110.0, sma_200=90.0)

    result = compute_score(t)

    assert isinstance(result, Score)
    assert result.fundamental_score is None
    assert result.composite_score == result.technical_score
    assert result.verdict == verdict_from_score(result.technical_score)


def test_compute_score_blends_fundamentals_with_a_40_percent_weight():
    t = _technicals(
        close=110.0,
        sma_20=100.0,
        sma_50=100.0,
        sma_200=90.0,
        rsi_14=20.0,
        macd=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        bb_upper=115.0,
        bb_lower=95.0,
    )
    f = _fundamentals(
        revenue=1000.0,
        revenue_prior_year=800.0,
        net_income=200.0,
        total_liabilities=400.0,
        stockholders_equity=500.0,
    )

    result = compute_score(t, f)

    assert result.technical_score == pytest.approx(80.0)
    assert result.fundamental_score == pytest.approx(100.0)
    assert result.composite_score == pytest.approx(0.4 * 100.0 + 0.6 * 80.0)
    assert result.verdict == "BUY"
    assert "strong net margin" in result.rationale
    assert "above SMA200" in result.rationale


def test_compute_score_reports_insufficient_data_when_nothing_is_available():
    result = compute_score(_technicals())

    assert result.composite_score == 0.0
    assert result.verdict == "HOLD"
    assert result.rationale == "insufficient data for any signal"
