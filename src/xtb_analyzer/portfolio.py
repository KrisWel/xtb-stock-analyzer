"""Stage 7: overlay real XTB holdings against stage 6's scoring output.

Two small pieces, kept independent so each can be tested (and reasoned
about) without the other:

* :class:`Position` — one open position as XTB's ``getTrades`` reports it
  (symbol, side, volume, entry price). ``trade_to_position`` reshapes the
  raw xAPI record; **not verified live**, since no session so far has had
  XTB credentials (see ``docs/xtb-api-notes.md``) — same caveat
  ``instruments.csv``/``identity_map.csv`` already carry for the primary
  XTB universe.
* :func:`build_portfolio_row` — combines one :class:`Position` with the
  matching :class:`~xtb_analyzer.scoring.Score` row (already carrying the
  latest close, stage 6's verdict, and its rationale) into one
  :class:`PortfolioRow`: current market value, unrealized P&L, and a plain
  next-step :func:`describe_action` derived from comparing the position's
  side against the verdict.

Positions and scores live in different symbol namespaces (an XTB symbol
like ``CDR.PL`` vs. the Yahoo ticker ``CDR.WA`` that stage 5/6 key their
output by), the same mismatch stage 6 already bridges via the identity map
— see ``cli.py::cmd_portfolio``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .scoring import Score

#: XTB's numeric trade-direction codes for cash instruments (see
#: docs/xtb-api-notes.md) — 0 = BUY, 1 = SELL. Not verified live.
TRADE_CMD_BUY = 0
TRADE_CMD_SELL = 1


@dataclass(frozen=True)
class Position:
    """One open position, as reported by XTB's ``getTrades``."""

    symbol: str
    side: str
    volume: float
    open_price: float

    @classmethod
    def csv_columns(cls) -> list[str]:
        return ["symbol", "side", "volume", "open_price"]

    def as_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "volume": repr(self.volume),
            "open_price": repr(self.open_price),
        }


def trade_to_position(trade: dict) -> Position:
    """Reshape one raw ``getTrades`` record into a :class:`Position`."""
    side = "SELL" if trade.get("cmd") == TRADE_CMD_SELL else "BUY"
    return Position(
        symbol=trade["symbol"],
        side=side,
        volume=float(trade["volume"]),
        open_price=float(trade["open_price"]),
    )


@dataclass(frozen=True)
class PortfolioRow:
    """One position overlaid with its latest score — the per-position condition."""

    symbol: str
    side: str
    volume: float
    open_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    verdict: str
    composite_score: float
    action: str
    rationale: str

    @classmethod
    def csv_columns(cls) -> list[str]:
        return [
            "symbol",
            "side",
            "volume",
            "open_price",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "verdict",
            "composite_score",
            "action",
            "rationale",
        ]

    def as_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "volume": repr(self.volume),
            "open_price": repr(self.open_price),
            "current_price": repr(self.current_price),
            "market_value": repr(self.market_value),
            "unrealized_pnl": repr(self.unrealized_pnl),
            "unrealized_pnl_pct": repr(self.unrealized_pnl_pct),
            "verdict": self.verdict,
            "composite_score": repr(self.composite_score),
            "action": self.action,
            "rationale": self.rationale,
        }


def _pnl_multiplier(side: str) -> float:
    """A SELL position profits when price falls — invert the raw price delta."""
    return -1.0 if side == "SELL" else 1.0


def describe_action(side: str, verdict: str) -> str:
    """Plain-English next step from a position's side vs. the latest verdict."""
    agrees = (side == "BUY" and verdict == "BUY") or (side == "SELL" and verdict == "SELL")
    opposes = (side == "BUY" and verdict == "SELL") or (side == "SELL" and verdict == "BUY")
    if opposes:
        return f"signal opposes the open {side} position ({verdict}) — review the position"
    if agrees:
        return f"signal supports the open {side} position ({verdict})"
    return "no strong signal either way — hold"


def build_portfolio_row(position: Position, score: Score) -> PortfolioRow:
    """Combine one open position with its matching score into a condition row."""
    multiplier = _pnl_multiplier(position.side)
    current_price = score.close
    market_value = position.volume * current_price
    price_delta = current_price - position.open_price
    unrealized_pnl = multiplier * price_delta * position.volume
    unrealized_pnl_pct = (
        multiplier * price_delta / position.open_price if position.open_price else 0.0
    )

    return PortfolioRow(
        symbol=position.symbol,
        side=position.side,
        volume=position.volume,
        open_price=position.open_price,
        current_price=current_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        verdict=score.verdict,
        composite_score=score.composite_score,
        action=describe_action(position.side, score.verdict),
        rationale=score.rationale,
    )
