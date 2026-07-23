"""
AbsenzDash WebUntis-Spike (Wegwerf-Diagnoseskript, kein Projektcode).

Prüft die vier offenen Risiken aus TECH-SPEC.md Abschnitt 5 gegen die echte
WebUntis-Instanz: REST- vs. JSON-RPC-Fehlzeitenendpunkt, Klassenlehrkraft-Feld
in getKlassen, Berechtigung für getClassregEvents, tatsächlich gepflegte
Klassenbuch-Kategorien.

Nur lesende Aufrufe. Personenbezogene Felder (Namen) werden in der Ausgabe
redigiert - es werden nur Feldstrukturen/Schlüssel und Beispiel-Zählwerte
ausgegeben, keine echten Schülerdaten.

Nutzung:
    cd scratchpad
    cp .env.example .env   # echte Werte eintragen
    pip install httpx python-dotenv
    python webuntis_spike.py
"""

import json
import os
import sys
from datetime import date, timedelta

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SERVER = os.environ.get("WEBUNTIS_SERVER")
SCHOOL = os.environ.get("WEBUNTIS_SCHOOL")
USERNAME = os.environ.get("WEBUNTIS_USERNAME")
PASSWORD = os.environ.get("WEBUNTIS_PASSWORD")

REDACT_KEYS = {
    "name",
    "surname",
    "forname",
    "fore_name",
    "sur_name",
    "studentname",
    "longname",
    "displayname",
    "firstname",
    "lastname",
    "text",
    "username",
}


def redact(value, key=""):
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value[:3]] + (
            [f"... ({len(value)} Einträge insgesamt)"] if len(value) > 3 else []
        )
    if key.lower() in REDACT_KEYS and isinstance(value, str) and value:
        return "[REDACTED]"
    return value


def rpc_url():
    return f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"


def rpc_call(client, session_id, method, params):
    payload = {"id": method, "method": method, "params": params, "jsonrpc": "2.0"}
    headers = {"Cookie": f"JSESSIONID={session_id}"} if session_id else {}
    resp = client.post(rpc_url(), json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        return None, body["error"]
    return body.get("result"), None


def authenticate(client):
    payload = {
        "id": "auth",
        "method": "authenticate",
        "params": {"user": USERNAME, "password": PASSWORD, "client": "AbsenzDashSpike"},
        "jsonrpc": "2.0",
    }
    resp = client.post(rpc_url(), json=payload, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Login fehlgeschlagen: {body['error']}")
    return body["result"]["sessionId"]


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    missing = [
        name
        for name, val in [
            ("WEBUNTIS_SERVER", SERVER),
            ("WEBUNTIS_SCHOOL", SCHOOL),
            ("WEBUNTIS_USERNAME", USERNAME),
            ("WEBUNTIS_PASSWORD", PASSWORD),
        ]
        if not val
    ]
    if missing:
        print(f"Fehlende .env-Werte: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    start = today - timedelta(days=30)
    start_int = int(start.strftime("%Y%m%d"))
    end_int = int(today.strftime("%Y%m%d"))

    with httpx.Client() as client:
        section("1) Login (JSON-RPC authenticate)")
        session_id = authenticate(client)
        print("Login OK, Session erhalten.")

        section("2) Risiko #2 - Klassenlehrkraft-Feld in getKlassen")
        result, error = rpc_call(client, session_id, "getKlassen", {})
        if error:
            print(f"FEHLER: {error}")
        else:
            sample = result[0] if result else {}
            print(f"{len(result)} Klassen erhalten. Felder im ersten Datensatz:")
            print(json.dumps(redact(sample), indent=2, ensure_ascii=False))
            print(
                "-> Prüfen: enthält der Datensatz teacher1/teacher2 o.ä.? "
                "Falls nicht: getTeachers zusätzlich nötig."
            )

        section("3) Risiko #1a - REST-Endpunkt /WebUntis/api/classreg/absences/students")
        try:
            rest_resp = client.get(
                f"https://{SERVER}/WebUntis/api/classreg/absences/students",
                params={
                    "startDate": start.isoformat().replace("-", ""),
                    "endDate": today.isoformat().replace("-", ""),
                },
                headers={"Cookie": f"JSESSIONID={session_id}"},
                timeout=15,
            )
            print(f"HTTP Status: {rest_resp.status_code}")
            if rest_resp.status_code == 200:
                data = rest_resp.json()
                print(json.dumps(redact(data), indent=2, ensure_ascii=False)[:3000])
            else:
                print(f"Body: {rest_resp.text[:500]}")
            print(
                "-> Prüfen: 200 mit isExcused-Feld = REST nutzbar. "
                "401/403/404 = JSON-RPC-Fallback nötig (siehe Abschnitt 3b)."
            )
        except Exception as exc:
            print(f"REST-Aufruf fehlgeschlagen: {exc}")

        section("3b) Risiko #1b - Fallback: JSON-RPC getTimetableWithAbsences")
        result, error = rpc_call(
            client,
            session_id,
            "getTimetableWithAbsences",
            {"options": {"startDate": start_int, "endDate": end_int}},
        )
        if error:
            print(f"FEHLER: {error}")
        else:
            entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result
            print(f"{len(entries) if entries else 0} Einträge im Testzeitraum.")
            if entries:
                print(json.dumps(redact(entries[0]), indent=2, ensure_ascii=False))

        section("4) Risiko #3 - Berechtigung getClassregEvents")
        result, error = rpc_call(
            client,
            session_id,
            "getClassregEvents",
            {"startDate": start_int, "endDate": end_int},
        )
        if error:
            print(f"FEHLER (evtl. fehlende Berechtigung 'classregevents read for all'): {error}")
        else:
            print(f"{len(result) if result else 0} Klassenbuch-Einträge im Testzeitraum.")
            if result:
                print(json.dumps(redact(result[0]), indent=2, ensure_ascii=False))

        section("5) Risiko #4 - tatsächlich gepflegte Klassenbuch-Kategorien")
        result, error = rpc_call(client, session_id, "getClassregCategories", {})
        if error:
            print(f"FEHLER: {error}")
        else:
            names = [r.get("name") for r in result] if result else []
            print(f"Kategorien ({len(names)}): {names}")

        result, error = rpc_call(client, session_id, "getClassregCategoryGroups", {})
        if error:
            print(f"FEHLER: {error}")
        else:
            names = [r.get("name") for r in result] if result else []
            print(f"Kategorie-Gruppen ({len(names)}): {names}")

        section("Logout")
        rpc_call(client, session_id, "logout", {})
        print("Fertig. Bitte die komplette Ausgabe oben zurückmelden.")


if __name__ == "__main__":
    main()
