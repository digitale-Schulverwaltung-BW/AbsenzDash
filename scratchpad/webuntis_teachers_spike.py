"""
Wegwerf-Spike: prüft, ob getTeachers() eine E-Mail-Adresse mitliefert
(für Roadmap-Punkt 1, Rollen-Zuweisungs-UI: WebUntis-Code automatisch über
E-Mail-Abgleich mit WP-Nutzern ermitteln).

Nur lesend. Personenbezogene Felder werden redigiert - es werden nur
Feldnamen (Keys) und ob 'email'/'mail' vorhanden+befüllt ist ausgegeben,
keine echten Werte.

Nutzung:
    cd scratchpad
    python webuntis_teachers_spike.py
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

REDACT_KEYS = {"name", "surname", "forname", "forename", "longname", "displayname",
               "firstname", "lastname", "email", "mail", "title"}


def redact(value, key=""):
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value[:3]] + (
            [f"... ({len(value)} Einträge insgesamt)"] if len(value) > 3 else []
        )
    if key.lower() in REDACT_KEYS and isinstance(value, str) and value:
        return "[REDACTED, non-empty]"
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
        "params": {"user": USERNAME, "password": PASSWORD, "client": "AbsenzDashTeacherSpike"},
        "jsonrpc": "2.0",
    }
    resp = client.post(rpc_url(), json=payload, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Login fehlgeschlagen: {body['error']}")
    return body["result"]["sessionId"]


def main():
    missing = [n for n, v in [("WEBUNTIS_SERVER", SERVER), ("WEBUNTIS_SCHOOL", SCHOOL),
                               ("WEBUNTIS_USERNAME", USERNAME), ("WEBUNTIS_PASSWORD", PASSWORD)] if not v]
    if missing:
        print(f"Fehlende .env-Werte: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    with httpx.Client() as client:
        session_id = authenticate(client)
        print("Login OK.")

        result, error = rpc_call(client, session_id, "getTeachers", {})
        if error:
            print(f"getTeachers FEHLER: {error}")
            return

        print(f"{len(result)} Lehrkräfte erhalten.")
        if not result:
            return

        sample = result[0]
        print("Felder im ersten Datensatz (Werte redigiert):")
        print(json.dumps(redact(sample), indent=2, ensure_ascii=False))

        all_keys = set()
        for t in result:
            all_keys |= set(t.keys())
        print(f"\nAlle vorkommenden Feldnamen über {len(result)} Einträge: {sorted(all_keys)}")

        email_keys = [k for k in all_keys if "mail" in k.lower()]
        print(f"\nE-Mail-artige Feldnamen gefunden: {email_keys}")
        for k in email_keys:
            non_empty = sum(1 for t in result if t.get(k))
            print(f"  '{k}': {non_empty}/{len(result)} Einträge nicht-leer")


if __name__ == "__main__":
    main()
