"""
AbsenzDash WebUntis-Spike (Wegwerf-Diagnoseskript, kein Projektcode).

Prueft fuer ROADMAP Bundle B ("Fach" soll den Kurznamen zeigen, nicht den
Langnamen), ob/wie sich der rohe Fehlzeiten-'subjectId'-Wert (aktuell 1:1 in
fehlzeit.fach gespeichert) auf ein Kuerzel via getSubjects abbilden laesst.
Eigenstaendiges Skript statt Erweiterung von webuntis_spike.py, weil dessen
Fehlzeiten-Abfrage aktuell an einem Datumsbereich ausserhalb jedes
Schuljahres (Sommerferien) scheitert - hier wird bewusst ein Datumsbereich
aus dem noch laufenden Schuljahr 2025/2026 (vor den Ferien) verwendet.

Nutzung:
    cd scratchpad
    python3 webuntis_subjects_spike.py
"""

import json
import os

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


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    missing = [n for n, v in [("WEBUNTIS_SERVER", SERVER), ("WEBUNTIS_SCHOOL", SCHOOL), ("WEBUNTIS_USERNAME", USERNAME), ("WEBUNTIS_PASSWORD", PASSWORD)] if not v]
    if missing:
        print(f"Fehlende .env-Werte: {missing}")
        return

    with httpx.Client() as client:
        session_id = authenticate(client)
        print("Login OK.")

        section("A) getSubjects - Faecher-Stammdaten")
        subjects_result, subjects_error = rpc_call(client, session_id, "getSubjects", {})
        if subjects_error:
            print(f"getSubjects: FEHLER {subjects_error}")
            subjects_result = []
        else:
            print(f"{len(subjects_result)} Faecher. Beispiel-Eintrag (ungekuerzt, keine PII):")
            if subjects_result:
                print(json.dumps(subjects_result[0], indent=2, ensure_ascii=False))
            print("\nAlle Faecher (id / name / longName / alternateName):")
            for s in sorted(subjects_result, key=lambda s: str(s.get("name", ""))):
                print(
                    f"  id={s.get('id')!r:>6} name={s.get('name')!r:15} "
                    f"longName={s.get('longName')!r:35} alternateName={s.get('alternateName')!r}"
                )
            interessant = [
                s for s in subjects_result
                if any(
                    needle in str(s.get(feld, "")).lower()
                    for feld in ("name", "longName", "alternateName")
                    for needle in ("bild", "kunst", "bk", "kom")
                )
            ]
            print(f"\n-> Kandidaten fuer 'BK'/'BKom'/'Bildende Kunst': {json.dumps(interessant, ensure_ascii=False)}")

        section("B) getTimetableWithAbsences im laufenden Schuljahr 2025/2026 (vor den Sommerferien)")
        # Schuljahr 2025/2026 laeuft laut getSchoolyears von 20250915 bis 20260729 -
        # 30-Tage-Fenster mitten im zweiten Schulhalbjahr, sicher innerhalb eines Schuljahres.
        result, error = rpc_call(
            client,
            session_id,
            "getTimetableWithAbsences",
            {"options": {"startDate": 20260201, "endDate": 20260228}},
        )
        if error:
            print(f"getTimetableWithAbsences: FEHLER {error}")
            entries = []
        else:
            entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else (result or [])
            print(f"{len(entries)} Fehlzeiten-Perioden erhalten.")
            if entries:
                all_keys = set()
                for e in entries:
                    all_keys |= set(e.keys())
                print(f"Feldnamen: {sorted(all_keys)}")
                print("\nBeispiel-Eintrag mit subjectId (ungekuerzt, keine PII in diesen Feldern):")
                with_subject = [e for e in entries if e.get("subjectId")]
                print(json.dumps(with_subject[0] if with_subject else entries[0], indent=2, ensure_ascii=False))

        if entries and subjects_result:
            observed = {e.get("subjectId") for e in entries if e.get("subjectId")}
            print(f"\nBeobachtete Fehlzeiten-'subjectId'-Werte (Stichprobe): {sorted(str(v) for v in observed)[:20]}")

            by_id = {str(s.get("id")): s for s in subjects_result}
            by_longname = {str(s.get("longName")): s for s in subjects_result if s.get("longName")}
            by_name = {str(s.get("name")): s for s in subjects_result if s.get("name")}

            print(f"-> Match gegen getSubjects.id: {observed & set(by_id) or 'KEINE'}")
            print(f"-> Match gegen getSubjects.longName: {observed & set(by_longname) or 'KEINE'}")
            print(f"-> Match gegen getSubjects.name (Kuerzel): {observed & set(by_name) or 'KEINE'}")
        elif entries:
            print("\ngetSubjects lieferte keine Daten - Kreuzabgleich nicht moeglich.")
        else:
            print("\nKeine Fehlzeiten-Eintraege im Testzeitraum - Kreuzabgleich nicht moeglich.")

        section("Logout")
        rpc_call(client, session_id, "logout", {})
        print("Fertig.")


if __name__ == "__main__":
    main()
