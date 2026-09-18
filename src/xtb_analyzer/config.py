"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"

#: Committed snapshot used as an offline fallback when no credentials are available.
SNAPSHOT_CSV = DATA_DIR / "instruments.csv"
SNAPSHOT_META = DATA_DIR / "instruments.meta.json"

#: Stage 2 identity map — symbol -> external tickers/FIGI.
IDENTITY_MAP_CSV = DATA_DIR / "identity_map.csv"

#: Stage 3 — one CSV of OHLCV bars per instrument, keyed by Yahoo ticker.
OHLCV_DIR = DATA_DIR / "ohlcv"

#: Alternative, login-free universe (SEC EDGAR, US-listed stocks only) — see
#: xtb_analyzer.sec_edgar. Kept separate from the XTB-specific files above so
#: the two universes are never conflated.
US_STOCKS_CSV = DATA_DIR / "us_stocks.csv"
US_STOCKS_META = DATA_DIR / "us_stocks.meta.json"
US_STOCKS_CIK_CSV = DATA_DIR / "us_stocks_cik.csv"

#: Stage 4 — raw fundamentals per company, via SEC EDGAR XBRL (us_stocks only).
US_STOCKS_FUNDAMENTALS_CSV = DATA_DIR / "us_stocks_fundamentals.csv"

#: Alternative, login-free universe: PLN-denominated stocks + ETFs quoted on
#: GPW's Main Market — see xtb_analyzer.gpw. Kept separate from the other
#: universes above so none of them get conflated.
GPW_INSTRUMENTS_CSV = DATA_DIR / "gpw_instruments.csv"
GPW_INSTRUMENTS_META = DATA_DIR / "gpw_instruments.meta.json"
GPW_ISIN_CSV = DATA_DIR / "gpw_isin.csv"
GPW_OHLCV_DIR = DATA_DIR / "gpw_ohlcv"
GPW_IDENTITY_MAP_CSV = DATA_DIR / "gpw_identity_map.csv"
GPW_TECHNICALS_CSV = DATA_DIR / "gpw_technicals.csv"

#: Stage 6 — buy/hold/sell verdicts, one CSV per universe (same naming
#: convention as the other per-universe outputs above).
GPW_SCORES_CSV = DATA_DIR / "gpw_scores.csv"
US_STOCKS_SCORES_CSV = DATA_DIR / "us_stocks_scores.csv"
SCORES_CSV = DATA_DIR / "scores.csv"

WS_URLS = {
    "demo": "wss://ws.xtb.com/demo",
    "real": "wss://ws.xtb.com/real",
}


class ConfigError(RuntimeError):
    """Raised when required credentials are missing."""


@dataclass(frozen=True)
class Credentials:
    user_id: str
    password: str
    mode: str = "demo"

    @property
    def ws_url(self) -> str:
        try:
            return WS_URLS[self.mode]
        except KeyError as exc:  # pragma: no cover - guarded by load()
            raise ConfigError(
                f"Unknown XTB_MODE={self.mode!r}, expected one of {sorted(WS_URLS)}"
            ) from exc


def load_env(env_file: Path | None = None) -> None:
    """Seed ``os.environ`` from ``.env`` without requiring XTB credentials to be set."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)


def load_credentials(env_file: Path | None = None) -> Credentials:
    """Read XTB credentials from the environment (optionally seeded from a .env file)."""
    load_env(env_file)

    user_id = os.getenv("XTB_USER_ID", "").strip()
    password = os.getenv("XTB_PASSWORD", "").strip()
    mode = os.getenv("XTB_MODE", "demo").strip().lower()

    missing = [
        name for name, value in (("XTB_USER_ID", user_id), ("XTB_PASSWORD", password)) if not value
    ]
    if missing:
        raise ConfigError(
            f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in "
            "(a demo account is enough to download the instrument list)."
        )
    if mode not in WS_URLS:
        raise ConfigError(f"Unknown XTB_MODE={mode!r}, expected one of {sorted(WS_URLS)}")

    return Credentials(user_id=user_id, password=password, mode=mode)
