import pytest

from xtb_analyzer.portfolio import (
    Position,
    build_portfolio_row,
    describe_action,
    trade_to_position,
)
from xtb_analyzer.scoring import Score


def _score(**overrides) -> Score:
    base = dict(
        symbol="CDR.WA",
        date="2026-09-18",
        close=100.0,
        technical_score=0.0,
        fundamental_score=None,
        composite_score=0.0,
        verdict="HOLD",
        rationale="insufficient data for any signal",
    )
    base.update(overrides)
    return Score(**base)


def test_trade_to_position_maps_cmd_0_to_buy():
    position = trade_to_position({"symbol": "CDR.PL", "cmd": 0, "volume": 10.0, "open_price": 80.0})

    assert position == Position(symbol="CDR.PL", side="BUY", volume=10.0, open_price=80.0)


def test_trade_to_position_maps_cmd_1_to_sell():
    position = trade_to_position({"symbol": "CDR.PL", "cmd": 1, "volume": 5.0, "open_price": 120.0})

    assert position.side == "SELL"


@pytest.mark.parametrize(
    ("side", "verdict", "expected_substring"),
    [
        ("BUY", "BUY", "supports"),
        ("SELL", "SELL", "supports"),
        ("BUY", "SELL", "opposes"),
        ("SELL", "BUY", "opposes"),
        ("BUY", "HOLD", "no strong signal"),
        ("SELL", "HOLD", "no strong signal"),
    ],
)
def test_describe_action_compares_side_against_verdict(side, verdict, expected_substring):
    assert expected_substring in describe_action(side, verdict)


def test_build_portfolio_row_computes_pnl_for_a_buy_position_in_profit():
    position = Position(symbol="CDR.PL", side="BUY", volume=10.0, open_price=80.0)
    score = _score(close=100.0, verdict="BUY", composite_score=50.0)

    row = build_portfolio_row(position, score)

    assert row.current_price == 100.0
    assert row.market_value == pytest.approx(1000.0)
    assert row.unrealized_pnl == pytest.approx(200.0)  # (100-80) * 10
    assert row.unrealized_pnl_pct == pytest.approx(0.25)  # (100-80) / 80
    assert row.action == "signal supports the open BUY position (BUY)"
    assert row.verdict == "BUY"


def test_build_portfolio_row_computes_pnl_for_a_buy_position_at_a_loss():
    position = Position(symbol="CDR.PL", side="BUY", volume=10.0, open_price=100.0)
    score = _score(close=80.0, verdict="SELL", composite_score=-50.0)

    row = build_portfolio_row(position, score)

    assert row.unrealized_pnl == pytest.approx(-200.0)  # (80-100) * 10
    assert row.unrealized_pnl_pct == pytest.approx(-0.20)
    assert row.action == "signal opposes the open BUY position (SELL) — review the position"


def test_build_portfolio_row_inverts_pnl_direction_for_a_sell_position():
    # a SELL position profits when price falls
    position = Position(symbol="CDR.PL", side="SELL", volume=10.0, open_price=100.0)
    score = _score(close=80.0, verdict="SELL")

    row = build_portfolio_row(position, score)

    assert row.unrealized_pnl == pytest.approx(200.0)  # -1 * (80-100) * 10
    assert row.unrealized_pnl_pct == pytest.approx(0.20)


def test_build_portfolio_row_handles_zero_open_price_without_dividing_by_zero():
    position = Position(symbol="CDR.PL", side="BUY", volume=1.0, open_price=0.0)
    score = _score(close=10.0)

    row = build_portfolio_row(position, score)

    assert row.unrealized_pnl_pct == 0.0
