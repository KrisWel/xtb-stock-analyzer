"""Command line entry point: ``xtb-analyzer <command>``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import (
    IDENTITY_MAP_CSV,
    OHLCV_DIR,
    RAW_DIR,
    SNAPSHOT_CSV,
    SNAPSHOT_META,
    US_STOCKS_CSV,
    US_STOCKS_META,
    ConfigError,
    load_credentials,
    load_env,
)
from .filters import FilterConfig, describe_universe, filter_instruments
from .identity import map_instruments
from .market_data import YahooChartClient, YahooFinanceError, merge_bars, safe_filename
from .openfigi import OpenFigiClient, OpenFigiError, build_jobs
from .sec_edgar import SecEdgarError, fetch_company_tickers, to_symbol_record
from .storage import (
    read_identity_map,
    read_ohlcv,
    read_raw,
    read_snapshot,
    write_identity_map,
    write_metadata,
    write_ohlcv,
    write_raw,
    write_snapshot,
)
from .xtb_client import XtbApiError, XtbClient

RAW_SYMBOLS = RAW_DIR / "all_symbols.json"

log = logging.getLogger("xtb_analyzer")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    try:
        return args.handler(args)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    except XtbApiError as exc:
        log.error("XTB API error: %s", exc)
        return 3
    except FileNotFoundError as exc:
        log.error("Missing file: %s", exc)
        return 4
    except OpenFigiError as exc:
        log.error("OpenFIGI error: %s", exc)
        return 5
    except YahooFinanceError as exc:
        log.error("Yahoo Finance error: %s", exc)
        return 6
    except SecEdgarError as exc:
        log.error("SEC EDGAR error: %s", exc)
        return 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xtb-analyzer", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch", help="download the instrument universe and refresh the snapshot"
    )
    fetch.add_argument(
        "--raw", type=Path, default=RAW_SYMBOLS, help="where to store the raw API payload"
    )
    fetch.add_argument("--output", type=Path, default=SNAPSHOT_CSV, help="snapshot CSV to write")
    fetch.add_argument(
        "--metadata", type=Path, default=SNAPSHOT_META, help="snapshot metadata JSON to write"
    )
    fetch.add_argument(
        "--from-raw", type=Path, help="skip the API and re-process an existing raw dump"
    )
    fetch.add_argument(
        "--keep-cfd", action="store_true", help="disable the CFD/leverage rules (debugging)"
    )
    fetch.set_defaults(handler=cmd_fetch)

    fetch_sec = sub.add_parser(
        "fetch-sec",
        help="alternative, login-free universe: US-listed stocks via SEC EDGAR",
    )
    fetch_sec.add_argument("--output", type=Path, default=US_STOCKS_CSV)
    fetch_sec.add_argument("--metadata", type=Path, default=US_STOCKS_META)
    fetch_sec.set_defaults(handler=cmd_fetch_sec)

    inspect = sub.add_parser("inspect", help="show field distributions used to tune the filters")
    inspect.add_argument("--from-raw", type=Path, default=RAW_SYMBOLS, help="raw dump to analyse")
    inspect.add_argument(
        "--live", action="store_true", help="fetch from the API instead of a raw dump"
    )
    inspect.add_argument("--top", type=int, default=15, help="values per field to display")
    inspect.set_defaults(handler=cmd_inspect)

    show = sub.add_parser(
        "show", help="read the committed snapshot (works offline, no credentials)"
    )
    show.add_argument("--snapshot", type=Path, default=SNAPSHOT_CSV)
    show.add_argument("--asset-class", choices=["STOCK", "ETF"], help="filter by asset class")
    show.add_argument("--market", help="filter by market code, e.g. US, PL, DE")
    show.add_argument("--limit", type=int, default=20, help="rows to print (0 = all)")
    show.set_defaults(handler=cmd_show)

    map_cmd = sub.add_parser("map", help="map the snapshot onto external tickers/FIGI (stage 2)")
    map_cmd.add_argument("--snapshot", type=Path, default=SNAPSHOT_CSV)
    map_cmd.add_argument("--output", type=Path, default=IDENTITY_MAP_CSV)
    map_cmd.add_argument(
        "--figi", action="store_true", help="also resolve FIGIs via OpenFIGI (network)"
    )
    map_cmd.add_argument(
        "--openfigi-api-key",
        default=None,
        help="OpenFIGI API key (raises the rate limit); defaults to $OPENFIGI_API_KEY",
    )
    map_cmd.set_defaults(handler=cmd_map)

    ohlcv = sub.add_parser(
        "ohlcv", help="fetch/refresh OHLCV history per instrument via Yahoo Finance (stage 3)"
    )
    ohlcv.add_argument("--identity-map", type=Path, default=IDENTITY_MAP_CSV)
    ohlcv.add_argument("--output-dir", type=Path, default=OHLCV_DIR)
    ohlcv.add_argument(
        "--range", default="5y", help="history window for a first-time fetch (e.g. 1y, 5y, max)"
    )
    ohlcv.add_argument("--interval", default="1d", help="bar interval (1d, 1wk, 1mo)")
    ohlcv.add_argument(
        "--symbols", nargs="*", help="limit to these XTB symbols (default: every mapped instrument)"
    )
    ohlcv.set_defaults(handler=cmd_ohlcv)

    return parser


# -- commands --------------------------------------------------------------
def cmd_fetch(args: argparse.Namespace) -> int:
    if args.from_raw:
        records = read_raw(args.from_raw)
        source = f"raw dump {args.from_raw}"
        log.info("Loaded %d records from %s", len(records), args.from_raw)
    else:
        records = _fetch_live()
        source = f"xAPI getAllSymbols ({load_credentials().mode})"
        write_raw(records, args.raw)
        log.info("Raw payload saved to %s", args.raw)

    config = (
        FilterConfig(reject_cfd_suffix=False, min_leverage=None, require_long_only=False)
        if args.keep_cfd
        else FilterConfig()
    )
    result = filter_instruments(records, config)

    write_snapshot(result.instruments, args.output)
    write_metadata(
        args.metadata,
        source=source,
        total=result.total,
        kept=result.kept,
        rejections=result.rejections,
    )

    print(result.summary())
    print()
    print(_breakdown(result.instruments))
    print(f"\nSnapshot: {args.output}\nMetadata: {args.metadata}")
    return 0


def cmd_fetch_sec(args: argparse.Namespace) -> int:
    entries = fetch_company_tickers()
    records = [to_symbol_record(entry) for entry in entries]
    result = filter_instruments(records)

    write_snapshot(result.instruments, args.output)
    write_metadata(
        args.metadata,
        source="SEC EDGAR company_tickers.json (US-listed stocks, no XTB account)",
        total=result.total,
        kept=result.kept,
        rejections=result.rejections,
    )

    print(result.summary())
    print()
    print(_breakdown(result.instruments))
    print(f"\nSnapshot: {args.output}\nMetadata: {args.metadata}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    records = _fetch_live() if args.live else read_raw(args.from_raw)
    stats = describe_universe(records)

    print(f"{len(records)} raw records\n")
    for field, counter in stats.items():
        print(f"== {field}")
        for value, count in counter.most_common(args.top):
            print(f"  {count:>7}  {value}")
        if len(counter) > args.top:
            print(f"  ... {len(counter) - args.top} more values")
        print()

    result = filter_instruments(records)
    print("== filter outcome")
    print(result.summary())
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    instruments = read_snapshot(args.snapshot)
    if args.asset_class:
        instruments = [i for i in instruments if i.asset_class == args.asset_class]
    if args.market:
        market = args.market.upper()
        instruments = [i for i in instruments if i.market == market]

    print(_breakdown(instruments))
    print()
    rows = instruments if args.limit == 0 else instruments[: args.limit]
    for instrument in rows:
        head = f"{instrument.symbol:<16} {instrument.asset_class:<6} {instrument.currency:<4}"
        print(f"{head} {instrument.description}")
    if args.limit and len(instruments) > args.limit:
        print(f"... {len(instruments) - args.limit} more (use --limit 0)")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    instruments = read_snapshot(args.snapshot)

    figi_by_symbol: dict[str, str] = {}
    if args.figi:
        jobs, unmapped = build_jobs(instruments)
        if unmapped:
            log.warning(
                "%d symbols have no OpenFIGI exchange-code mapping, skipping FIGI lookup: %s",
                len(unmapped),
                ", ".join(unmapped[:5]) + ("..." if len(unmapped) > 5 else ""),
            )
        load_env()
        api_key = args.openfigi_api_key or os.getenv("OPENFIGI_API_KEY")
        client = OpenFigiClient(api_key=api_key)
        figi_by_symbol = client.lookup_figis(jobs)
        log.info("resolved %d/%d FIGIs via OpenFIGI", len(figi_by_symbol), len(jobs))

    mappings = map_instruments(instruments, figi_by_symbol)
    write_identity_map(mappings, args.output)

    with_yahoo = sum(1 for m in mappings if m.yahoo_symbol)
    with_figi = sum(1 for m in mappings if m.figi)
    print(f"{len(mappings)} instruments mapped")
    print(f"  yahoo ticker: {with_yahoo}")
    print(f"  figi:         {with_figi}")
    print(f"\nIdentity map: {args.output}")
    return 0


def cmd_ohlcv(args: argparse.Namespace) -> int:
    mappings = read_identity_map(args.identity_map)
    if args.symbols:
        wanted = set(args.symbols)
        mappings = [m for m in mappings if m.symbol in wanted]

    mapped = [m for m in mappings if m.yahoo_symbol]
    skipped = len(mappings) - len(mapped)
    if skipped:
        log.warning("%d instruments have no yahoo_symbol, skipping", skipped)

    client = YahooChartClient()
    refreshed = 0
    failed: list[str] = []

    for mapping in mapped:
        path = args.output_dir / f"{safe_filename(mapping.yahoo_symbol)}.csv"
        existing = read_ohlcv(path)
        try:
            if existing:
                period1 = int(
                    datetime.fromisoformat(existing[-1].date)
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                new_bars = client.get_bars(
                    mapping.yahoo_symbol,
                    period1=period1,
                    period2=int(time.time()),
                    interval=args.interval,
                )
            else:
                new_bars = client.get_bars(
                    mapping.yahoo_symbol, range_=args.range, interval=args.interval
                )
        except YahooFinanceError as exc:
            log.warning("%s (%s): %s", mapping.symbol, mapping.yahoo_symbol, exc)
            failed.append(mapping.symbol)
            continue

        write_ohlcv(merge_bars(existing, new_bars), path)
        refreshed += 1

    print(
        f"{refreshed}/{len(mapped)} instruments refreshed, {len(failed)} failed, {skipped} skipped"
    )
    if failed:
        print("failed: " + ", ".join(failed))
    print(f"\nBars stored under: {args.output_dir}")
    return 0


# -- helpers ---------------------------------------------------------------
def _fetch_live() -> list[dict[str, Any]]:
    credentials = load_credentials()
    with XtbClient(credentials) as client:
        return client.get_all_symbols()


def _breakdown(instruments: list[Any]) -> str:
    by_class = Counter(i.asset_class for i in instruments)
    by_market = Counter(i.market or "?" for i in instruments)
    lines = [f"total: {len(instruments)}"]
    lines.append("by asset class: " + ", ".join(f"{k}={v}" for k, v in sorted(by_class.items())))
    lines.append("by market:      " + ", ".join(f"{k}={v}" for k, v in by_market.most_common()))
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
