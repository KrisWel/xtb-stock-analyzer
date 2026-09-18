"""Minimal synchronous client for the XTB xStation5 API (xAPI).

Protocol notes (see docs/xtb-api-notes.md):
  * transport is a plain WebSocket, one JSON object per frame;
  * every request is ``{"command": ..., "arguments": {...}}``;
  * every response is ``{"status": true, "returnData": ...}`` or
    ``{"status": false, "errorCode": ..., "errorDescr": ...}``;
  * the server rate-limits to one command per 200 ms — we keep 250 ms.
"""

from __future__ import annotations

import json
import logging
import time
from types import TracebackType
from typing import Any

import websocket

from .config import Credentials

log = logging.getLogger(__name__)

#: Server-side limit is 1 request / 200 ms; a small margin avoids EX009 throttling errors.
MIN_REQUEST_INTERVAL_S = 0.25


class XtbApiError(RuntimeError):
    """The API answered with ``status: false``."""

    def __init__(self, command: str, code: str | None, description: str | None) -> None:
        super().__init__(f"{command} failed: [{code}] {description}")
        self.command = command
        self.code = code
        self.description = description


class XtbClient:
    """Thin request/response wrapper around the xAPI socket."""

    def __init__(
        self, credentials: Credentials, timeout: float = 60.0, app_name: str = "xtb-stock-analyzer"
    ) -> None:
        self._credentials = credentials
        self._timeout = timeout
        self._app_name = app_name
        self._ws: websocket.WebSocket | None = None
        self._last_request_at = 0.0
        self.stream_session_id: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> XtbClient:
        log.info("Connecting to %s", self._credentials.ws_url)
        self._ws = websocket.create_connection(self._credentials.ws_url, timeout=self._timeout)
        return self

    def login(self) -> None:
        data = self._request(
            "login",
            {
                "userId": self._credentials.user_id,
                "password": self._credentials.password,
                "appName": self._app_name,
            },
            redact=True,
        )
        self.stream_session_id = data if isinstance(data, str) else None
        log.info("Logged in to the %s server", self._credentials.mode)

    def logout(self) -> None:
        if self._ws is None:
            return
        try:
            self._request("logout")
        except (XtbApiError, OSError, websocket.WebSocketException) as exc:  # best effort
            log.debug("logout failed, closing anyway: %s", exc)

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def __enter__(self) -> XtbClient:
        self.connect()
        self.login()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.logout()
        self.close()

    # -- commands ----------------------------------------------------------
    def get_all_symbols(self) -> list[dict[str, Any]]:
        """Return every symbol record the account can see (stocks, ETFs, CFDs, FX, ...)."""
        data = self._request("getAllSymbols")
        if not isinstance(data, list):
            raise XtbApiError(
                "getAllSymbols", "MALFORMED", f"expected a list, got {type(data).__name__}"
            )
        log.info("getAllSymbols returned %d records", len(data))
        return data

    def get_server_time(self) -> dict[str, Any]:
        data = self._request("getServerTime")
        return data if isinstance(data, dict) else {}

    def get_trades(self, opened_only: bool = True) -> list[dict[str, Any]]:
        """Return the account's open positions (stage 7, portfolio view).

        Not verified live — no session so far has had XTB credentials (see
        docs/xtb-api-notes.md); the shape (``symbol``, ``cmd``, ``volume``,
        ``open_price``, ...) is taken from xAPI's published documentation
        for ``getTrades``. Confirm field names against a real response
        before trusting them blindly, same discipline as everywhere else.
        """
        data = self._request("getTrades", {"openedOnly": opened_only})
        if not isinstance(data, list):
            raise XtbApiError(
                "getTrades", "MALFORMED", f"expected a list, got {type(data).__name__}"
            )
        log.info("getTrades returned %d records", len(data))
        return data

    # -- plumbing ----------------------------------------------------------
    def _request(
        self, command: str, arguments: dict[str, Any] | None = None, *, redact: bool = False
    ) -> Any:
        if self._ws is None:
            raise RuntimeError("Not connected — call connect() first (or use the context manager).")

        self._throttle()
        payload: dict[str, Any] = {"command": command}
        if arguments:
            payload["arguments"] = arguments

        log.debug("-> %s%s", command, "" if redact else f" {arguments or ''}")
        self._ws.send(json.dumps(payload))
        raw = self._ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        response = json.loads(raw)

        if not response.get("status"):
            raise XtbApiError(command, response.get("errorCode"), response.get("errorDescr"))
        return response.get("returnData")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()
