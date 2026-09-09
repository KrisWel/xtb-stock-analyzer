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

#: Stage 2 identity map — symbol -> external tickers/ISIN.
IDENTITY_MAP_CSV = DATA_DIR / "identity_map.csv"

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
