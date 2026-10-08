"""Rein LESENDE Sonde: liefert WebUntis an der Schul-Instanz "Klassendienste" (Klassensprecher,
Entschuldigungspflicht, Attestpflicht) und brauchbare Ferien/Feiertage (getHolidays)?

Es werden ausschliesslich JSON-RPC-Methoden `get*` und HTTP-GET-Requests abgesetzt. Kein
DB-Zugriff, keine Schreibzugriffe (ausser der optionalen Datei-Ausgabe via --json). Die REST-Pfade
unter /WebUntis/api/ sind GERATEN bzw. inoffiziell. Personenbezogene Werte werden in der Ausgabe
maskiert (siehe `maskiere`), damit sie in einen Chat eingefuegt werden kann.

Nutzung (im laufenden Backend-Container):
    python -m scripts.probe_webuntis_klassendienste [--json DATEI]
    python -m scripts.probe_webuntis_klassendienste --rpc-method getXyz [--rpc-params '{"a": 1}'] [--rpc-path PFAD]
    python -m scripts.probe_webuntis_klassendienste --klasse-id 3821 --duty-id 26 --duty-id 27
    python -m scripts.probe_webuntis_klassendienste --klasse-id 3836 --duty-id 26 --abgleich-klasse-id 3836 --mit-db

Mit --rpc-method wird gezielt nur dieser eine Aufruf gegen den internen Dienst (Default
jsonrpc_web/jsonStudentDutyService) abgesetzt. Erlaubt sind nur Methoden, die mit get, list oder
find beginnen (zusaetzlich system.listMethods); Pfade muessen unter /WebUntis/ liegen.

Der Standardlauf prueft zusaetzlich: token/new (nur Form/Claim-NAMEN), Cookie-NAMEN, die Suche nach
einer CSRF-Token-Quelle (nur Fundort-Art, Laenge, Form) und eine Matrix von Header-Kombinationen fuer
`getStudentDutySchedulerData [klasseId, dutyId]`. Token-, Cookie- und CSRF-WERTE werden nie ausgegeben.

ID-Abgleich: `getStudents` (Formprofil je Key, UUID-Kandidat fuer Schueler.externe_id), Abgleich der
numerischen Matrix-Schueler-IDs mit `getStudents` (Zahlen, keine Namen), Suche nach `dutyOptions`
(Parameter-Varianten GERATEN) und mit `--mit-db` ein ausschliesslich lesender Abgleich gegen
`SELECT externe_id, vorname, nachname, klasse_id FROM schueler` (nur Zahlen in der Ausgabe).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html as html_lib
import json
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient

TIMEOUT = 15.0
KEYWORDS = ("dienst", "sprecher", "attest", "entschuldigung", "role", "service")
MAX_BEISPIELE = 3
MAX_BODY = 300

_NAME_EXAKT = {
    "name", "longname", "firstname", "lastname", "forename", "surname", "fullname",
    "displayname", "email", "mail", "phone", "mobile", "tel", "telephone",
}  # fmt: skip
_NAME_PRAEFIXE = ("teacher", "student")


def _norm(key: str) -> str:
    return re.sub(r"[_\-\s]", "", key).lower()


def _ist_namensfeld(key: str) -> bool:
    n = _norm(key)
    return n in _NAME_EXAKT or n.startswith(_NAME_PRAEFIXE) or "mail" in n or "phone" in n


def maskiere(obj: Any, ausnahmen: frozenset[str] | set[str] = frozenset(), _maskieren: bool = False) -> Any:
    """Kopie von `obj`, in der Strings in namensartigen Feldern (name, longName, firstName,
    lastName, teacher*, student*, email, phone u. ae.) auf die ersten 2 Zeichen + '…' gekuerzt sind.
    IDs, Zahlen, Datums-/Kuerzel-/Rollenfelder und Keys bleiben unveraendert. `ausnahmen`: Keys
    (normalisiert, case-insensitiv), die nie maskiert werden, z. B. {"name"} fuer Klassenkuerzel."""
    ausnahmen_norm = {_norm(a) for a in ausnahmen}
    if isinstance(obj, dict):
        return {
            k: maskiere(v, ausnahmen, _ist_namensfeld(str(k)) and _norm(str(k)) not in ausnahmen_norm)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [maskiere(v, ausnahmen, _maskieren) for v in obj]
    if isinstance(obj, str) and _maskieren and obj:
        return obj[:2] + "…"
    return obj


def suche_stichworte(obj: Any, pfad: str) -> list[tuple[str, str]]:
    """Case-insensitive Suche nach KEYWORDS in Keys und String-Werten. Liefert (Fundort, Stichwort);
    der gefundene Wert selbst wird nicht ausgegeben."""
    treffer: list[tuple[str, str]] = []

    def pruefe(text: str, fundort: str) -> None:
        low = text.lower()
        for wort in KEYWORDS:
            if wort in low:
                treffer.append((fundort, wort))

    def walk(o: Any, p: str) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                pruefe(str(k), f"{p}.{k}")
                walk(v, f"{p}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{p}[{i}]")
        elif isinstance(o, str):
            pruefe(o, p)

    walk(obj, pfad)
    return treffer


def kuerze(obj: Any, max_beispiele: int = MAX_BEISPIELE) -> Any:
    """Listen mit mehr als `max_beispiele` Eintraegen werden zu {"_laenge": n, "_beispiele": [...]}."""
    if isinstance(obj, dict):
        return {k: kuerze(v, max_beispiele) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > max_beispiele:
            return {"_laenge": len(obj), "_beispiele": [kuerze(v, max_beispiele) for v in obj[:max_beispiele]]}
        return [kuerze(v, max_beispiele) for v in obj]
    return obj


@dataclass
class Sonde:
    name: str
    ok: bool
    zeilen: list[str] = field(default_factory=list)
    treffer: list[tuple[str, str]] = field(default_factory=list)
    roh: Any = None  # maskierte, gekuerzte Antwort fuer --json
    kategorie: str | None = None  # nur bei jsonrpc_web-Sonden: Ergebnis von klassifiziere_antwort
    tag: str | None = None  # z. B. "token", "csrf", "duty:a" - fuer den Befund
    extra: dict[str, Any] = field(default_factory=dict)  # interne Metadaten, nie in der Ausgabe


def _fmt(obj: Any, ausnahmen: set[str] | None = None) -> str:
    return json.dumps(kuerze(maskiere(obj, ausnahmen or set())), ensure_ascii=False, default=str)


def _fehler(name: str, exc: Exception) -> Sonde:
    return Sonde(name, False, [f"Fehler: {type(exc).__name__}: {str(exc)[:200]}"])


def _beschreibe(daten: Any) -> str:
    if isinstance(daten, list):
        return f"Liste mit {len(daten)} Eintraegen"
    if isinstance(daten, dict):
        return f"Objekt, Keys: {sorted(daten.keys())}"
    return f"{type(daten).__name__}: {str(daten)[:60]}"


def _ist_leer(daten: Any) -> bool:
    return daten is None or daten == [] or daten == {}


async def hole_schuljahr(client: Any) -> dict[str, Any] | None:
    try:
        sj = await client.call("getCurrentSchoolyear", {})
        return sj if isinstance(sj, dict) else None
    except Exception:  # noqa: BLE001 - Schuljahr ist nur Zusatzinfo
        return None


async def sonde_holidays(client: Any, schuljahr: dict[str, Any] | None) -> Sonde:
    name = "getHolidays"
    try:
        daten = await client.call("getHolidays", {})
    except Exception as exc:  # noqa: BLE001
        return _fehler(name, exc)
    if not isinstance(daten, list) or not daten:
        return Sonde(name, False, [f"leer oder unerwartetes Format: {_beschreibe(daten)}"])
    keys = sorted({k for e in daten if isinstance(e, dict) for k in e})
    starts = [e["startDate"] for e in daten if isinstance(e, dict) and "startDate" in e]
    ends = [e["endDate"] for e in daten if isinstance(e, dict) and "endDate" in e]
    zeilen = [f"Anzahl Eintraege: {len(daten)}", f"Keys: {keys}"]
    zeilen.append("Erste 3: " + _fmt(daten[:3], {"name", "longName"}))
    zeilen.append("Letzte 3: " + _fmt(daten[-3:], {"name", "longName"}))
    if starts and ends:
        zeilen.append(f"Abdeckung: frueheste startDate {min(starts)}, spaeteste endDate {max(ends)}")
        if schuljahr and "startDate" in schuljahr and "endDate" in schuljahr:
            sj_s, sj_e = schuljahr["startDate"], schuljahr["endDate"]
            im_jahr = [s for s, e in zip(starts, ends) if s <= sj_e and e >= sj_s]
            zeilen.append(
                f"Aktuelles Schuljahr {sj_s}-{sj_e} abgedeckt: {'ja' if im_jahr else 'nein'} "
                f"({len(im_jahr)} Eintraege im Schuljahr)"
            )
        else:
            zeilen.append("Aktuelles Schuljahr unbekannt (getCurrentSchoolyear lieferte nichts): abgedeckt: unbekannt")
    return Sonde(name, True, zeilen, roh=kuerze(maskiere(daten, {"name", "longName"})))


async def sonde_klassen(client: Any, schuljahr: dict[str, Any] | None) -> Sonde:
    name = "getKlassen"
    params = {"schoolyearId": schuljahr["id"]} if schuljahr and "id" in schuljahr else {}
    try:
        daten = await client.call("getKlassen", params)
    except Exception as exc:  # noqa: BLE001
        return _fehler(name, exc)
    if not isinstance(daten, list) or not daten:
        return Sonde(name, False, [f"leer oder unerwartetes Format: {_beschreibe(daten)}"])
    keys = sorted({k for e in daten if isinstance(e, dict) for k in e})
    ausnahmen = {"name", "longName"}  # Klassenkuerzel/-bezeichnung, nicht personenbezogen
    treffer = suche_stichworte({k: None for k in keys}, name)
    treffer += [t for t in suche_stichworte(daten[:50], name) if t not in treffer]
    zeilen = [
        f"Anzahl Klassen: {len(daten)}",
        f"Keys: {keys}",
        "Beispiel: " + _fmt(daten[0], ausnahmen),
        "Key mit Dienst/Rolle/Sprecher-Bezug: " + (", ".join(sorted({f for f, _ in treffer})) if treffer else "keiner"),
    ]
    erste_id = daten[0].get("id") if isinstance(daten[0], dict) else None
    return Sonde(name, True, zeilen, treffer, kuerze(maskiere(daten[:3], ausnahmen)), extra={"erste_klasse_id": erste_id})


RPC_KANDIDATEN = ("getClassregCategories", "getClassregCategoryGroups", "getRemarkCategories", "getStatusData")


async def sonde_rpc_kandidaten(client: Any) -> list[Sonde]:
    sonden = []
    for methode in RPC_KANDIDATEN:
        try:
            daten = await client.call(methode, {})
        except Exception as exc:  # noqa: BLE001
            sonden.append(_fehler(methode, exc))
            continue
        if _ist_leer(daten):
            sonden.append(Sonde(methode, False, [f"leer: {_beschreibe(daten)}"]))
            continue
        ausnahmen = {"name", "longName"}  # Kategorie-/Gruppennamen, nicht personenbezogen
        treffer = suche_stichworte(daten, methode)
        zeilen = [_beschreibe(daten)]
        if isinstance(daten, list):
            keys = sorted({k for e in daten if isinstance(e, dict) for k in e})
            zeilen.append(f"Keys: {keys}")
            zeilen.append("Beispiele: " + _fmt(daten[:3], ausnahmen))
        elif isinstance(daten, dict):
            zeilen.append("Laengen: " + str({k: len(v) if isinstance(v, (list, dict)) else v for k, v in daten.items()}))
        zeilen.append(f"Stichwort-Treffer: {len(treffer)}")
        sonden.append(Sonde(methode, True, zeilen, treffer[:10], kuerze(maskiere(daten, ausnahmen))))
    return sonden


async def rest_sonde(
    http: httpx.AsyncClient, pfad: str, params: dict[str, str], auth_label: str, headers: dict[str, str] | None = None
) -> Sonde:
    """Ein einzelner REST-GET (GERATENER, inoffizieller Pfad unter /WebUntis/api/)."""
    query = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
    name = f"GET /WebUntis/api/{pfad}{query} [{auth_label}, geraten]"
    try:
        response = await http.get(f"/WebUntis/api/{pfad}", params=params or None, headers=headers or {})
    except Exception as exc:  # noqa: BLE001
        return _fehler(name, exc)
    ctype = response.headers.get("content-type", "?")
    zeilen = [f"Status {response.status_code}, Content-Type {ctype}, Laenge {len(response.content)}"]
    daten: Any = None
    try:
        daten = response.json()
    except Exception:  # noqa: BLE001
        daten = None
    ok = response.is_success and not _ist_leer(daten if daten is not None else response.text.strip() or None)
    treffer: list[tuple[str, str]] = []
    if response.is_success and daten is not None:
        if isinstance(daten, dict):
            zeilen.append(f"Top-Level-Keys: {sorted(daten.keys())}")
        elif isinstance(daten, list):
            zeilen.append(f"Liste mit {len(daten)} Eintraegen")
        zeilen.append("Beispiel: " + _fmt(daten, {"name", "longName"}))
        treffer = suche_stichworte(daten, pfad)[:10]
    elif not response.is_success:
        body = _fmt(daten) if daten is not None else response.text
        zeilen.append("Body: " + body[:MAX_BODY])
    else:
        zeilen.append("Body (kein JSON): " + response.text[:MAX_BODY])
    return Sonde(name, ok, zeilen, treffer, {"status": response.status_code})


def _cookie_headers(session_id: str | None, schule: str) -> dict[str, str]:
    schulname = "_" + base64.b64encode(schule.encode()).decode()
    return {"Cookie": f'JSESSIONID={session_id}; schoolname="{schulname}"'} if session_id else {}


def _datums_varianten(schuljahr: dict[str, Any] | None) -> list[dict[str, str]]:
    if not schuljahr or "startDate" not in schuljahr or "endDate" not in schuljahr:
        return []
    s, e = str(schuljahr["startDate"]), str(schuljahr["endDate"])
    return [
        {"startDate": s, "endDate": e},
        {"startDate": f"{s[:4]}-{s[4:6]}-{s[6:]}", "endDate": f"{e[:4]}-{e[4:6]}-{e[6:]}"},
    ]


async def sonde_rest(http: httpx.AsyncClient, kontext: Kontext, token: str | None, schuljahr: dict[str, Any] | None) -> list[Sonde]:
    """REST-GETs in drei Auth-Varianten: nur Cookies, nur Bearer (OHNE Cookie, wie die urspruengliche
    Sonde) und Bearer + Cookie. `token` stammt aus `diagnose_token` (None = nicht geholt)."""
    cookie_headers = kontext.header()
    varianten: list[tuple[str, dict[str, str]]] = [("Cookie", cookie_headers)]
    if token:
        varianten.append(("Bearer", {"Authorization": f"Bearer {token}"}))
        varianten.append(("Bearer+Cookie", {**cookie_headers, "Authorization": f"Bearer {token}"}))
    kandidaten: list[tuple[str, dict[str, str]]] = [
        ("classreg/classservices", {}),
        ("classreg/classroles", {}),
        *[("classreg/classservices", p) for p in _datums_varianten(schuljahr)],
        ("classreg/classregevents", {}),
        ("classreg/absences/students", {}),
    ]
    sonden: list[Sonde] = []
    for label, headers in varianten:
        for pfad, params in kandidaten:
            sonden.append(await rest_sonde(http, pfad, params, label, headers))
    # public/classreg/... nur, wenn Antworten darauf hindeuten (z. B. Links in Fehler-/Erfolgs-Bodies)
    # -> hier bewusst nicht geraten; Hinweise tauchen ggf. in den Body-Auszuegen oben auf.
    return sonden


# --- Cookies, token/new, CSRF-Quellensuche (nie Werte ausgeben) ---


def _norm_cookie(name: str) -> str:
    return name.lower().replace("-", "").replace("_", "")


@dataclass
class Kontext:
    """Cookies der Sonde (Namen -> Werte, nur intern) samt Herkunft: jar (aus dem Client-Jar),
    selbst (von der Sonde gesetzt), abgeleitet (aus Antwort/JWT)."""

    schule: str
    cookies: dict[str, str] = field(default_factory=dict, repr=False)
    herkunft: dict[str, str] = field(default_factory=dict)

    def setze(self, name: str, wert: str, herkunft: str = "jar") -> None:
        self.cookies[name] = wert
        self.herkunft[name] = herkunft

    def hat(self, name: str) -> bool:
        return any(_norm_cookie(n) == _norm_cookie(name) for n in self.cookies)

    def herkunft_von(self, name: str) -> str:
        for n, h in self.herkunft.items():
            if _norm_cookie(n) == _norm_cookie(name):
                return h
        return "fehlt"

    def setze_schoolname(self) -> None:
        if not self.hat("schoolname"):
            self.setze("schoolname", '"_' + base64.b64encode(self.schule.encode()).decode() + '"', "selbst")

    def uebernimm_set_cookie(self, response: httpx.Response) -> None:
        for roh in response.headers.get_list("set-cookie"):
            name, sep, rest = roh.partition("=")
            wert = rest.split(";", 1)[0].strip()
            if sep and name.strip() and wert:
                self.setze(name.strip(), wert, "jar" if name.strip() in self.cookies else "abgeleitet")

    def setze_tenant(self, tenant: str, herkunft: str = "abgeleitet") -> None:
        if not self.hat("Tenant-Id"):
            self.setze("Tenant-Id", tenant, herkunft)

    def header(self) -> dict[str, str]:
        return {"Cookie": "; ".join(f"{n}={v}" for n, v in self.cookies.items())} if self.cookies else {}

    @classmethod
    def aus_client(cls, client: Any, schule: str) -> Kontext:
        k = cls(schule)
        jar = getattr(getattr(client, "_http", None), "cookies", None)
        if isinstance(jar, httpx.Cookies):
            for c in jar.jar:
                if c.value is not None:
                    k.setze(c.name, c.value, "jar")
        session_id = getattr(client, "_session_id", None)
        if isinstance(session_id, str) and session_id:
            k.setze("JSESSIONID", session_id, k.herkunft.get("JSESSIONID", "client"))
        return k


def cookie_uebersicht(k: Kontext) -> Sonde:
    namen = sorted(k.cookies)
    zeilen = [
        f"Cookies im Client-Jar nach dem Login (nur Namen): {', '.join(namen) if namen else 'keine'}",
        f"Tenant-Id: {'ja' if k.hat('Tenant-Id') else 'nein'}",
        f"schoolname: {'ja' if k.hat('schoolname') else 'nein'}",
    ]
    return Sonde("Cookie-Namen nach Login", True, zeilen)


_HERKUNFT_TEXT = {"jar": "vorhanden", "client": "vorhanden", "selbst": "selbst gesetzt", "abgeleitet": "aus Antwort/JWT abgeleitet", "fehlt": "fehlt"}


def cookie_status_sonde(k: Kontext) -> Sonde:
    """Cookies, die fuer die Duty-Aufrufe tatsaechlich gesendet werden (nur Namen + Herkunft)."""
    status = {n: k.herkunft_von(n) for n in ("Tenant-Id", "schoolname")}
    zeilen = [f"Gesendete Cookies (nur Namen): {', '.join(sorted(k.cookies))}"]
    zeilen += [f"{n}: {_HERKUNFT_TEXT.get(h, h)}" for n, h in status.items()]
    if status["Tenant-Id"] == "fehlt":
        zeilen.append("Tenant-Id nicht ableitbar -> bei den Duty-Aufrufen weggelassen")
    return Sonde("Cookies fuer Duty-Aufrufe", status["Tenant-Id"] != "fehlt", zeilen, tag="cookies", extra=status)


@dataclass(frozen=True)
class JwtInfo:
    claim_namen: list[str]
    gueltig_min: float | None
    tenant_id: str | None
    token: str = field(repr=False, default="")


_B64URL = re.compile(r"[A-Za-z0-9_-]+")


def analysiere_jwt(text: str, jetzt: float | None = None) -> JwtInfo | None:
    """Erkennt ein JWT (drei Base64url-Teile, beginnt mit eyJ). Liefert NUR Claim-Namen, die
    verbleibende Gueltigkeit in Minuten und (intern) eine numerische Tenant-ID, nie Claim-Werte."""
    t = text.strip().strip('"')
    teile = t.split(".")
    if len(teile) != 3 or not t.startswith("eyJ") or not all(_B64URL.fullmatch(x) for x in teile):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(teile[1] + "=" * (-len(teile[1]) % 4)))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    gueltig = None
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        gueltig = (exp - (time.time() if jetzt is None else jetzt)) / 60
    tenant = next(
        (str(v) for k, v in payload.items() if _norm(str(k)) in ("tenantid", "tenant") and str(v).isdigit()), None
    )
    return JwtInfo(sorted(payload), gueltig, tenant, t)


def _ziel(location: str) -> str:
    u = urlsplit(location)
    return f"{u.netloc}{u.path}" if u.netloc else u.path


async def diagnose_token(http: httpx.AsyncClient, k: Kontext, jetzt: float | None = None) -> tuple[Sonde, str | None]:
    """GET /WebUntis/api/token/new mit Cookie-Auth (Redirects werden nicht gefolgt). Gibt (Sonde,
    verwendbares Token oder None) zurueck; das Token selbst wird nie ausgegeben."""
    name = "GET /WebUntis/api/token/new [Cookie]"
    try:
        r = await http.get("/WebUntis/api/token/new", headers=k.header(), follow_redirects=False)
    except Exception as exc:  # noqa: BLE001
        sonde = _fehler(name, exc)
        sonde.tag, sonde.extra = "token", {"jwt": False, "klasse": "netzwerkfehler"}
        return sonde, None
    k.uebernimm_set_cookie(r)
    ctype = r.headers.get("content-type", "?")
    text = r.text.strip() if 200 <= r.status_code < 300 else ""
    zeilen = [f"Status {r.status_code}, Content-Type {ctype}, Laenge {len(r.content)}"]
    info = analysiere_jwt(text, jetzt) if text else None
    token: str | None = None
    if 300 <= r.status_code < 400:
        klasse = "redirect"
        zeilen.append(f"Redirect (nicht gefolgt) -> {_ziel(r.headers.get('location', '?'))}")
    elif r.status_code in (401, 403):
        klasse = "http_auth"
    elif not r.is_success:
        klasse = "http_fehler"
    elif not text:
        klasse = "leer"
    elif info:
        klasse, token = "jwt", info.token
    elif "html" in ctype.lower() or "<html" in text[:500].lower():
        klasse = "login_html"
    else:
        klasse = "kein_jwt"
        if len(text) <= 4096 and not re.search(r"\s", text.strip('"')):
            token = text.strip('"')  # opakes Token: fuer Bearer-Tests trotzdem verwendbar
    zeilen.append(f"Klasse: {klasse}")
    zeilen.append(f"JWT-Form: {'ja' if info else 'nein'}")
    if info:
        zeilen.append(f"Claim-Namen: {', '.join(info.claim_namen)}")
        if info.gueltig_min is None:
            zeilen.append("Gueltigkeit: kein exp-Claim")
        elif info.gueltig_min >= 0:
            zeilen.append(f"Gueltigkeit: noch {info.gueltig_min:.0f} Minuten")
        else:
            zeilen.append(f"Gueltigkeit: abgelaufen seit {-info.gueltig_min:.0f} Minuten")
        if info.tenant_id:
            k.setze_tenant(info.tenant_id, "abgeleitet")
    sonde = Sonde(name, token is not None, zeilen, tag="token", extra={"jwt": info is not None, "klasse": klasse})
    return sonde, token


@dataclass(frozen=True)
class Fund:
    ort: str
    laenge: int
    form: str
    wert: str = field(repr=False, default="")


def beschreibe_form(wert: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]+", wert):
        return "hex"
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", wert):
        return "UUID"
    if re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", wert):
        return "url-safe base64"
    if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", wert):
        return "base64"
    if re.fullmatch(r"[A-Za-z0-9_\-+/=.]+", wert):
        return "base64-aehnlich (gemischt)"
    return "sonstige Zeichen"


_CSRF_WORT = re.compile(r"csrf|xsrf", re.IGNORECASE)
_TOKEN_ZEICHEN = re.compile(r"[A-Za-z0-9_\-+/=.]{16,}")
_SKRIPT_VAR = re.compile(r"""([\w$.\-]*(?:csrf|xsrf)[\w$\-]*)["']?\s*[:=]\s*["']([^"'\s]{8,})["']""", re.IGNORECASE)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")


