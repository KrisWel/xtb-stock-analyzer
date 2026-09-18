"""Stage 6: combine technicals (and fundamentals, when available) into a
transparent buy/hold/sell verdict with a plain-English rationale.

Deliberately rule-based rather than a black-box model, so every verdict can
be explained by listing which signals fired: the roadmap calls for "a
transparent buy / sell / hold verdict with rationale", not a score nobody
can audit.

Two independent sub-scores, each normalised to the same ``-100..100`` scale
so they can be combined or compared regardless of how many of their inputs
were actually available for a given instrument:

* :func:`score_technicals` — trend (price vs SMA20/50/200), momentum
  (RSI, MACD) and mean-reversion (Bollinger Bands). Works for every
  instrument with enough OHLCV history, in any universe.
* :func:`score_fundamentals` — profitability (net margin), growth (revenue
  YoY) and balance-sheet risk (liabilities/equity). Only available where
  stage 4 fundamentals exist, currently the ``us_stocks`` universe — GPW
  companies file via KNF/ESPI, not SEC's XBRL system, so no free structured
  fundamentals source has been found for them yet (see docs/PROGRESS.md).

:func:`compute_score` combines the two: fundamentals get a 40% weight when
present, otherwise the composite is technicals-only. Each signal's point
value is only counted toward the achievable maximum when its underlying
indicator actually has data, so an instrument with a short history (no
SMA 200 yet) is scored fairly against its available signals rather than
being penalised for missing ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fundamentals import Fundamentals
from .technicals import Technicals

#: Composite = fundamental_weight * fundamental_score + (1 - fundamental_weight) * technical_score,
#: when a fundamentals row is available; technicals-only otherwise.
FUNDAMENTAL_WEIGHT = 0.4

BUY_THRESHOLD = 40.0
SELL_THRESHOLD = -40.0


@dataclass(frozen=True)
class Score:
    """One instrument's verdict, with the signals that produced it."""

    symbol: str
    date: str
    close: float
    technical_score: float
    fundamental_score: float | None
    composite_score: float
    verdict: str
    rationale: str

    @classmethod
    def csv_columns(cls) -> list[str]:
        return [
            "symbol",
            "date",
            "close",
            "technical_score",
            "fundamental_score",
            "composite_score",
            "verdict",
            "rationale",
        ]

    def as_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "date": self.date,
            "close": repr(self.close),
            "technical_score": repr(self.technical_score),
            "fundamental_score": (
                "" if self.fundamental_score is None else repr(self.fundamental_score)
            ),
            "composite_score": repr(self.composite_score),
            "verdict": self.verdict,
            "rationale": self.rationale,
        }


def _normalize(raw: float, max_possible: float) -> float:
    """Scale ``raw`` (a signed sum of per-signal points) onto ``-100..100``."""
    if max_possible == 0:
        return 0.0
    return max(-100.0, min(100.0, 100.0 * raw / max_possible))


