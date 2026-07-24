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
    "forename",
    "fore_name",
    "sur_name",
    "studentname",
    "longname",
    "displayname",
    "firstname",
    "lastname",
    "text",
    "username",
    "email",
    "mail",
    "birthdate",
    "phone",
    "address",
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

                section("3c) Vertiefung - welche Felder tragen Entschuldigungs-Infos?")
                all_keys = set()
                for e in entries:
                    all_keys |= set(e.keys())
                print(f"Alle in {len(entries)} Einträgen vorkommenden Feldnamen: {sorted(all_keys)}")

                checked_true = [e for e in entries if e.get("checked") is True]
                print(f"Einträge mit checked=true: {len(checked_true)}")
                if checked_true:
                    print("Beispiel checked=true:")
                    print(json.dumps(redact(checked_true[0]), indent=2, ensure_ascii=False))

                statuses = {}
                for e in entries:
                    s = e.get("status")
                    statuses[s] = statuses.get(s, 0) + 1
                print(f"Verteilung des 'status'-Felds: {statuses}")

                for candidate_key in ("absenceReason", "excuseStatus", "reason", "isExcused"):
                    with_key = [e for e in entries if candidate_key in e]
                    print(f"Einträge mit Feld '{candidate_key}': {len(with_key)}")
                    if with_key:
                        print(json.dumps(redact(with_key[0]), indent=2, ensure_ascii=False))

        section("4) Risiko #3 - Berechtigung getClassregEvents")
        result, error = rpc_call(
            client,
            session_id,
            "getClassregEvents",
            {"startDate": start_int, "endDate": end_int},
        )
        classreg_entries = result if not error else None
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

        section("6) Neu - Methodenname für Entschuldigungsstatus-Stammdaten (Name/Langname/zaehlt/aktiv)")
        candidates = [
            "getExcuseStatuses",
            "getExcuseStatus",
            "getStudentExcuseStatuses",
            "getAbsenceReasons",
            "getAbsenceStatuses",
            "getStudentAbsenceReasons",
        ]
        for method in candidates:
            result, error = rpc_call(client, session_id, method, {})
            if error:
                print(f"{method}: FEHLER {error.get('message', error)}")
            else:
                print(f"{method}: ERFOLG -> {json.dumps(redact(result), indent=2, ensure_ascii=False)[:1500]}")

        section("7) Neu - Schueler-Stammdaten (getStudents)")
        result, error = rpc_call(client, session_id, "getStudents", {})
        all_students = result
        if error:
            print(f"getStudents: FEHLER {error}")
        else:
            print(f"{len(result) if result else 0} Schüler erhalten. Felder im ersten Datensatz:")
            if result:
                print(json.dumps(redact(result[0]), indent=2, ensure_ascii=False))
                has_klasse_ref = any(
                    k in result[0] for k in ("klasseId", "klasse", "schoolclasses", "classId")
                )
                print(f"-> Enthält ein Klassen-Referenz-Feld? {has_klasse_ref}")
                keys_union = set()
                for r in result[:50]:
                    keys_union |= set(r.keys())
                print(f"Feldnamen über die ersten 50 Datensätze: {sorted(keys_union)}")

        section("7a) Neu - getStudents mit schoolyearId-Filter (Reduktion auf aktive Schueler?)")
        schoolyears_result, _ = rpc_call(client, session_id, "getSchoolyears", {})
        current_sy, _ = rpc_call(client, session_id, "getCurrentSchoolyear", {})
        current_sy_id = current_sy.get("id") if current_sy else None
        for param_variant in (
            {"schoolyearId": current_sy_id},
            {"schoolyear": current_sy_id},
        ):
            result, error = rpc_call(client, session_id, "getStudents", param_variant)
            if error:
                print(f"getStudents({param_variant}): FEHLER {error}")
            else:
                count = len(result) if result else 0
                print(f"getStudents({param_variant}): {count} Schüler zurück (Gesamtliste war {len(all_students) if all_students else '?'})")

        section("7b) Neu - getStudents mit Klassen-Filter (Schueler<->Klasse-Zuordnung)")
        klassen_result, klassen_error = rpc_call(client, session_id, "getKlassen", {})
        test_klasse_id = klassen_result[0]["id"] if klassen_result else None
        print(f"Teste gegen Klasse id={test_klasse_id}")
        for param_variant in (
            {"klasseId": test_klasse_id},
            {"id": test_klasse_id, "type": 1},
            {"schoolclassId": test_klasse_id},
        ):
            result, error = rpc_call(client, session_id, "getStudents", param_variant)
            if error:
                print(f"getStudents({param_variant}): FEHLER {error}")
            else:
                count = len(result) if result else 0
                scoped = all_students is not None and count < len(all_students)
                print(
                    f"getStudents({param_variant}): {count} Schüler zurück "
                    f"(gefiltert gegenüber Gesamtliste: {scoped})"
                )
                if result:
                    print(json.dumps(redact(result[0]), indent=2, ensure_ascii=False))

        section("7c) Neu - getTimetable für Klassen-Element (30 Tage statt 1 Tag)")
        result, error = rpc_call(
            client,
            session_id,
            "getTimetable",
            {
                "options": {
                    "element": {"id": test_klasse_id, "type": 1},
                    "startDate": start_int,
                    "endDate": end_int,
                }
            },
        )
        if error:
            print(f"getTimetable(type=1, id={test_klasse_id}): FEHLER {error}")
        else:
            print(f"{len(result) if result else 0} Timetable-Einträge über 30 Tage. Erster Eintrag:")
            if result:
                print(json.dumps(redact(result[0]), indent=2, ensure_ascii=False))

        section("8) Neu - sind getStudents-'id' und Fehlzeiten/Klassenbuch-'studentId' dieselbe Entität?")
        example_pair = None
        if all_students and classreg_entries:
            by_name = {}
            for s in all_students:
                fore = (s.get("foreName") or "").strip().lower()
                long_ = (s.get("longName") or "").strip().lower()
                if fore and long_:
                    by_name[(fore, long_)] = s["id"]

            matched = 0
            example_pair = None
            for entry in classreg_entries:
                fore = (entry.get("forname") or "").strip().lower()
                sur = (entry.get("surname") or "").strip().lower()
                key = (fore, sur)
                if key in by_name:
                    matched += 1
                    if example_pair is None:
                        example_pair = (by_name[key], entry.get("studentid"))
            print(
                f"{matched} von {len(classreg_entries)} Klassenbuch-Einträgen per Namensabgleich "
                f"einem getStudents-Datensatz zugeordnet."
            )
            if example_pair:
                print(
                    f"Beispiel-Korrelation: getStudents.id={example_pair[0]} "
                    f"<-> Klassenbuch/Fehlzeiten.studentId={example_pair[1]!r}"
                )
            else:
                print("Keine Korrelation per Namensabgleich gefunden.")
        else:
            print("Übersprungen - all_students oder classreg_entries leer/fehlerhaft.")

        section("9) Neu - getTimetable fuer Schueler-Element (type=5) - liefert 'kl' die Klasse?")
        test_student_id = example_pair[0] if example_pair else (
            all_students[0]["id"] if all_students else None
        )
        print(f"Nutze bestätigt aktiven Schüler id={test_student_id} (aus Abschnitt 8)")
        result, error = rpc_call(
            client,
            session_id,
            "getTimetable",
            {
                "options": {
                    "element": {"id": test_student_id, "type": 5},
                    "startDate": start_int,
                    "endDate": end_int,
                }
            },
        )
        if error:
            print(f"getTimetable(type=5, id={test_student_id}): FEHLER {error}")
        else:
            print(f"{len(result) if result else 0} Timetable-Einträge für Schüler id={test_student_id}.")
            if result:
                print(json.dumps(redact(result[0]), indent=2, ensure_ascii=False))

        section("10) Neu - Schuljahre per API (getSchoolyears / getCurrentSchoolyear)")
        result, error = rpc_call(client, session_id, "getSchoolyears", {})
        if error:
            print(f"getSchoolyears: FEHLER {error}")
        else:
            print(f"{len(result) if result else 0} Schuljahre erhalten:")
            for sy in result or []:
                print(f"  id={sy.get('id')} name={sy.get('name')!r} start={sy.get('startDate')} end={sy.get('endDate')}")

        result, error = rpc_call(client, session_id, "getCurrentSchoolyear", {})
        if error:
            print(f"getCurrentSchoolyear: FEHLER {error}")
        else:
            print(f"Aktuelles Schuljahr: {json.dumps(result, indent=2, ensure_ascii=False)}")

        section("11) Neu - Tragen getTimetableWithAbsences-Einträge (Fehlzeiten) einen Namen?")
        print(
            "Frage: TECH-SPEC.md Abschnitt 1.3 setzt Namensabgleich für Fehlzeiten UND "
            "Klassenbuch voraus, aber Abschnitt 1.2 listet für Fehlzeiten-Einträge keine "
            "Namensfelder. Prüfung: welche Feldnamen kommen in periodsWithAbsences wirklich vor?"
        )
        if entries:
            all_keys = set()
            for e in entries:
                all_keys |= set(e.keys())
            print(f"Alle Feldnamen über {len(entries)} Fehlzeiten-Einträge: {sorted(all_keys)}")

            name_like_keys = [
                k for k in all_keys if k.lower() in
                {"forname", "surname", "name", "studentname", "displayname", "longname", "fore_name", "sur_name"}
            ]
            print(f"-> Namens-artige Feldnamen gefunden: {name_like_keys or 'KEINE'}")

            if name_like_keys and all_students:
                by_name = {}
                for s in all_students:
                    fore = (s.get("foreName") or "").strip().lower()
                    long_ = (s.get("longName") or "").strip().lower()
                    if fore and long_:
                        by_name[(fore, long_)] = s["id"]
                fore_key = next((k for k in name_like_keys if "fore" in k.lower()), None)
                sur_key = next((k for k in name_like_keys if k.lower() in ("surname", "name", "longname")), None)
                if fore_key and sur_key:
                    matched = 0
                    for e in entries:
                        fore = (e.get(fore_key) or "").strip().lower()
                        sur = (e.get(sur_key) or "").strip().lower()
                        if (fore, sur) in by_name:
                            matched += 1
                    print(
                        f"-> {matched} von {len(entries)} Fehlzeiten-Einträgen per Namensabgleich "
                        f"({fore_key}+{sur_key}) einem getStudents-Datensatz zugeordnet."
                    )
            else:
                print(
                    "-> Kein Namensabgleich für Fehlzeiten möglich mit den beobachteten Feldern. "
                    "studentId müsste über einen anderen Weg (z.B. Klassenbuch-Eintrag mit "
                    "derselben studentId, oder eine noch unbekannte Zusatzabfrage) aufgelöst werden."
                )
        else:
            print("Keine Fehlzeiten-Einträge im Testzeitraum - Prüfung nicht möglich.")

        section("12) Neu - getTimetableWithAbsences pro Schüler-Element (type=5) - UUID ohne Namensabgleich lernbar?")
        print(
            "Frage: akzeptiert getTimetableWithAbsences denselben options.element-Filter wie "
            "getTimetable? Falls ja: liefert ein auf einen bekannten Schüler (per Integer-ID) "
            "gescopter Aufruf konsistent dessen studentId-UUID zurück - ganz ohne Namensabgleich?"
        )
        result, error = rpc_call(
            client,
            session_id,
            "getTimetableWithAbsences",
            {
                "options": {
                    "element": {"id": test_student_id, "type": 5},
                    "startDate": start_int,
                    "endDate": end_int,
                }
            },
        )
        if error:
            print(f"getTimetableWithAbsences(element type=5, id={test_student_id}): FEHLER {error}")
        else:
            scoped_entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result
            print(f"{len(scoped_entries) if scoped_entries else 0} Fehlzeiten-Einträge für Schüler id={test_student_id}.")
            if scoped_entries:
                uuids_found = {e.get("studentId") for e in scoped_entries}
                print(f"-> Darin vorkommende studentId-UUIDs: {uuids_found}")
                print(f"-> Genau eine UUID für den einen angefragten Schüler? {len(uuids_found) == 1}")
                if example_pair and example_pair[0] == test_student_id:
                    print(
                        f"-> Abgleich gegen Abschnitt 8 (per Namensabgleich ermittelte UUID "
                        f"{example_pair[1]!r} für denselben Schüler): "
                        f"{'UEBEREINSTIMMUNG' if example_pair[1] in uuids_found else 'KEINE UEBEREINSTIMMUNG'}"
                    )
                print(json.dumps(redact(scoped_entries[0]), indent=2, ensure_ascii=False))
            else:
                print(
                    "-> Keine Fehlzeiten-Einträge für diesen Schüler im Testzeitraum - "
                    "Prüfung mit einem anderen Schüler wiederholen, der im Zeitraum sicher "
                    "Fehlzeiten hat, falls möglich."
                )

        section("13) Neu - Gibt es eine direkte UUID<->Integer-ID-Umwandlung für Schüler?")
        print(
            "Der element-Filter wird von getTimetableWithAbsences ignoriert (Abschnitt 12) - "
            "letzter Versuch, die studentId-UUID ohne Namensabgleich auf getStudents.id "
            "zurückzuführen: unbekannte RPC-Methodennamen sowie reverse getStudents-Filter."
        )
        known_uuid = example_pair[1] if example_pair else None
        known_int_id = example_pair[0] if example_pair else None
        print(f"Bekanntes Paar aus Abschnitt 8 zum Gegenprüfen: id={known_int_id} <-> uuid={known_uuid!r}")

        method_candidates = [
            ("getPersonId", {"id": known_int_id, "type": 5}),
            ("getPersonsId", {"id": known_int_id, "type": 5}),
            ("convertPersonId", {"id": known_int_id}),
            ("getStudentPersonId", {"studentId": known_int_id}),
            ("getPersonIdForStudent", {"studentId": known_int_id}),
            ("getUuidForStudent", {"id": known_int_id}),
            ("getPerson", {"id": known_int_id, "type": 5}),
            ("getPersonData", {"id": known_int_id, "type": 5}),
        ]
        for method, params in method_candidates:
            result, error = rpc_call(client, session_id, method, params)
            if error:
                print(f"{method}({params}): FEHLER {error.get('message', error)}")
            else:
                print(f"{method}({params}): ERFOLG -> {json.dumps(redact(result), indent=2, ensure_ascii=False)[:800]}")

        if known_uuid:
            print("\nReverse-Versuch: getStudents mit der bekannten UUID als Filterwert:")
            for param_key in ("personId", "studentId", "id", "key", "uuid"):
                result, error = rpc_call(client, session_id, "getStudents", {param_key: known_uuid})
                if error:
                    print(f"getStudents({{'{param_key}': uuid}}): FEHLER {error.get('message', error)}")
                else:
                    count = len(result) if result else 0
                    print(f"getStudents({{'{param_key}': uuid}}): {count} Schüler zurück")
                    if result and count <= 3:
                        print(json.dumps(redact(result[0]), indent=2, ensure_ascii=False))

        section("14) Neu - studentId als direkter Parameter + Inhalt des 'user'-Felds")
        known_uuid = example_pair[1] if example_pair else None
        print("14a) getTimetableWithAbsences mit studentId direkt als Options-Feld (statt element):")
        if known_uuid:
            for param_variant in (
                {"studentId": known_uuid, "startDate": start_int, "endDate": end_int},
                {"options": {"studentId": known_uuid, "startDate": start_int, "endDate": end_int}},
                {"student": {"id": known_uuid}, "startDate": start_int, "endDate": end_int},
            ):
                result, error = rpc_call(client, session_id, "getTimetableWithAbsences", param_variant)
                if error:
                    print(f"getTimetableWithAbsences({param_variant}): FEHLER {error.get('message', error)}")
                else:
                    scoped = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result
                    count = len(scoped) if scoped else 0
                    uuids = {e.get("studentId") for e in scoped} if scoped else set()
                    print(
                        f"getTimetableWithAbsences({param_variant}): {count} Einträge, "
                        f"{len(uuids)} unterschiedliche UUID(s) darin: {uuids if len(uuids) <= 3 else '(zu viele, ungescoped)'}"
                    )
        else:
            print("Kein bekanntes UUID-Beispiel vorhanden - übersprungen.")

        print("\n14b) Was steht im 'user'-Feld der Fehlzeiten-Einträge?")
        if entries:
            user_values = [e.get("user") for e in entries if e.get("user")]
            distinct_users = set(user_values)
            print(f"{len(user_values)} von {len(entries)} Einträgen haben ein nicht-leeres 'user'-Feld.")
            print(f"Anzahl unterschiedlicher Werte: {len(distinct_users)}")
            print(f"Beispielwerte (redigiert falls namensartig): {redact(list(distinct_users)[:10], key='user')}")
            entries_with_group = [e for e in entries if e.get("studentGroup")]
            print(
                f"\n{len(entries_with_group)} von {len(entries)} Einträgen haben ein nicht-leeres "
                f"'studentGroup'-Feld (Beispiel 12 hatte null)."
            )
            if entries_with_group:
                print(json.dumps(redact(entries_with_group[0]), indent=2, ensure_ascii=False))
        else:
            print("Keine Fehlzeiten-Einträge im Testzeitraum - Prüfung nicht möglich.")

        section("Logout")
        rpc_call(client, session_id, "logout", {})
        print("Fertig. Bitte die komplette Ausgabe oben zurückmelden.")


if __name__ == "__main__":
    main()
