"""Reading and writing the instrument snapshot (CSV + metadata + raw dump)."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fundamentals import Fundamentals
from .gpw import IsinEntry
from .identity import IdentityMapping
from .market_data import Bar
from .models import Instrument
from .portfolio import PortfolioRow, Position
from .scoring import Score
from .sec_edgar import CikEntry
from .technicals import Technicals

BOOL_FIELDS = {"long_only", "short_selling"}
INT_FIELDS = {"precision", "margin_mode", "instrument_type"}
FLOAT_FIELDS = {"contract_size", "leverage"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_raw(records: list[dict[str, Any]], path: Path) -> Path:
    """Persist the untouched ``getAllSymbols`` payload (git-ignored, useful for re-runs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def read_raw(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} does not contain a list of symbol records")
    return data


def write_snapshot(instruments: Iterable[Instrument], path: Path) -> Path:
    """Write the committed CSV snapshot — the offline fallback source."""
    instruments = list(instruments)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=Instrument.csv_columns())
        writer.writeheader()
        for instrument in instruments:
            writer.writerow(instrument.as_dict())
    return path


def read_snapshot(path: Path) -> list[Instrument]:
    """Load the committed CSV snapshot back into :class:`Instrument` objects."""
    with path.open(newline="", encoding="utf-8") as handle:
        return [_row_to_instrument(row) for row in csv.DictReader(handle)]


def write_metadata(path: Path, *, source: str, total: int, kept: int, rejections: Counter) -> Path:
    payload = {
        "fetched_at": utc_now_iso(),
        "source": source,
        "records_returned": total,
        "instruments_kept": kept,
        "rejections": dict(rejections.most_common()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_identity_map(mappings: Iterable[IdentityMapping], path: Path) -> Path:
    """Write the ``symbol -> external identifier`` map (Yahoo ticker, FIGI)."""
    mappings = list(mappings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=IdentityMapping.csv_columns())
        writer.writeheader()
        for mapping in mappings:
            writer.writerow(mapping.as_dict())
    return path


def read_identity_map(path: Path) -> list[IdentityMapping]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            IdentityMapping(
                symbol=row["symbol"],
                ticker=row["ticker"],
                market=row["market"],
                currency=row["currency"],
                yahoo_symbol=row["yahoo_symbol"] or None,
                figi=row["figi"] or None,
            )
            for row in csv.DictReader(handle)
        ]


def write_ohlcv(bars: Iterable[Bar], path: Path) -> Path:
    """Write one instrument's bar history, sorted by date."""
    bars = sorted(bars, key=lambda bar: bar.date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=Bar.csv_columns())
        writer.writeheader()
        for bar in bars:
            writer.writerow(bar.as_dict())
    return path


def read_ohlcv(path: Path) -> list[Bar]:
    """Load a stored bar history; an absent file (no history fetched yet) is empty."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            Bar(
                date=row["date"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
            )
            for row in csv.DictReader(handle)
        ]


def write_cik_map(entries: Iterable[CikEntry], path: Path) -> Path:
    """Write the ``symbol -> SEC CIK`` sidecar for the ``us_stocks`` universe."""
    entries = list(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CikEntry.csv_columns())
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.as_dict())
    return path


def read_cik_map(path: Path) -> list[CikEntry]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            CikEntry(symbol=row["symbol"], cik=int(row["cik"])) for row in csv.DictReader(handle)
        ]


def write_fundamentals(rows: Iterable[Fundamentals], path: Path) -> Path:
    """Write one CSV row of raw, filed figures per company."""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=Fundamentals.csv_columns())
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
    return path


def read_fundamentals(path: Path) -> list[Fundamentals]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [_row_to_fundamentals(row) for row in csv.DictReader(handle)]


_FUNDAMENTALS_FLOAT_FIELDS = {
    "revenue",
    "revenue_prior_year",
    "net_income",
    "net_income_prior_year",
    "gross_profit",
    "total_assets",
    "total_liabilities",
    "stockholders_equity",
    "eps_diluted",
}


def _row_to_fundamentals(row: dict[str, str]) -> Fundamentals:
    values: dict[str, Any] = {
        "symbol": row["symbol"],
        "cik": int(row["cik"]),
        "fiscal_year": int(row["fiscal_year"]) if row.get("fiscal_year") else None,
        "fiscal_year_end": row.get("fiscal_year_end") or None,
    }
    for column in _FUNDAMENTALS_FLOAT_FIELDS:
        raw = row.get(column, "")
        values[column] = float(raw) if raw else None
    return Fundamentals(**values)


def write_isin_map(entries: Iterable[IsinEntry], path: Path) -> Path:
    """Write the ``symbol -> ISIN`` sidecar for the ``gpw`` universe."""
    entries = list(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=IsinEntry.csv_columns())
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.as_dict())
    return path


def read_isin_map(path: Path) -> list[IsinEntry]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [IsinEntry(symbol=row["symbol"], isin=row["isin"]) for row in csv.DictReader(handle)]


def write_technicals(rows: Iterable[Technicals], path: Path) -> Path:
    """Write one CSV row of latest indicator values per instrument."""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=Technicals.csv_columns())
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
    return path


def read_technicals(path: Path) -> list[Technicals]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [_row_to_technicals(row) for row in csv.DictReader(handle)]


_TECHNICALS_FLOAT_FIELDS = {
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
}


def _row_to_technicals(row: dict[str, str]) -> Technicals:
    values: dict[str, Any] = {"symbol": row["symbol"], "date": row["date"]}
    for column in _TECHNICALS_FLOAT_FIELDS:
        raw = row.get(column, "")
        values[column] = float(raw) if raw else None
    return Technicals(**values)


def write_scores(rows: Iterable[Score], path: Path) -> Path:
    """Write one CSV row of buy/hold/sell verdicts per instrument."""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=Score.csv_columns())
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
    return path


def read_scores(path: Path) -> list[Score]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [_row_to_score(row) for row in csv.DictReader(handle)]


def _row_to_score(row: dict[str, str]) -> Score:
    fundamental_score = row.get("fundamental_score", "")
    return Score(
        symbol=row["symbol"],
        date=row["date"],
        close=float(row["close"]),
        technical_score=float(row["technical_score"]),
        fundamental_score=float(fundamental_score) if fundamental_score else None,
        composite_score=float(row["composite_score"]),
        verdict=row["verdict"],
        rationale=row["rationale"],
    )


def write_positions(positions: Iterable[Position], path: Path) -> Path:
    """Write the account's open positions (stage 7), straight from ``getTrades``."""
    positions = list(positions)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=Position.csv_columns())
        writer.writeheader()
        for position in positions:
            writer.writerow(position.as_dict())
    return path


