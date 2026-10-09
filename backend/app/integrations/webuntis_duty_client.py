"""Lesender Zugriff auf den internen, nicht offiziell dokumentierten WebUntis-Dienst
`jsonrpc_web/jsonStudentDutyService` (Klassendienste), siehe
docs/superpowers/plans/2026-10-08-klassendienste-anzeige.md.

Der Dienst akzeptiert die Cookie-Session des WebUntisClient, verlangt aber zusaetzlich einen
CSRF-Header. Token und Header-Name stehen als Skriptvariablen `csrfToken`/`csrfHeader` in
`GET /WebUntis/index.do`. Token, Cookies und CSRF-Werte werden nie geloggt und nie in
Ausnahme-Texte uebernommen.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.integrations.webuntis_client import WebUntisClient

DUTY_PATH = "/WebUntis/jsonrpc_web/jsonStudentDutyService"
INDEX_PATH = "/WebUntis/index.do"
DEFAULT_CSRF_HEADER = "X-CSRF-TOKEN"

_TOKEN_RE = re.compile(r"""\bcsrfToken\b["']?\s*[:=]\s*["']([^"'\s]+)["']""")
_HEADER_RE = re.compile(r"""\bcsrfHeader\b["']?\s*[:=]\s*["']([^"'\s]+)["']""")
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class DutyServiceError(RuntimeError):
    """Klassifizierter Fehler des Duty-Dienstes. `kind`: csrf_missing, forbidden, login_required,
    rpc_error, http_error, invalid_response, network. Die Nachricht enthaelt nie Token/Cookies."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind


@dataclass(frozen=True)
class DutyOption:
    id: int
    bezeichnung: str


def extract_csrf(html: str) -> tuple[str, str]:
    """(Header-Name, Token) aus der index.do-HTML-Seite. Fehlt der Header-Name, gilt der bisher
    beobachtete Default X-CSRF-TOKEN. Fehlt das Token, DutyServiceError('csrf_missing')."""
    token_match = _TOKEN_RE.search(html)
    if token_match is None:
        raise DutyServiceError("csrf_missing", "Kein CSRF-Token in der WebUntis-Seite gefunden")
    header_match = _HEADER_RE.search(html)
    header = header_match.group(1) if header_match else DEFAULT_CSRF_HEADER
    if not _HEADER_NAME_RE.match(header):
        header = DEFAULT_CSRF_HEADER
    return header, token_match.group(1)


_OPTION_LABEL_KEYS = ("label", "name", "longName", "text", "displayName", "title")
_OPTION_ID_KEYS = ("id", "dutyId", "value")


def _option_from_dict(entry: dict[str, Any]) -> DutyOption | None:
    raw_id = next((entry[k] for k in _OPTION_ID_KEYS if k in entry), None)
    label = next((entry[k] for k in _OPTION_LABEL_KEYS if isinstance(entry.get(k), str) and entry[k].strip()), None)
    if isinstance(raw_id, bool) or label is None:
        return None
    try:
        return DutyOption(id=int(raw_id), bezeichnung=label.strip())
    except (TypeError, ValueError):
        return None


def _options_from_list(items: list[Any]) -> list[DutyOption]:
    options = [o for o in (_option_from_dict(e) for e in items if isinstance(e, dict)) if o is not None]
    return options


def parse_duty_options(result: Any) -> list[DutyOption]:
    """Toleranter Parser fuer `getStudentDutyOptions` (Antwortform nicht bestaetigt): Liste von
    {id, label}, Objekt mit einer solchen Liste (z. B. `dutyOptions`) oder Objekt {"26": "Name"}.
    Unbekannte Form -> leere Liste."""
    options: list[DutyOption] = []
    if isinstance(result, list):
        options = _options_from_list(result)
    elif isinstance(result, dict):
        preferred = result.get("dutyOptions")
        candidates = [preferred] if isinstance(preferred, list) else [v for v in result.values() if isinstance(v, list)]
        for candidate in candidates:
            options = _options_from_list(candidate)
            if options:
                break
        if not options:
            for key, value in result.items():
                if isinstance(value, str) and value.strip() and str(key).strip().isdigit():
                    options.append(DutyOption(id=int(key), bezeichnung=value.strip()))
    seen: dict[int, DutyOption] = {}
    for option in options:
        seen.setdefault(option.id, option)
    return sorted(seen.values(), key=lambda o: o.id)


class StudentDutyClient:
    """Duty-Aufrufe ueber die Session eines bereits angemeldeten WebUntisClient. Das CSRF-Token wird
    lazy einmal pro Instanz geholt und bei HTTP 403 genau einmal neu geholt (pro Aufruf)."""

    def __init__(self, client: WebUntisClient, settings: Settings) -> None:
        self._client = client
        self._http: httpx.AsyncClient = client.http
        self._server = settings.webuntis_server
        self._school = settings.webuntis_school
        self._csrf: tuple[str, str] | None = None

    @property
    def _base(self) -> str:
        return f"https://{self._server}"

    def _cookie_header(self) -> str:
        cookies: dict[str, str] = {}
        for cookie in self._http.cookies.jar:
            if cookie.value is not None:
                cookies[cookie.name] = cookie.value
        session_id = self._client.session_id
        if session_id and "JSESSIONID" not in cookies:
            cookies["JSESSIONID"] = session_id
        if "schoolname" not in cookies and self._school:
            cookies["schoolname"] = '"_' + base64.b64encode(self._school.encode()).decode() + '"'
        return "; ".join(f"{name}={value}" for name, value in cookies.items())

    async def _fetch_csrf(self) -> tuple[str, str]:
        try:
            response = await self._http.get(
                self._base + INDEX_PATH, headers={"Cookie": self._cookie_header()}, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            raise DutyServiceError("network", f"index.do nicht erreichbar ({type(exc).__name__})") from None
        if response.status_code != 200:
            kind = "login_required" if 300 <= response.status_code < 400 else "http_error"
            raise DutyServiceError(kind, f"index.do lieferte HTTP {response.status_code}")
        self._csrf = extract_csrf(response.text)
        return self._csrf

    async def _post(self, method: str, params: list[Any], csrf: tuple[str, str]) -> httpx.Response:
        header, token = csrf
        headers = {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self._base,
            "Referer": f"{self._base}/WebUntis/embedded.do?showSidebar=true",
            "Cookie": self._cookie_header(),
            header: token,
        }
        payload = {"id": 2, "method": method, "params": params, "jsonrpc": "2.0"}
        try:
            return await self._http.post(
                self._base + DUTY_PATH, json=payload, headers=headers, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            raise DutyServiceError("network", f"{method} nicht erreichbar ({type(exc).__name__})") from None

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        csrf = self._csrf or await self._fetch_csrf()
        response = await self._post(method, params, csrf)
        if response.status_code == 403:
            csrf = await self._fetch_csrf()  # genau ein Neuholen, dann genau ein Wiederholen
            response = await self._post(method, params, csrf)
            if response.status_code == 403:
                raise DutyServiceError("forbidden", f"{method} auch mit neuem CSRF-Token mit HTTP 403 abgelehnt")
        if 300 <= response.status_code < 400:
            raise DutyServiceError("login_required", f"{method}: Weiterleitung (Session nicht akzeptiert)")
        if response.status_code in (401, 403):
            raise DutyServiceError("forbidden", f"{method}: HTTP {response.status_code}")
        if response.status_code != 200:
            raise DutyServiceError("http_error", f"{method}: HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise DutyServiceError("login_required", f"{method}: Antwort ist kein JSON (vermutlich Login-Seite)") from None
        if not isinstance(body, dict):
            raise DutyServiceError("invalid_response", f"{method}: unerwartete Antwortform")
        error = body.get("error")
        if error is not None:
            code = error.get("code") if isinstance(error, dict) else None
            raise DutyServiceError("rpc_error", f"{method}: JSON-RPC-Fehler (Code {code})")
        if "result" not in body:
            raise DutyServiceError("invalid_response", f"{method}: Antwort ohne result")
        return body["result"]

    async def get_scheduler_data(self, webuntis_klassen_id: int, dienst_id: int) -> dict[str, Any]:
        result = await self._rpc("getStudentDutySchedulerData", [webuntis_klassen_id, dienst_id])
        if not isinstance(result, dict) or not isinstance(result.get("matrix"), dict):
            raise DutyServiceError("invalid_response", "getStudentDutySchedulerData: result.matrix fehlt")
        return result

    async def get_duty_options(self) -> list[DutyOption]:
        return parse_duty_options(await self._rpc("getStudentDutyOptions", []))

    async def get_students(self) -> list[dict[str, Any]]:
        """getStudents (jsonrpc.do, ohne Parameter). Enthaelt Namen; der Aufrufer darf sie weder
        speichern noch loggen."""
        result = await self._client.call("getStudents", {})
        if not isinstance(result, list):
            raise DutyServiceError("invalid_response", "getStudents: Liste erwartet")
        return result
