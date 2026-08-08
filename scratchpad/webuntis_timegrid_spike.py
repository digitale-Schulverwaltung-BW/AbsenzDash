"""
AbsenzDash WebUntis-Spike (Wegwerf-Diagnoseskript, kein Projektcode).

Prueft das reale Antwortformat von getTimegridUnits (schulweiter Stundenraster-Abruf,
kein elementType/elementId noetig) fuer den Design-Vorschlag "Fehlzeiten mit
Stundenangabe statt Uhrzeit anzeigen" (docs/superpowers/specs/2026-08-08-fehlzeit-
stunden-anzeige-design.md).

Nur lesende Aufrufe. Keine personenbezogenen Daten in dieser Antwort zu erwarten
(reine Zeitraster-Stammdaten), trotzdem wird die volle Rohantwort ausgegeben, um das
Feldschema zu pruefen.

Nutzung:
    cd scratchpad
    cp .env.example .env   # echte Werte eintragen (bereits vorhanden)
    pip install httpx python-dotenv
    python webuntis_timegrid_spike.py
"""

import json
import os
import sys

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


def main():
    missing = [
        name
        for name, value in [
            ("WEBUNTIS_SERVER", SERVER),
            ("WEBUNTIS_SCHOOL", SCHOOL),
            ("WEBUNTIS_USERNAME", USERNAME),
            ("WEBUNTIS_PASSWORD", PASSWORD),
        ]
        if not value
    ]
    if missing:
        print(f"Fehlende .env-Werte: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    with httpx.Client() as client:
        session_id = authenticate(client)
        try:
            result, error = rpc_call(client, session_id, "getTimegridUnits", {})
            print("getTimegridUnits ohne Parameter:")
            print(f"  error={error}")
            print(f"  result={json.dumps(result, ensure_ascii=False, indent=2)}")

            result2, error2 = rpc_call(client, session_id, "getTimegrid", {})
            print("\ngetTimegrid ohne Parameter (Alternativname, zur Sicherheit geprueft):")
            print(f"  error={error2}")
            print(f"  result={json.dumps(result2, ensure_ascii=False, indent=2)}")
        finally:
            rpc_call(client, session_id, "logout", {})


if __name__ == "__main__":
    main()