def read_positions(path: Path) -> list[Position]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            Position(
                symbol=row["symbol"],
                side=row["side"],
                volume=float(row["volume"]),
                open_price=float(row["open_price"]),
            )
            for row in csv.DictReader(handle)
        ]


def write_portfolio(rows: Iterable[PortfolioRow], path: Path) -> Path:
    """Write the per-position condition report (stage 7)."""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PortfolioRow.csv_columns())
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
    return path


def read_portfolio(path: Path) -> list[PortfolioRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [_row_to_portfolio_row(row) for row in csv.DictReader(handle)]


def _row_to_portfolio_row(row: dict[str, str]) -> PortfolioRow:
    return PortfolioRow(
        symbol=row["symbol"],
        side=row["side"],
        volume=float(row["volume"]),
        open_price=float(row["open_price"]),
        current_price=float(row["current_price"]),
        market_value=float(row["market_value"]),
        unrealized_pnl=float(row["unrealized_pnl"]),
        unrealized_pnl_pct=float(row["unrealized_pnl_pct"]),
        verdict=row["verdict"],
        composite_score=float(row["composite_score"]),
        action=row["action"],
        rationale=row["rationale"],
    )


def _row_to_instrument(row: dict[str, str]) -> Instrument:
    values: dict[str, Any] = {}
    for column in Instrument.csv_columns():
        raw = row.get(column, "")
        if column in BOOL_FIELDS:
            values[column] = {"True": True, "False": False}.get(raw)
        elif column in INT_FIELDS:
            values[column] = int(raw) if raw not in ("", "None") else None
        elif column in FLOAT_FIELDS:
            values[column] = float(raw) if raw not in ("", "None") else None
        else:
            values[column] = raw
    return Instrument(**values)