def score_technicals(t: Technicals) -> tuple[float, list[str]]:
    """Trend/momentum/mean-reversion score from a single :class:`Technicals` row."""
    raw = 0.0
    max_possible = 0.0
    reasons: list[str] = []

    if t.sma_200 is not None:
        max_possible += 2
        if t.close > t.sma_200:
            raw += 2
            reasons.append("price above SMA200 (long-term uptrend)")
        else:
            raw -= 2
            reasons.append("price below SMA200 (long-term downtrend)")

    if t.sma_50 is not None and t.sma_200 is not None:
        max_possible += 1
        if t.sma_50 > t.sma_200:
            raw += 1
            reasons.append("SMA50 above SMA200 (golden-cross state)")
        else:
            raw -= 1
            reasons.append("SMA50 below SMA200 (death-cross state)")

    if t.sma_20 is not None:
        max_possible += 1
        if t.close > t.sma_20:
            raw += 1
            reasons.append("price above SMA20 (short-term uptrend)")
        else:
            raw -= 1
            reasons.append("price below SMA20 (short-term downtrend)")

    if t.rsi_14 is not None:
        max_possible += 2
        if t.rsi_14 < 30:
            raw += 2
            reasons.append(f"RSI oversold ({t.rsi_14:.1f} < 30)")
        elif t.rsi_14 > 70:
            raw -= 2
            reasons.append(f"RSI overbought ({t.rsi_14:.1f} > 70)")

    if t.macd is not None and t.macd_signal is not None:
        max_possible += 1
        if t.macd > t.macd_signal:
            raw += 1
            reasons.append("MACD above signal line (bullish)")
        else:
            raw -= 1
            reasons.append("MACD below signal line (bearish)")

    if t.macd_histogram is not None:
        max_possible += 1
        if t.macd_histogram > 0:
            raw += 1
            reasons.append("MACD histogram positive (momentum building)")
        else:
            raw -= 1
            reasons.append("MACD histogram negative (momentum fading)")

    if t.bb_lower is not None and t.bb_upper is not None:
        max_possible += 2
        if t.close <= t.bb_lower:
            raw += 2
            reasons.append("price at/below lower Bollinger Band (potentially oversold)")
        elif t.close >= t.bb_upper:
            raw -= 2
            reasons.append("price at/above upper Bollinger Band (potentially overbought)")

    return _normalize(raw, max_possible), reasons


def score_fundamentals(f: Fundamentals) -> tuple[float, list[str]]:
    """Profitability/growth/leverage score from a single :class:`Fundamentals` row."""
    raw = 0.0
    max_possible = 0.0
    reasons: list[str] = []

    net_margin = f.net_margin
    if net_margin is not None:
        max_possible += 2
        if net_margin > 0.15:
            raw += 2
            reasons.append(f"strong net margin ({net_margin:.1%} > 15%)")
        elif net_margin > 0:
            raw += 1
            reasons.append(f"positive net margin ({net_margin:.1%})")
        else:
            raw -= 2
            reasons.append(f"negative net margin ({net_margin:.1%}, unprofitable)")

    revenue_growth = f.revenue_growth
    if revenue_growth is not None:
        max_possible += 2
        if revenue_growth > 0.10:
            raw += 2
            reasons.append(f"strong revenue growth ({revenue_growth:.1%} YoY)")
        elif revenue_growth > 0:
            raw += 1
            reasons.append(f"positive revenue growth ({revenue_growth:.1%} YoY)")
        else:
            raw -= 1
            reasons.append(f"revenue declined ({revenue_growth:.1%} YoY)")

    leverage = f.liabilities_to_equity
    if leverage is not None:
        max_possible += 1
        if leverage < 1.0:
            raw += 1
            reasons.append(f"moderate leverage (liabilities/equity = {leverage:.2f})")
        elif leverage > 3.0:
            raw -= 1
            reasons.append(f"high leverage (liabilities/equity = {leverage:.2f})")

    return _normalize(raw, max_possible), reasons


def verdict_from_score(score: float) -> str:
    if score >= BUY_THRESHOLD:
        return "BUY"
    if score <= SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


def compute_score(t: Technicals, fundamentals: Fundamentals | None = None) -> Score:
    """Combine one instrument's technicals (and optional fundamentals) into a verdict."""
    technical_score, technical_reasons = score_technicals(t)

    fundamental_score: float | None = None
    reasons = list(technical_reasons)
    if fundamentals is not None:
        fundamental_score, fundamental_reasons = score_fundamentals(fundamentals)
        reasons = reasons + fundamental_reasons
        composite = (
            FUNDAMENTAL_WEIGHT * fundamental_score + (1 - FUNDAMENTAL_WEIGHT) * technical_score
        )
    else:
        composite = technical_score

    return Score(
        symbol=t.symbol,
        date=t.date,
        close=t.close,
        technical_score=technical_score,
        fundamental_score=fundamental_score,
        composite_score=composite,
        verdict=verdict_from_score(composite),
        rationale="; ".join(reasons) if reasons else "insufficient data for any signal",
    )