def _fund(ort: str, wert: str) -> Fund:
    return Fund(ort, len(wert), beschreibe_form(wert), wert)


def _json_csrf(obj: Any, pfad: str, out: list[Fund]) -> None:
    if isinstance(obj, dict):
        for key, v in obj.items():
            p = f"{pfad}.{key}" if pfad else str(key)
            if _CSRF_WORT.search(str(key)) and isinstance(v, str) and v:
                out.append(_fund(f"JSON-Key {p}", v))
            _json_csrf(v, p, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _json_csrf(v, f"{pfad}[{i}]", out)


def suche_csrf(response: httpx.Response) -> list[Fund]:
    """Sucht CSRF/XSRF-Kandidaten in Headern, Set-Cookie-Namen und Body. Die Fund-Objekte tragen den
    Wert nur intern (nicht in repr); ausgegeben werden Fundort-Art, Laenge und Form."""
    funde: list[Fund] = []
    for hname, wert in response.headers.items():
        if _CSRF_WORT.search(hname) and wert:
            funde.append(_fund(f"Header {hname}", wert))
    for roh in response.headers.get_list("set-cookie"):
        cname, _, rest = roh.partition("=")
        if _CSRF_WORT.search(cname):
            wert = rest.split(";", 1)[0].strip().strip('"')
            if wert:
                funde.append(_fund(f"Cookie {cname.strip()}", wert))
    text = response.text
    daten: Any = None
    if text.lstrip()[:1] in ("{", "["):
        try:
            daten = json.loads(text)
        except Exception:  # noqa: BLE001
            daten = None
    if daten is not None:
        _json_csrf(daten, "", funde)
    else:
        for tag in re.findall(r"<(?:meta|input)\b[^>]*>", text, re.IGNORECASE):
            attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
            name = attrs.get("name") or attrs.get("property") or attrs.get("id") or ""
            wert = attrs.get("content") if tag.lower().startswith("<meta") else attrs.get("value")
            if _CSRF_WORT.search(name) and wert:
                art = "meta" if tag.lower().startswith("<meta") else "input"
                funde.append(_fund(f"{art}[name={name}]", wert))
        for var, wert in _SKRIPT_VAR.findall(text):
            funde.append(_fund(f"Skriptvariable {var}", wert))
    eindeutig: dict[tuple[str, str], Fund] = {}
    for f in funde:
        eindeutig.setdefault((f.ort, f.wert), f)
    return list(eindeutig.values())


CSRF_KANDIDATEN = (
    ("/WebUntis/embedded.do?showSidebar=true", False),
    ("/WebUntis/index.do", False),
    ("/WebUntis/", False),
    ("/WebUntis/api/csrf", True),
    ("/WebUntis/api/token/csrf", True),
)


async def csrf_quellensuche(http: httpx.AsyncClient, k: Kontext) -> tuple[list[Sonde], str | None]:
    """GET auf Kandidatenseiten (Redirects werden NICHT gefolgt). Gibt (Sonden, intern gemerktes
    Token oder None) zurueck; Werte werden nie ausgegeben."""
    sonden: list[Sonde] = []
    token: str | None = None
    for pfad, geraten in CSRF_KANDIDATEN:
        name = f"GET {pfad}" + (" [GERATEN]" if geraten else "")
        try:
            r = await http.get(pfad, headers=k.header(), follow_redirects=False)
        except Exception as exc:  # noqa: BLE001
            sonde = _fehler(name, exc)
            sonde.tag, sonde.extra = "csrf", {"fundorte": []}
            sonden.append(sonde)
            continue
        k.uebernimm_set_cookie(r)
        zeilen = [f"Status {r.status_code}, Content-Type {r.headers.get('content-type', '?')}, Laenge {len(r.content)}"]
        if 300 <= r.status_code < 400:
            zeilen.append(f"Redirect (nicht gefolgt) -> {_ziel(r.headers.get('location', '?'))}")
        funde = suche_csrf(r)
        for f in funde:
            zeilen.append(f"Fund: {f.ort} - {f.form}, {f.laenge} Zeichen")
        if not funde:
            erwaehnungen = len(_CSRF_WORT.findall(r.text))
            zeilen.append(
                f"Erwaehnung von csrf/xsrf im Body: {erwaehnungen}x (kein Wert extrahierbar)" if erwaehnungen else "kein CSRF-Fund"
            )
        if token is None:
            token = next((f.wert for f in funde if _TOKEN_ZEICHEN.fullmatch(f.wert)), None)
        sonden.append(Sonde(name, bool(funde), zeilen, tag="csrf", extra={"fundorte": [f.ort for f in funde]}))
    return sonden, token


# --- Interner JSON-RPC-Dienst (jsonrpc_web/jsonStudentDutyService), Methodennamen GERATEN ---

DEFAULT_RPC_PATH = "jsonrpc_web/jsonStudentDutyService"
DUTY_KANDIDATEN = ("getStudentDuties", "getAllStudentDuties", "getDuties", "getDutyTypes", "system.listMethods")
_ERLAUBTE_METHODE = re.compile(r"^(get|list|find)[A-Za-z0-9_.]*$")
_ERLAUBTE_EXTRA_METHODEN = {"system.listMethods"}
_AUTH_CODES = {-8520, -8504}
_PERMISSION_CODES = {-8509}
ERREICHBAR = {"ok", "methode_unbekannt", "rpc_fehler", "permission"}


def pruefe_methode(name: str) -> str:
    """Whitelist: nur lesende Methoden (Praefix get/list/find, oder system.listMethods)."""
    if name in _ERLAUBTE_EXTRA_METHODEN or _ERLAUBTE_METHODE.match(name):
        return name
    raise ValueError(f"Methode '{name}' abgelehnt: nur Namen mit Praefix get, list oder find sind erlaubt.")


def pruefe_pfad(pfad: str) -> str:
    """Normalisiert auf einen absoluten Pfad, der garantiert unter /WebUntis/ liegt."""
    roh = pfad.strip()
    if not roh or "://" in roh or "?" in roh or "#" in roh or ".." in roh.split("/") or "\\" in roh:
        raise ValueError(f"Pfad '{pfad}' abgelehnt: muss ein Pfad unter /WebUntis/ sein.")
    roh = roh.lstrip("/")
    if not roh.startswith("WebUntis/"):
        roh = "WebUntis/" + roh
    if roh == "WebUntis/":
        raise ValueError(f"Pfad '{pfad}' abgelehnt: kein Dienst angegeben.")
    return "/" + roh


def klassifiziere_antwort(response: httpx.Response) -> tuple[str, str]:
    """Ordnet eine Antwort des jsonrpc_web-Dienstes ein. Kategorien: ok, methode_unbekannt,
    rpc_fehler, permission, auth, http_auth (401/403), login_umleitung (Redirect/Login-HTML),
    unerwartet."""
    status = response.status_code
    if status in (401, 403):
        return "http_auth", f"HTTP {status}: Auth/Permission-Fehler"
    ctype = response.headers.get("content-type", "").lower()
    if 300 <= status < 400:
        return "login_umleitung", f"HTTP {status}: Redirect (vermutlich auf Login)"
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        if "html" in ctype or "<html" in response.text[:500].lower():
            return "login_umleitung", f"HTTP {status}: HTML statt JSON (vermutlich Login-Seite, Session nicht akzeptiert)"
        return "unerwartet", f"HTTP {status}: weder JSON-RPC noch HTML"
    error = body.get("error")
    if isinstance(error, dict):
        code, msg = error.get("code"), str(error.get("message", ""))[:150]
        if code == -32601:
            return "methode_unbekannt", f"JSON-RPC-Fehler {code}: Methode nicht gefunden ({msg})"
        if code in _AUTH_CODES:
            return "auth", f"JSON-RPC-Fehler {code}: nicht authentifiziert ({msg})"
        if code in _PERMISSION_CODES or "right" in msg.lower() or "permission" in msg.lower():
            return "permission", f"JSON-RPC-Fehler {code}: keine Berechtigung ({msg})"
        return "rpc_fehler", f"JSON-RPC-Fehler {code}: {msg}"
    if "result" in body:
        return "ok", f"HTTP {status}: JSON-RPC-Ergebnis"
    return "unerwartet", f"HTTP {status}: JSON ohne result/error, Keys {sorted(body.keys())}"


DUTY_METHODE = "getStudentDutySchedulerData"
MAX_HINT_BODY = 200


def kuerze_body(text: str, maximal: int = MAX_HINT_BODY) -> str:
    """Body fuer die Ausgabe: Skript/Style und Tags entfernt, Whitespace normalisiert, lange
    token-artige Zeichenfolgen ersetzt, auf `maximal` Zeichen gekuerzt."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    t = re.sub(r"<[^>]*>", " ", t)
    t = re.sub(r"[A-Za-z0-9_\-+/=.]{40,}", "[...]", html_lib.unescape(t))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= maximal else t[:maximal] + "…"


def _finde(obj: Any, key: str) -> tuple[bool, Any]:
    """Breitensuche: erster Wert zum Key `key` (case-insensitiv)."""
    queue = [obj]
    while queue:
        o = queue.pop(0)
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower() == key.lower():
                    return True, v
            queue.extend(o.values())
        elif isinstance(o, list):
            queue.extend(o)
    return False, None


def _wochen_ids(werte: Any) -> list[str]:
    if not isinstance(werte, list):
        return []
    return [str(w) for w in werte if (isinstance(w, int) and not isinstance(w, bool)) or (isinstance(w, str) and re.fullmatch(r"\d{6,8}", w))]


def _bereich(werte: Any) -> str:
    ids = _wochen_ids(werte)
    return f" ({ids[0]} .. {ids[-1]})" if ids else ""


def _anzahl(werte: Any) -> int:
    return len(werte) if isinstance(werte, (list, dict)) else 0


def struktur_bericht(result: Any) -> tuple[list[str], dict[str, Any]]:
    """Nur STRUKTUR der Antwort von getStudentDutySchedulerData: keine Schuelernamen, kein studentDTO,
    Schueler nur als laufende Nummer."""
    if not isinstance(result, dict):
        return [f"Ergebnis ist kein Objekt: {type(result).__name__}"], {"typ": type(result).__name__}
    daten: dict[str, Any] = {"result_keys": sorted(str(k) for k in result)}
    zeilen: list[str] = [f"result-Top-Level-Keys: {daten['result_keys']}"]
    for key in ("klasseName", "dutyName"):
        _, wert = _finde(result, key)
        daten[key] = wert if isinstance(wert, str) else None
        zeilen.append(f"{key}: {daten[key] if daten[key] is not None else 'nicht vorhanden'}")
    ok, matrix = _finde(result, "matrix")
    matrix = matrix if ok and isinstance(matrix, dict) else {}
    columns = matrix.get("columns") if isinstance(matrix.get("columns"), list) else []
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    spalten_ids = [c.get("id") for c in columns if isinstance(c, dict)]
    daten["columns"], daten["rows"] = len(columns), len(rows)
    zeilen.append(f"columns: {len(columns)}" + (f" (erste {_wochen_ids(spalten_ids)[0]}, letzte {_wochen_ids(spalten_ids)[-1]})" if _wochen_ids(spalten_ids) else ""))
    zeilen.append(f"rows: {len(rows)}")
    daten["zeilen"] = []
    for i, row in enumerate(rows, 1):
        row = row if isinstance(row, dict) else {}
        rel, abw = row.get("relations"), row.get("absences")
        daten["zeilen"].append({"nr": i, "relations": _anzahl(rel), "absences": _anzahl(abw)})
        if i <= 60:
            zeilen.append(f"  Schueler {i}: relations={_anzahl(rel)}{_bereich(rel)}, absences={_anzahl(abw)}{_bereich(abw)}")
    if len(rows) > 60:
        zeilen.append(f"  ... {len(rows) - 60} weitere Zeilen")
    _, optionen = _finde(result, "dutyOptions")
    duties = [
        f"{o.get('id')}={o.get('label', o.get('name', '?'))}" for o in (optionen if isinstance(optionen, list) else []) if isinstance(o, dict)
    ]
    daten["dutyOptions"] = duties
    zeilen.append("dutyOptions: " + (", ".join(duties) if duties else "nicht vorhanden"))
    for key in ("klasseOptions", "studentOptions"):
        _, wert = _finde(result, key)
        daten[key] = _anzahl(wert)
        zeilen.append(f"{key}: {daten[key]}")
    vorhanden, can_write = _finde(result, "canWrite")
    daten["canWrite"] = can_write if vorhanden and isinstance(can_write, (bool, int)) else vorhanden
    zeilen.append("canWrite: " + (f"vorhanden (Wert {str(can_write).lower()})" if vorhanden and isinstance(can_write, (bool, int)) else "vorhanden" if vorhanden else "nicht vorhanden"))
    return zeilen, daten


async def rpc_web_sonde(
    http: httpx.AsyncClient,
    pfad: str,
    methode: str,
    params: Any,
    headers: dict[str, str],
    geraten: bool = True,
    name: str | None = None,
    tag: str | None = None,
) -> Sonde:
    """Ein JSON-RPC-2.0-POST gegen einen internen /WebUntis/jsonrpc_web/-Dienst. Nur Methoden, die
    `pruefe_methode` bestehen (lesend). Fuer `getStudentDutySchedulerData` wird bei Erfolg nur die
    Struktur ausgegeben."""
    pruefe_methode(methode)
    pfad = pruefe_pfad(pfad)
    name = name or f"RPC {pfad} {methode}{' (Name GERATEN)' if geraten else ''}"
    payload = {"id": methode, "method": methode, "params": params, "jsonrpc": "2.0"}
    try:
        response = await http.post(pfad, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001
        sonde = _fehler(name, exc)
        sonde.tag = tag
        return sonde
    kategorie, text = klassifiziere_antwort(response)
    zeilen = [f"Status {response.status_code}, Content-Type {response.headers.get('content-type', '?')}, "
              f"Laenge {len(response.content)}", f"Einordnung: {kategorie} - {text}"]  # fmt: skip
    extra: dict[str, Any] = {"status": response.status_code, "body_csrf": False}
    treffer: list[tuple[str, str]] = []
    roh: Any = None
    if kategorie == "ok":
        result = response.json().get("result")
        if methode == DUTY_METHODE:
            struktur_zeilen, roh = struktur_bericht(result)
            zeilen += struktur_zeilen
            extra["result"] = result  # nur intern (fuer den ID-Abgleich), nie in Ausgabe/--json
            extra["duty_options"] = roh.get("dutyOptions") if isinstance(roh, dict) else None
        else:
            zeilen.append(_beschreibe(result))
            if isinstance(result, list):
                zeilen.append(f"Keys: {sorted({k for e in result if isinstance(e, dict) for k in e})}")
                zeilen.append("Beispiele: " + _fmt(result[:3]))
            elif isinstance(result, dict):
                zeilen.append("Beispiel: " + _fmt(result))
            else:
                zeilen.append("Wert: " + _fmt(result)[:MAX_BODY])
            treffer = suche_stichworte(result, f"{methode}")[:10]
            roh = kuerze(maskiere(result))
    elif kategorie == "unerwartet":
        zeilen.append("Body: " + response.text[:MAX_BODY])
    elif kategorie in ("http_auth", "login_umleitung") and response.text.strip():
        hinweis = kuerze_body(response.text)
        if hinweis:
            zeilen.append("Body (gekuerzt): " + hinweis)
            extra["body_csrf"] = bool(_CSRF_WORT.search(hinweis))
    return Sonde(name, kategorie == "ok" and not _ist_leer(roh), zeilen, treffer, roh, kategorie, tag, extra)


async def sonde_duty_service(
    http: httpx.AsyncClient, session_id: str | None, schule: str, pfad: str = DEFAULT_RPC_PATH
) -> list[Sonde]:
    headers = _cookie_headers(session_id, schule)
    return [await rpc_web_sonde(http, pfad, m, {}, headers) for m in DUTY_KANDIDATEN]


async def sonde_gezielt(
    http: httpx.AsyncClient, session_id: str | None, schule: str, pfad: str, methode: str, params: Any
) -> list[Sonde]:
    return [await rpc_web_sonde(http, pfad, methode, params, _cookie_headers(session_id, schule), geraten=False)]


DUTY_KOMBINATIONEN = (
    ("a", "nur Cookies", False, False),
    ("b", "Cookies + X-CSRF-TOKEN", True, False),
    ("c", "Cookies + Authorization Bearer (JWT von token/new)", False, True),
    ("d", "Cookies + X-CSRF-TOKEN + Bearer", True, True),
)


def _duty_fest(http: httpx.AsyncClient) -> dict[str, str]:
    basis = str(http.base_url).rstrip("/")
    return {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": basis,
        "Referer": f"{basis}/WebUntis/embedded.do?showSidebar=true",
    }


async def sonde_duty_matrix(
    http: httpx.AsyncClient,
    k: Kontext,
    klasse_id: int,
    duty_ids: list[int],
    csrf: str | None,
    jwt: str | None,
    pfad: str = DEFAULT_RPC_PATH,
) -> list[Sonde]:
    """getStudentDutySchedulerData [klasseId, dutyId] in mehreren Header-Kombinationen. Kombinationen,
    deren Zutat (CSRF-Token / JWT) fehlt, werden uebersprungen (kein Request)."""
    fest = _duty_fest(http)
    kombis: list[tuple[str, str, dict[str, str] | None, str | None]] = []
    for key, text, braucht_csrf, braucht_jwt in DUTY_KOMBINATIONEN:
        extra: dict[str, str] = {}
        fehlt = [n for n, noetig, da in (("CSRF-Token", braucht_csrf, csrf), ("JWT", braucht_jwt, jwt)) if noetig and not da]
        if braucht_csrf and csrf:
            extra["X-CSRF-TOKEN"] = csrf
        if braucht_jwt and jwt:
            extra["Authorization"] = f"Bearer {jwt}"
        kombis.append((key, text, None if fehlt else extra, ", ".join(fehlt) or None))
    hyp = "HYPOTHESE: JWT als X-CSRF-TOKEN"
    kombis.append(("e", f"{hyp} statt CSRF-Token", {"X-CSRF-TOKEN": jwt} if jwt else None, None if jwt else "JWT"))
    kombis.append(("e+", f"{hyp} zusaetzlich zu Bearer", {"X-CSRF-TOKEN": jwt, "Authorization": f"Bearer {jwt}"} if jwt else None, None if jwt else "JWT"))
    sonden: list[Sonde] = []
    for key, text, extra, fehlt in kombis:
        for duty_id in duty_ids:
            name = f"Duty ({key}) {text}, klasseId={klasse_id}, dutyId={duty_id}"
            if extra is None:
                sonden.append(Sonde(name, False, [f"uebersprungen: {fehlt} nicht vorhanden"], tag=f"duty:{key}"))
                continue
            headers = {**k.header(), **fest, **extra}
            sonden.append(
                await rpc_web_sonde(http, pfad, DUTY_METHODE, [klasse_id, duty_id], headers, geraten=False, name=name, tag=f"duty:{key}")
            )
    return sonden


# --- ID-Abgleich: getStudents, Matrix-IDs, optionaler lesender DB-Abgleich, dutyOptions ---

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DATUM_RE = re.compile(r"\d{4}-\d{2}-\d{2}([T ].*)?|\d{1,2}\.\d{1,2}\.\d{4}")
UUID_SCHWELLE = 0.9


def _ist_yyyymmdd(zahl: int) -> bool:
    s = str(zahl)
    return len(s) == 8 and 1900 <= int(s[:4]) <= 2100 and 1 <= int(s[4:6]) <= 12 and 1 <= int(s[6:]) <= 31


def klassifiziere_wert(wert: Any) -> str:
    """Formklasse eines Werts: leer, bool, numerisch, UUID, Datum, kurzer String, Freitext, Struktur."""
    if wert is None or wert == "" or wert == [] or wert == {}:
        return "leer"
    if isinstance(wert, bool):
        return "bool"
    if isinstance(wert, int):
        return "Datum" if _ist_yyyymmdd(wert) else "numerisch"
    if isinstance(wert, float):
        return "numerisch"
    if isinstance(wert, (list, dict)):
        return "Struktur"
    text = str(wert).strip()
    if not text:
        return "leer"
    if _UUID_RE.fullmatch(text):
        return "UUID"
    if _DATUM_RE.fullmatch(text):
        return "Datum"
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return "Datum" if text.isdigit() and _ist_yyyymmdd(int(text)) else "numerisch"
    return "kurzer String" if len(text) <= 16 and not re.search(r"\s", text) else "Freitext"


def profil_keys(eintraege: list[Any]) -> dict[str, dict[str, Any]]:
    """Je Key ueber alle dict-Eintraege: Anzahl Eintraege, befuellt, Verteilung der Formklassen."""
    dicts = [e for e in eintraege if isinstance(e, dict)]
    profil: dict[str, dict[str, Any]] = {}
    for key in sorted({str(k) for e in dicts for k in e}):
        klassen = Counter(klassifiziere_wert(e.get(key)) for e in dicts if key in e)
        befuellt = sum(n for k, n in klassen.items() if k != "leer")
        profil[key] = {"n": len(dicts), "befuellt": befuellt, "klassen": {k: n for k, n in klassen.items() if k != "leer"}}
    return profil


def profil_zeilen(profil: dict[str, dict[str, Any]]) -> list[str]:
    zeilen = []
    for key, p in profil.items():
        n, bef = p["n"], p["befuellt"]
        form = ", ".join(f"{k} {round(100 * c / bef)}%" for k, c in sorted(p["klassen"].items(), key=lambda kv: -kv[1])) or "-"
        zeilen.append(f"  {key}: befuellt {bef}/{n} ({round(100 * bef / n) if n else 0}%); Form: {form}")
    return zeilen


def uuid_keys(profil: dict[str, dict[str, Any]], schwelle: float = UUID_SCHWELLE) -> list[str]:
    """Keys, deren befuellte Werte (zu mindestens `schwelle`) UUID-foermig sind: Kandidaten fuer externe_id."""
    return [
        k for k, p in profil.items() if p["befuellt"] and p["klassen"].get("UUID", 0) / p["befuellt"] >= schwelle
    ]


def _maskiere_beispiel(eintrag: Any) -> Any:
    """Beispiel-Eintrag mit zusaetzlicher Vorsicht: Namensfelder (maskiere), UUIDs auf 4 Zeichen,
    Datumswerte/Geburtsfelder als <Datum>, sonstige Strings ab 3 Zeichen auf 2 Zeichen + '…'."""
    if isinstance(eintrag, dict):
        return {k: _maskiere_beispiel_wert(str(k), v) for k, v in maskiere(eintrag).items()}
    return eintrag


def _maskiere_beispiel_wert(key: str, wert: Any) -> Any:
    if "birth" in key.lower() or "geb" in key.lower() or klassifiziere_wert(wert) == "Datum":
        return "<Datum>"
    if isinstance(wert, str) and wert.endswith("…"):
        return wert
    if isinstance(wert, str) and _UUID_RE.fullmatch(wert.strip()):
        return wert[:4] + "…"
    if isinstance(wert, str) and len(wert) >= 3:
        return wert[:2] + "…"
    if isinstance(wert, (dict, list)):
        return "<Struktur>"
    return wert


def fehlerklasse(exc: Exception) -> str:
    text = str(exc).lower()
    if "-32601" in text or "method not found" in text or "not found" in text:
        return "Methode nicht vorhanden"
    if "-8509" in text or "right" in text or "permission" in text or "403" in text or "forbidden" in text:
        return "keine Berechtigung"
    if "-8520" in text or "-8504" in text or "401" in text or "not authenticated" in text:
        return "nicht authentifiziert"
    return f"sonstiger Fehler ({type(exc).__name__})"


async def sonde_students(client: Any, schuljahr: dict[str, Any] | None) -> Sonde:
    """getStudents (jsonrpc.do): Anzahl, Keys, Formprofil je Key, UUID-Kandidat. Bei Fehler/leer
    werden GERATENE lesende Alternativen versucht. Die Eintraege stehen nur intern in extra."""
    name = "getStudents"
    zeilen: list[str] = []
    versuche: list[tuple[str, dict[str, Any], bool]] = [("getStudents", {}, False)]
    if schuljahr and "id" in schuljahr:
        versuche.append(("getStudents", {"schoolyearId": schuljahr["id"]}, True))
    for methode, params, geraten in versuche:
        pruefe_methode(methode)
        label = f"{methode} {sorted(params)}" + (" [GERATEN]" if geraten else "")
        try:
            daten = await client.call(methode, params)
        except Exception as exc:  # noqa: BLE001
            zeilen.append(f"{label}: Fehlerklasse {fehlerklasse(exc)}")
            continue
        if not isinstance(daten, list) or not daten or not any(isinstance(e, dict) for e in daten):
            zeilen.append(f"{label}: leer oder unerwartetes Format ({_beschreibe(daten)})")
            continue
        eintraege = [e for e in daten if isinstance(e, dict)]
        profil = profil_keys(eintraege)
        kandidaten = uuid_keys(profil)
        zeilen.append(f"{label}: ✔")
        zeilen += [f"Anzahl Eintraege: {len(eintraege)}", f"Keys: {sorted(profil)}", "Formprofil je Key:", *profil_zeilen(profil)]
        zeilen.append("Beispiel (maskiert): " + json.dumps(_maskiere_beispiel(eintraege[0]), ensure_ascii=False, default=str))
        zeilen.append("UUID-foermige Keys (Kandidat fuer externe_id): " + (", ".join(kandidaten) if kandidaten else "keiner"))
        extra = {"eintraege": eintraege, "uuid_keys": kandidaten, "methode": label, "anzahl": len(eintraege)}
        return Sonde(name, True, zeilen, roh={"anzahl": len(eintraege), "keys": sorted(profil), "uuid_keys": kandidaten}, tag="students", extra=extra)
    return Sonde(name, False, zeilen, tag="students", extra={"eintraege": [], "uuid_keys": [], "anzahl": 0})


_FEHLER_NORM = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalisiere_name(text: Any) -> str:
    """Casefold, Umlaute -> ae/oe/ue, ß -> ss, restliche Akzente entfernt, alle Nicht-Buchstaben
    (Bindestrich, Leerzeichen, Apostroph, Komma) entfernt: 'Müller-Lüdenscheidt' == 'mueller luedenscheidt'."""
    t = str(text or "").casefold().translate(_FEHLER_NORM)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", t)


def _ci(d: Any, *namen: str) -> Any:
    if not isinstance(d, dict):
        return None
    low = {_norm(str(k)): v for k, v in d.items()}
    for n in namen:
        if _norm(n) in low and low[_norm(n)] not in (None, ""):
            return low[_norm(n)]
    return None


def _name_key(eintraege: list[dict[str, Any]], kandidaten: tuple[str, ...]) -> str | None:
    vorhandene = {_norm(str(k)): str(k) for e in eintraege for k in e}
    for n in kandidaten:
        if _norm(n) in vorhandene:
            return vorhandene[_norm(n)]
    return None


def _skalar(v: Any) -> str | None:
    return str(v) if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) != "" else None


def _eindeutigkeit(schluessel: list[str | None], index: Counter) -> tuple[int, int, int]:
    eindeutig = mehrdeutig = fehlt = 0
    for k in schluessel:
        n = index.get(k, 0) if k else 0
        eindeutig += n == 1
        mehrdeutig += n > 1
        fehlt += n == 0
    return eindeutig, mehrdeutig, fehlt


def _matrix_rows(result: Any) -> list[dict[str, Any]]:
    ok, matrix = _finde(result, "matrix")
    rows = matrix.get("rows") if ok and isinstance(matrix, dict) else None
    return [r.get("studentDTO") for r in (rows or []) if isinstance(r, dict) and isinstance(r.get("studentDTO"), dict)]


def abgleich_matrix(students: list[dict[str, Any]], dtos: list[dict[str, Any]]) -> dict[str, Any]:
    """Zaehlt (keine Namen im Ergebnis): wie viele Matrix-IDs als Wert welches getStudents-Keys vorkommen
    und wie viele Matrix-Schueler eindeutig/mehrdeutig/nicht ueber (Vor-, Nachname) bzw. displayName
    gefunden werden. `zuordnung` (intern): Matrix-ID -> getStudents-Eintrag ueber den besten ID-Key."""
    m = len(dtos)
    ids = [_skalar(_ci(d, "id")) for d in dtos]
    keys = sorted({str(k) for e in students for k in e})
    treffer: dict[str, int] = {}
    for k in keys:
        werte = {_skalar(e.get(k)) for e in students} - {None}
        n = sum(1 for i in ids if i is not None and i in werte)
        if n:
            treffer[k] = n
    bester = max(treffer, key=lambda k: (treffer[k], k == "id"), default=None)
    zuordnung: dict[str, dict[str, Any]] = {}
    if bester:
        by_wert = {_skalar(e.get(bester)): e for e in students if _skalar(e.get(bester))}
        zuordnung = {i: by_wert[i] for i in ids if i in by_wert}
    fk = _name_key(students, ("foreName", "firstName", "vorname"))
    lk = _name_key(students, ("lastName", "surname", "nachname", "longName"))
    dk = _name_key(students, ("displayName",))
    idx = Counter(normalisiere_name(e.get(fk)) + "|" + normalisiere_name(e.get(lk)) for e in students) if fk and lk else Counter()
    idx_dn: Counter = Counter()
    for e in students:
        f, la = normalisiere_name(e.get(fk)), normalisiere_name(e.get(lk))
        for t in {f + la, la + f} if (f or la) else set():
            idx_dn[t] += 1
        if dk and e.get(dk):
            idx_dn[normalisiere_name(e.get(dk))] += 1
    namen = [normalisiere_name(_ci(d, "firstname", "foreName")) + "|" + normalisiere_name(_ci(d, "lastname", "surname", "longName")) for d in dtos]
    namen = [n if n != "|" else None for n in namen]
    dn = [normalisiere_name(_ci(d, "displayName")) or None for d in dtos]
    ne, nm, nf = _eindeutigkeit(namen, idx)
    de, dm, df = _eindeutigkeit(dn, idx_dn)
    return {
        "m": m, "id_treffer": treffer, "id_key": bester, "id_n": treffer.get(bester, 0) if bester else 0,
        "name_keys": (fk, lk), "name": (ne, nm, nf), "display": (de, dm, df), "zuordnung": zuordnung,
    }  # fmt: skip


def abgleich_zeilen(a: dict[str, Any]) -> list[str]:
    m = a["m"]
    keys = ", ".join(f"{k}: {n}/{m}" for k, n in sorted(a["id_treffer"].items(), key=lambda kv: -kv[1])[:6]) or "kein Key"
    ne, nm, nf = a["name"]
    de, dm, df = a["display"]
    return [
        f"Matrix-Schueler: {m}",
        f"studentDTO.id kommt in getStudents vor (Key: Treffer): {keys}",
        f"Bester ID-Key: {a['id_key'] or 'keiner'} ({a['id_n']}/{m})",
        f"Namensabgleich (Keys {a['name_keys'][0]}/{a['name_keys'][1]}): eindeutig {ne}, mehrdeutig {nm}, nicht gefunden {nf}",
        f"displayName-Abgleich: eindeutig {de}, mehrdeutig {dm}, nicht gefunden {df}",
    ]


async def lade_schueler_readonly(session_factory: Any) -> list[tuple[str, str, str, int | None]]:
    """NUR `SELECT externe_id, vorname, nachname, klasse_id FROM schueler`. Kein commit, keine Schreibzugriffe."""
    from sqlalchemy import select

    from app.models.schueler import Schueler

    async with session_factory() as db:
        result = await db.execute(select(Schueler.externe_id, Schueler.vorname, Schueler.nachname, Schueler.klasse_id))
        return [(r[0], r[1], r[2], r[3]) for r in result.all()]


def abgleich_db(students: list[dict[str, Any]], a: dict[str, Any], dtos: list[dict[str, Any]], db: list[tuple[Any, ...]], praefer_keys: list[str]) -> dict[str, Any]:
    """Reine Zaehlung (keine Namen/externe_ids im Ergebnis). Schluessel mit den meisten externe_id-Treffern
    (Vorrang UUID-foermige Keys) ist die Bruecke; Matrix-Schueler -> getStudents -> Bruecke -> Schueler."""
    ext = {str(r[0]) for r in db if r[0]}
    keys = sorted({str(k) for e in students for k in e})
    treffer = {}
    for k in keys:
        n = sum(1 for e in students if _skalar(e.get(k)) in ext)
        if n:
            treffer[k] = n
    bruecke = max(treffer, key=lambda k: (treffer[k], k in praefer_keys), default=None)
    via_uuid = 0
    if bruecke:
        via_uuid = sum(1 for e in a["zuordnung"].values() if _skalar(e.get(bruecke)) in ext)
    idx = Counter(normalisiere_name(r[1]) + "|" + normalisiere_name(r[2]) for r in db)
    namen = [normalisiere_name(_ci(d, "firstname", "foreName")) + "|" + normalisiere_name(_ci(d, "lastname", "surname", "longName")) for d in dtos]
    ne, nm, nf = _eindeutigkeit([n if n != "|" else None for n in namen], idx)
    return {"anzahl_db": len(db), "treffer": treffer, "bruecke": bruecke, "via_uuid": via_uuid, "m": a["m"], "name": (ne, nm, nf)}


def abgleich_db_zeilen(d: dict[str, Any], n_students: int) -> list[str]:
    keys = ", ".join(f"{k}: {n}/{n_students} ({round(100 * n / n_students) if n_students else 0}%)" for k, n in sorted(d["treffer"].items(), key=lambda kv: -kv[1])[:6]) or "kein Key"
    ne, nm, nf = d["name"]
    return [
        f"Schueler in DB (nur gelesen): {d['anzahl_db']}",
        f"getStudents-Eintraege mit Wert in Schueler.externe_id (Key: Treffer): {keys}",
        f"Bruecken-Key: {d['bruecke'] or 'keiner'}",
        f"Matrix-Schueler -> getStudents -> externe_id -> Schueler: {d['via_uuid']}/{d['m']}",
        f"Fallback (Vorname, Nachname normalisiert) gegen Schueler: eindeutig {ne}, mehrdeutig {nm}, keiner {nf}",
    ]


DUTY_OPTIONEN_VARIANTEN = (("[klasseId]", lambda k: [k]), ("[klasseId, null]", lambda k: [k, None]), ("[klasseId, 0]", lambda k: [k, 0]))


async def sonde_duty_optionen(http: httpx.AsyncClient, k: Kontext, klasse_id: int, csrf: str | None, pfad: str = DEFAULT_RPC_PATH) -> list[Sonde]:
    """GERATENE Parametervarianten (lesend, Kombination b), um an `dutyOptions` zu kommen."""
    if not csrf:
        return [Sonde("dutyOptions-Varianten", False, ["uebersprungen: kein CSRF-Token"], tag="dutyopt")]
    headers = {**k.header(), **_duty_fest(http), "X-CSRF-TOKEN": csrf}
    sonden = []
    for label, bauen in DUTY_OPTIONEN_VARIANTEN:
        name = f"dutyOptions-Variante {label} (Params GERATEN), klasseId={klasse_id}"
        s = await rpc_web_sonde(http, pfad, DUTY_METHODE, bauen(klasse_id), headers, geraten=False, name=name, tag="dutyopt")
        s.extra["gefunden"] = bool(s.extra.get("duty_options"))
        sonden.append(s)
    return sonden


def duty_optionen_gefunden(sonden: list[Sonde]) -> list[str]:
    for s in sonden:
        if s.extra.get("duty_options"):
            return list(s.extra["duty_options"])
    return []


def schlussfolgerung(f: dict[str, Any]) -> str:
    if not f.get("students_ok"):
        return "getStudents nicht verfuegbar → keine ID-Bruecke ermittelbar"
    brk, key = f.get("bruecke"), f.get("id_key")
    if f.get("db") and brk and f.get("via_uuid", 0) > 0 and f.get("id_n", 0) > 0:
        return f"Schluessel `{brk}` aus getStudents entspricht Schueler.externe_id → Zuordnung ueber numerische ID (`{key}`) moeglich ({f['via_uuid']}/{f['m']})"
    if not f.get("db") and f.get("uuid_keys") and f.get("id_n", 0) > 0:
        return f"Schluessel `{f['uuid_keys'][0]}` aus getStudents ist UUID-foermig (Kandidat fuer externe_id), Bestaetigung nur mit --mit-db moeglich"
    mehr = f.get("db_name", f.get("name", (0, 0, 0)))[1]
    return f"keine ID-Bruecke gefunden → nur Namensabgleich ({mehr} mehrdeutig)"


def _id_befund(sonden: list[Sonde]) -> list[str]:
    st = next((s for s in sonden if s.tag == "students"), None)
    zeilen: list[str] = []
    if st is None:
        return zeilen
    uk = st.extra.get("uuid_keys", [])
    zeilen.append(f"(a) getStudents: {'✔' if st.ok else '✖'}; UUID-Key vorhanden: " + (f"ja ({', '.join(uk)})" if uk else "nein"))
    ab = next((s for s in sonden if s.tag == "abgleich"), None)
    fakten: dict[str, Any] = {"students_ok": st.ok, "uuid_keys": uk}
    if ab is not None and ab.extra.get("m") is not None:
        zeilen.append(f"(b) Matrix-ID in getStudents: {ab.extra['id_n']}/{ab.extra['m']}" + (f" (Key {ab.extra['id_key']})" if ab.extra.get("id_key") else ""))
        fakten.update(m=ab.extra["m"], id_n=ab.extra["id_n"], id_key=ab.extra["id_key"], name=ab.extra["name"])
    else:
        zeilen.append("(b) Matrix-ID in getStudents: nicht ermittelbar (keine Matrix)")
    db = next((s for s in sonden if s.tag == "dbabgleich"), None)
    if db is not None and db.extra.get("anzahl_db") is not None:
        ne = db.extra["name"][0]
        zeilen.append(f"(c) Abbildung auf Schueler: ueber UUID {db.extra['via_uuid']}/{db.extra['m']}, ueber Namen eindeutig {ne}/{db.extra['m']}")
        fakten.update(db=True, bruecke=db.extra["bruecke"], via_uuid=db.extra["via_uuid"], db_name=db.extra["name"])
    else:
        zeilen.append("(c) Abbildung auf Schueler: nicht geprueft (ohne --mit-db oder DB-Fehler)")
    opts = duty_optionen_gefunden([s for s in sonden if (s.tag or "").startswith("duty") or s.tag == "dutyopt"])
    zeilen.append("(d) dutyOptions gefunden: " + (f"ja ({', '.join(opts)})" if opts else "nein"))
    zeilen.append("(e) Schlussfolgerung: " + schlussfolgerung(fakten))
    return zeilen


async def hole_matrix_ergebnis(
    http: httpx.AsyncClient, k: Kontext, klasse_id: int, duty_id: int, csrf: str | None, bisherige: list[Sonde], pfad: str
) -> tuple[Any, str]:
    """Matrix-`result` (Kombination b) fuer (Klasse, Dienst): zuerst aus dem schon laufenden Duty-Matrix-Lauf
    wiederverwendet, sonst frisch geholt. Rueckgabe (result oder None, Hinweis)."""
    marke = f"klasseId={klasse_id}, dutyId={duty_id}"
    for s in bisherige:
        if s.tag == "duty:b" and s.name.endswith(marke):
            return s.extra.get("result"), "wiederverwendet" if s.extra.get("result") is not None else "Kombination b lieferte keine Daten"
    if not csrf:
        return None, "kein CSRF-Token"
    headers = {**k.header(), **_duty_fest(http), "X-CSRF-TOKEN": csrf}
    s = await rpc_web_sonde(http, pfad, DUTY_METHODE, [klasse_id, duty_id], headers, geraten=False, name=f"Duty (b) {marke}", tag="duty:b")
    return s.extra.get("result"), "neu geholt" if s.extra.get("result") is not None else f"keine Daten ({s.kategorie})"


async def sonden_id_abgleich(
    students: Sonde, matrix_results: list[tuple[int, Any, str]], mit_db: bool, db_factory: Any = None
) -> list[Sonde]:
    """Reiner Abgleich (kein Netzwerk). `matrix_results`: (klasse_id, result|None, Hinweis)."""
    if not students.ok:
        return []
    eintraege = students.extra["eintraege"]
    zeilen, dtos = [], []
    for klasse_id, result, hinweis in matrix_results:
        rows = _matrix_rows(result) if result is not None else []
        zeilen.append(f"Klasse {klasse_id}: {len(rows)} Matrix-Schueler ({hinweis})")
        dtos += rows
    if not dtos:
        return [Sonde("ID-Abgleich Matrix ↔ getStudents", False, [*zeilen, "keine Matrix-Schueler vorhanden"], tag="abgleich", extra={"m": None})]
    a = abgleich_matrix(eintraege, dtos)
    sonden = [Sonde(
        "ID-Abgleich Matrix ↔ getStudents", a["id_n"] > 0, [*zeilen, *abgleich_zeilen(a)],
        roh={k: v for k, v in a.items() if k != "zuordnung"}, tag="abgleich",
        extra={"m": a["m"], "id_n": a["id_n"], "id_key": a["id_key"], "name": a["name"]},
    )]  # fmt: skip
    if mit_db:
        try:
            if db_factory is None:
                from app.core.database import async_session_factory as db_factory
            db = await lade_schueler_readonly(db_factory)
        except Exception as exc:  # noqa: BLE001
            sonden.append(_fehler("DB-Abgleich (read-only)", exc))
            sonden[-1].tag = "dbabgleich"
            return sonden
        d = abgleich_db(eintraege, a, dtos, db, students.extra["uuid_keys"])
        sonden.append(Sonde("DB-Abgleich (read-only, nur Zahlen)", d["bruecke"] is not None, abgleich_db_zeilen(d, len(eintraege)), roh=d, tag="dbabgleich", extra=d))
    return sonden


async def fuehre_alle_sonden_aus(
    client: Any,
    http: httpx.AsyncClient,
    rpc_path: str = DEFAULT_RPC_PATH,
    klasse_id: int | None = None,
    duty_ids: list[int] | None = None,
    abgleich_klassen: list[int] | None = None,
    mit_db: bool = False,
    db_factory: Any = None,
) -> list[Sonde]:
    schuljahr = await hole_schuljahr(client)
    klassen = await sonde_klassen(client, schuljahr)
    sonden = [await sonde_holidays(client, schuljahr), klassen]
    students = await sonde_students(client, schuljahr)
    sonden.append(students)
    sonden += await sonde_rpc_kandidaten(client)
    k = Kontext.aus_client(client, settings.webuntis_school)
    sonden.append(cookie_uebersicht(k))
    k.setze_schoolname()
    token_sonde, token = await diagnose_token(http, k)
    sonden.append(token_sonde)
    sonden += await sonde_rest(http, k, token, schuljahr)
    csrf_sonden, csrf = await csrf_quellensuche(http, k)
    sonden += csrf_sonden
    sonden += await sonde_duty_service(http, getattr(client, "_session_id", None), settings.webuntis_school, rpc_path)
    sonden.append(cookie_status_sonde(k))
    klasse = klasse_id if klasse_id is not None else klassen.extra.get("erste_klasse_id")
    if isinstance(klasse, int):
        sonden += await sonde_duty_matrix(http, k, klasse, duty_ids or [26], csrf, token, rpc_path)
        if any(x.kategorie == "ok" for x in sonden if (x.tag or "").startswith("duty:")):
            sonden += await sonde_duty_optionen(http, k, klasse, csrf, rpc_path)
    else:
        sonden.append(Sonde("Duty-Matrix", False, ["uebersprungen: keine Klassen-ID (getKlassen leer, --klasse-id nicht angegeben)"]))
    ziel_klassen = abgleich_klassen or ([klasse] if isinstance(klasse, int) else [])
    if students.ok and ziel_klassen:
        ergebnisse = []
        for kid in ziel_klassen:
            result, hinweis = await hole_matrix_ergebnis(http, k, kid, 26, csrf, sonden, rpc_path)
            ergebnisse.append((kid, result, hinweis))
        sonden += await sonden_id_abgleich(students, ergebnisse, mit_db, db_factory)
    return sonden


_DUTY_ERKLAERUNG = {
    "a": "Cookies genuegen",
    "b": "CSRF-Token genuegt",
    "c": "Bearer-JWT genuegt",
    "d": "CSRF-Token plus Bearer-JWT noetig",
    "e": "JWT als X-CSRF-TOKEN genuegt (Hypothese bestaetigt)",
    "e+": "JWT als X-CSRF-TOKEN plus Bearer genuegt (Hypothese bestaetigt)",
}


def _duty_schluessel(s: Sonde) -> str:
    return (s.tag or "")[5:]


def _duty_befund(sonden: list[Sonde]) -> list[str]:
    duty = [s for s in sonden if (s.tag or "").startswith("duty:") and s.kategorie is not None]
    if not duty:
        return []
    schluessel = _duty_schluessel
    ohne_403 = [s for s in duty if s.extra.get("status") != 403]
    zeilen = ["Duty-Kombinationen ohne HTTP 403: " + (", ".join(f"{schluessel(s)} ({s.kategorie})" for s in ohne_403) or "keine")]
    ok = [s for s in duty if s.kategorie == "ok"]
    if ok:
        key = schluessel(ok[0])
        zeilen.append(f"Schlussfolgerung: Kombination ({key}) liefert Daten → {_DUTY_ERKLAERUNG.get(key, 'siehe Strukturbericht')}")
    elif ohne_403:
        liste = ", ".join(f"{schluessel(s)} ({s.kategorie})" for s in ohne_403)
        zeilen.append(f"Schlussfolgerung: Kein 403 bei Kombination {liste}, aber keine Daten → Auth-Huerde evtl. genommen, Einordnung/Body oben pruefen")
    else:
        getestet = {schluessel(s) for s in duty}
        csrf_da = "b" in getestet or "d" in getestet
        jwt_da = "c" in getestet
        hinweis = "; 403-Body erwaehnt CSRF" if any(s.extra.get("body_csrf") for s in duty) else ""
        if csrf_da and jwt_da:
            zeilen.append("Schlussfolgerung: 403 unabhaengig von Token/CSRF → vermutlich Rechte-Problem des Service-Accounts" + hinweis)
        else:
            fehlt = " und ".join(n for n, da in (("CSRF-Token (keine Quelle gefunden)", csrf_da), ("JWT (token/new ohne Token)", jwt_da)) if not da)
            zeilen.append(
                f"Schlussfolgerung: 403 in allen getesteten Kombinationen, aber ohne {fehlt} → CSRF-/Token-Hypothese nicht abschliessend pruefbar, sonst vermutlich Rechte-Problem{hinweis}"
            )
    return zeilen


def befund(sonden: list[Sonde]) -> list[str]:
    zeilen = ["", "=== Befund ==="]
    for s in sonden:
        zeilen.append(f"{'✔' if s.ok else '✖'} {s.name}")
    token = [s for s in sonden if s.tag == "token"]
    csrf = [s for s in sonden if s.tag == "csrf"]
    cookies = [s for s in sonden if s.tag == "cookies"]
    for s in token:
        jwt = "ja" if s.extra.get("jwt") else "nein"
        zeilen.append(f"token/new: ✔ (JWT: {jwt})" if s.ok else f"token/new: ✖ (JWT: nein, Klasse: {s.extra.get('klasse', '?')})")
    for s in cookies:
        tenant, schule = (_HERKUNFT_TEXT.get(s.extra.get(n, "fehlt"), "fehlt") for n in ("Tenant-Id", "schoolname"))
        zeilen.append(f"Cookies: Tenant-Id {tenant}, schoolname {schule}")
    if csrf:
        orte = sorted({o for s in csrf for o in s.extra.get("fundorte", [])})
        zeilen.append(f"CSRF-Quelle gefunden: ja ({', '.join(orte)})" if orte else "CSRF-Quelle gefunden: nein")
    web = [s for s in sonden if s.kategorie is not None]
    if web:
        kats = sorted({s.kategorie for s in web if s.kategorie})
        if any(k in ERREICHBAR for k in kats):
            zeilen.append(f"jsonrpc_web-Dienst: erreichbar mit der Service-Account-Session (Einordnungen: {', '.join(kats)})")
        else:
            zeilen.append(
                "jsonrpc_web-Dienst: NICHT nutzbar mit der Service-Account-Session "
                f"(Einordnungen: {', '.join(kats)}; http_auth = HTTP 401/403, login_umleitung = Redirect/Login-HTML, "
                "auth/permission = JSON-RPC-Fehler)"
            )
    alle = [(s.name, f, w) for s in sonden for f, w in s.treffer]
    if alle:
        fundorte = "; ".join(f"{f} ({w})" for _, f, w in alle[:15])
        zeilen.append(f"Klassendienst-Indizien: ja - Fundorte: {fundorte}")
    else:
        zeilen.append("Klassendienst-Indizien: nein (keine Stichwort-Treffer)")
    zeilen += _duty_befund(sonden)
    zeilen += _id_befund(sonden)
    return zeilen


def _ausgabe(sonden: list[Sonde]) -> None:
    print("HINWEIS: REST-Pfade unter /WebUntis/api/ sind GERATEN/inoffiziell; nur lesend (get*/GET).")
    print("Personenbezogene Namensfelder sind maskiert; Token-, Cookie- und CSRF-Werte werden nie ausgegeben.")
    for s in sonden:
        print(f"\n--- {s.name} --- {'✔' if s.ok else '✖'}")
        for z in s.zeilen:
            print("  " + z)
    for z in befund(sonden):
        print(z)


async def _main(
    json_pfad: str | None,
    rpc_path: str,
    rpc_method: str | None,
    rpc_params: Any,
    klasse_id: int | None = None,
    duty_ids: list[int] | None = None,
    abgleich_klassen: list[int] | None = None,
    mit_db: bool = False,
) -> None:
    async with WebUntisClient(settings) as client:
        async with httpx.AsyncClient(base_url=f"https://{settings.webuntis_server}", timeout=TIMEOUT) as http:
            if rpc_method:
                sonden = await sonde_gezielt(
                    http, getattr(client, "_session_id", None), settings.webuntis_school, rpc_path, rpc_method, rpc_params
                )
            else:
                sonden = await fuehre_alle_sonden_aus(client, http, rpc_path, klasse_id, duty_ids, abgleich_klassen, mit_db)
    _ausgabe(sonden)
    if json_pfad:
        with open(json_pfad, "w", encoding="utf-8") as f:
            json.dump(
                [{"name": s.name, "ok": s.ok, "zeilen": s.zeilen, "treffer": s.treffer, "antwort": s.roh} for s in sonden],
                f, ensure_ascii=False, indent=2, default=str,
            )  # fmt: skip
        print(f"\nMaskierte Vollausgabe geschrieben: {json_pfad}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", metavar="DATEI", default=None, help="vollstaendige maskierte Ausgabe als JSON schreiben")
    parser.add_argument("--rpc-path", default=DEFAULT_RPC_PATH, help=f"Dienstpfad unter /WebUntis/ (Default {DEFAULT_RPC_PATH})")
    parser.add_argument("--rpc-method", default=None, help="gezielt nur diese Methode aufrufen (nur get*/list*/find*)")
    parser.add_argument("--rpc-params", default="{}", help="JSON-Params fuer --rpc-method (Default {})")
    parser.add_argument("--klasse-id", type=int, default=None, help="Klassen-ID fuer getStudentDutySchedulerData (Default: erste Klasse aus getKlassen)")
    parser.add_argument("--duty-id", type=int, action="append", default=None, help="Dienst-ID (Default 26; mehrfach angebbar)")
    parser.add_argument("--abgleich-klasse-id", type=int, action="append", default=None, help="Klasse(n) fuer den ID-Abgleich Matrix <-> getStudents (Default: --klasse-id; mehrfach angebbar)")
    parser.add_argument("--mit-db", action="store_true", help="zusaetzlich rein lesender Abgleich gegen die Tabelle schueler (nur Zahlen in der Ausgabe)")
    args = parser.parse_args(argv)
    args.duty_id = args.duty_id or [26]
    try:
        args.rpc_path = pruefe_pfad(args.rpc_path)
        if args.rpc_method:
            pruefe_methode(args.rpc_method)
        args.rpc_params = json.loads(args.rpc_params)
        if not isinstance(args.rpc_params, (dict, list)):
            raise ValueError("--rpc-params muss ein JSON-Objekt oder -Array sein.")
    except (ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return args


if __name__ == "__main__":
    _args = parse_args()
    asyncio.run(_main(_args.json, _args.rpc_path, _args.rpc_method, _args.rpc_params, _args.klasse_id, _args.duty_id, _args.abgleich_klasse_id, _args.mit_db))
