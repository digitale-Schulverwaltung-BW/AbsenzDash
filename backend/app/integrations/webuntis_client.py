from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from app.core.config import Settings

_SESSION_EXPIRED_ERROR_CODE = -8520


class WebUntisError(RuntimeError):
    """Raised when a WebUntis JSON-RPC call returns an error (other than session expiry)."""


class WebUntisClient:
    """Async JSON-RPC-Client für WebUntis (TECH-SPEC.md Abschnitt 1.1).

    Nutzung: `async with WebUntisClient(settings) as client: await client.call("getKlassen", {})`.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=15.0)
        self._session_id: str | None = None

    @property
    def _rpc_url(self) -> str:
        return f"https://{self._settings.webuntis_server}/WebUntis/jsonrpc.do"

    async def __aenter__(self) -> WebUntisClient:
        try:
            await self._authenticate()
        except:
            await self._http.aclose()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._session_id is not None:
                await self._raw_call("logout", {})
        finally:
            await self._http.aclose()

    async def _authenticate(self) -> None:
        payload = {
            "id": "auth",
            "method": "authenticate",
            "params": {
                "user": self._settings.webuntis_username,
                "password": self._settings.webuntis_password,
                "client": "AbsenzDash",
            },
            "jsonrpc": "2.0",
        }
        response = await self._http.post(
            self._rpc_url, params={"school": self._settings.webuntis_school}, json=payload
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise WebUntisError(f"WebUntis-Login fehlgeschlagen: {body['error']}")
        self._session_id = body["result"]["sessionId"]

    async def _raw_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {"Cookie": f"JSESSIONID={self._session_id}"} if self._session_id else {}
        payload = {"id": method, "method": method, "params": params, "jsonrpc": "2.0"}
        response = await self._http.post(
            self._rpc_url, params={"school": self._settings.webuntis_school}, json=payload, headers=headers
        )
        response.raise_for_status()
        return response.json()

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        body = await self._raw_call(method, params)
        if "error" in body:
            error = body["error"]
            if error.get("code") == _SESSION_EXPIRED_ERROR_CODE:
                await self._authenticate()
                body = await self._raw_call(method, params)
                if "error" in body:
                    raise WebUntisError(f"WebUntis-Aufruf '{method}' fehlgeschlagen: {body['error']}")
            else:
                raise WebUntisError(f"WebUntis-Aufruf '{method}' fehlgeschlagen: {error}")
        return body.get("result")
