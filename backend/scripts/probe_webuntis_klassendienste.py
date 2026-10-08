"""Rein LESENDE Sonde: liefert WebUntis an der Schul-Instanz "Klassendienste" (Klassensprecher,
Entschuldigungspflicht, Attestpflicht) und brauchbare Ferien/Feiertage (getHolidays)?

Es werden ausschliesslich JSON-RPC-Methoden `get*` und HTTP-GET-Requests abgesetzt. Kein
DB-Zugriff, keine Schreibzugriffe (ausser der optionalen Datei-Ausgabe via --json). Die REST-Pfade
unter /WebUntis/api/ sind GERATEN bzw. inoffiziell. Personenbezogene Werte werden in der Ausgabe
maskiert (siehe `maskiere`), damit sie in einen Chat eingefuegt werden kann.

Nutzung (im laufenden Backend-Container):
    python -m scripts.probe_webuntis_klassendienste [--json DATEI]
    python -m scripts.probe_webuntis_klassendienste --rpc-method getXyz [--rpc-params '{"a": 1}'] [--rpc-path PFAD]

Mit --rpc-method wird gezielt nur dieser eine Aufruf gegen den internen Dienst (Default
jsonrpc_web/jsonStudentDutyService) abgesetzt. Erlaubt sind nur Methoden, die mit get, list oder
find beginnen (zusaetzlich system.listMethods); Pfade muessen unter /WebUntis/ liegen.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

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
    return Sonde(name, True, zeilen, treffer, kuerze(maskiere(daten[:3], ausnahmen)))


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


async def hole_bearer_token(http: httpx.AsyncClient, cookie_headers: dict[str, str]) -> str | None:
    """GET /WebUntis/api/token/new (nur lesend). Das Token wird nie ausgegeben."""
    try:
        r = await http.get("/WebUntis/api/token/new", headers=cookie_headers)
        if r.is_success and r.text.strip():
            return r.text.strip().strip('"')
    except Exception:  # noqa: BLE001
        pass
    return None


async def sonde_rest(http: httpx.AsyncClient, session_id: str | None, schule: str, schuljahr: dict[str, Any] | None) -> list[Sonde]:
    cookie_headers = _cookie_headers(session_id, schule)
    token = await hole_bearer_token(http, cookie_headers)
    varianten: list[tuple[str, dict[str, str]]] = [("Cookie", cookie_headers)]
    if token:
        varianten.append(("Bearer", {"Authorization": f"Bearer {token}"}))
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


async def rpc_web_sonde(
    http: httpx.AsyncClient, pfad: str, methode: str, params: Any, headers: dict[str, str], geraten: bool = True
) -> Sonde:
    """Ein JSON-RPC-2.0-POST gegen einen internen /WebUntis/jsonrpc_web/-Dienst. Nur Methoden, die
    `pruefe_methode` bestehen (lesend)."""
    pruefe_methode(methode)
    pfad = pruefe_pfad(pfad)
    name = f"RPC {pfad} {methode}{' (Name GERATEN)' if geraten else ''}"
    payload = {"id": methode, "method": methode, "params": params, "jsonrpc": "2.0"}
    try:
        response = await http.post(pfad, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return _fehler(name, exc)
    kategorie, text = klassifiziere_antwort(response)
    zeilen = [f"Status {response.status_code}, Content-Type {response.headers.get('content-type', '?')}, "
              f"Laenge {len(response.content)}", f"Einordnung: {kategorie} - {text}"]  # fmt: skip
    treffer: list[tuple[str, str]] = []
    roh: Any = None
    if kategorie == "ok":
        result = response.json().get("result")
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
    return Sonde(name, kategorie == "ok" and not _ist_leer(roh), zeilen, treffer, roh, kategorie)


async def sonde_duty_service(
    http: httpx.AsyncClient, session_id: str | None, schule: str, pfad: str = DEFAULT_RPC_PATH
) -> list[Sonde]:
    headers = _cookie_headers(session_id, schule)
    return [await rpc_web_sonde(http, pfad, m, {}, headers) for m in DUTY_KANDIDATEN]


async def sonde_gezielt(
    http: httpx.AsyncClient, session_id: str | None, schule: str, pfad: str, methode: str, params: Any
) -> list[Sonde]:
    return [await rpc_web_sonde(http, pfad, methode, params, _cookie_headers(session_id, schule), geraten=False)]


async def fuehre_alle_sonden_aus(client: Any, http: httpx.AsyncClient, rpc_path: str = DEFAULT_RPC_PATH) -> list[Sonde]:
    schuljahr = await hole_schuljahr(client)
    sonden = [await sonde_holidays(client, schuljahr), await sonde_klassen(client, schuljahr)]
    sonden += await sonde_rpc_kandidaten(client)
    session_id = getattr(client, "_session_id", None)
    sonden += await sonde_rest(http, session_id, settings.webuntis_school, schuljahr)
    sonden += await sonde_duty_service(http, session_id, settings.webuntis_school, rpc_path)
    return sonden


def befund(sonden: list[Sonde]) -> list[str]:
    zeilen = ["", "=== Befund ==="]
    for s in sonden:
        zeilen.append(f"{'✔' if s.ok else '✖'} {s.name}")
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
    return zeilen


def _ausgabe(sonden: list[Sonde]) -> None:
    print("HINWEIS: REST-Pfade unter /WebUntis/api/ sind GERATEN/inoffiziell; nur lesend (get*/GET).")
    print("Personenbezogene Namensfelder sind maskiert.")
    for s in sonden:
        print(f"\n--- {s.name} --- {'✔' if s.ok else '✖'}")
        for z in s.zeilen:
            print("  " + z)
    for z in befund(sonden):
        print(z)


async def _main(json_pfad: str | None, rpc_path: str, rpc_method: str | None, rpc_params: Any) -> None:
    async with WebUntisClient(settings) as client:
        async with httpx.AsyncClient(base_url=f"https://{settings.webuntis_server}", timeout=TIMEOUT) as http:
            if rpc_method:
                sonden = await sonde_gezielt(
                    http, getattr(client, "_session_id", None), settings.webuntis_school, rpc_path, rpc_method, rpc_params
                )
            else:
                sonden = await fuehre_alle_sonden_aus(client, http, rpc_path)
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
    args = parser.parse_args(argv)
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
    asyncio.run(_main(_args.json, _args.rpc_path, _args.rpc_method, _args.rpc_params))
