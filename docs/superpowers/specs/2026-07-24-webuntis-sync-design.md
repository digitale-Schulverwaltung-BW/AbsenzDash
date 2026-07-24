# Backend: WebUntis-Sync-Job — Design

Stand: 2026-07-24 (überarbeitet nach Live-Spike gegen die reale WebUntis-Instanz, siehe TECH-SPEC.md Abschnitt 1.3). Aufbauend auf dem fertigen Backend-Grundgerüst (`docs/superpowers/plans/2026-07-24-backend-grundgeruest.md`, "Plan 1"). Dies ist "Plan 2". Referenz für alle Feldnamen/Endpunkte: [TECH-SPEC.md](../../../TECH-SPEC.md) Abschnitt 1, 2, 2.1, 6; [SPECS.md](../../../SPECS.md) Abschnitt 4, 5.1.

## Ziel

Ein WebUntis-Sync-Job, der Klassen, Klassenbuch-Kategorien, Fehlzeiten und Klassenbucheinträge aus WebUntis in die lokale Datenbank zieht, sowie ein ASV-BW-CSV-Import, der Schüler-Stammdaten (Name, Klasse, Aktiv-Status) und die für Fehlzeiten-/Klassenbuch-Zuordnung nötige externe ID liefert — beides regelmäßig nach konfigurierbarem Intervall. Reiner Daten-Sync; keine Schwellwert-Prüfung, keine Benachrichtigungen (das ist ein späterer Plan, siehe "Nicht-Ziele" unten).

## Scope-Einordnung

Vier Subsysteme, in einem Plan mit vier Phasen umgesetzt (nicht als separate Pläne, um Overhead klein zu halten — Entscheidung im Brainstorming):

1. **JSON-RPC-Client + Klassen/Kategorie-Sync** — risikoarm, keine Abhängigkeiten.
2. **ASV-BW-CSV-Import (Schüler-Stammdaten & Klassenzuordnung)** — harte Voraussetzung für Phase 3 (liefert den Join-Key `externe_id`), braucht den `klasse`-Cache aus Phase 1 zur Klassennamens-Auflösung.
3. **Fehlzeiten- + Klassenbuch-Sync** — braucht den Schüler-Cache aus Phase 2.
4. **Orchestrierung** — Gesamtlauf, Retry, Scheduler, Schuljahr-Erkennung.

**Design-Historie:** Phase 2 war ursprünglich als `getStudents`+`getTimetable(type=5)`-Batch geplant (siehe erste Fassung dieses Dokuments in der Git-Historie). Live-Tests gegen die reale Instanz (`scratchpad/webuntis_spike.py`, Abschnitte 11–14) zeigten, dass `getTimetableWithAbsences`-Einträge kein Namensfeld tragen und keinen Element-Scoping-Parameter akzeptieren — die WebUntis-API allein bot keinen verlässlichen, lückenfreien Weg, Fehlzeiten-Einträge einzelnen Schülern zuzuordnen. Der ASV-BW-CSV-Import (TECH-SPEC.md Abschnitt 1.3) löst das direkt: seine `externe_id`-Spalte ist identisch mit der `studentId`-UUID in Fehlzeiten/Klassenbuch.

## Architektur & Modulstruktur

Neue Module in `backend/app/`:

```
app/
  integrations/
    __init__.py
    webuntis_client.py        # WebUntisClient (Phase 1)
  services/
    webuntis_klassen_sync.py       # getKlassen → klasse, ruft seed_nutzer_klasse_from_webuntis (Phase 1)
    webuntis_kategorie_sync.py     # getClassregCategories/-Groups → classreg_category (Phase 1)
    asv_csv_import.py              # ASV-BW-CSV → schueler (Phase 2)
    webuntis_fehlzeit_sync.py      # getTimetableWithAbsences → fehlzeit (Phase 3)
    webuntis_klassenbuch_sync.py   # getClassregEvents → klassenbuch_eintrag (Phase 3)
    sync_orchestrator.py           # run_full_sync() (Phase 4)
  core/
    scheduler.py               # APScheduler-Setup, Lifespan-Integration (Phase 4)
```

Jede `*_sync`-Funktion nimmt einen offenen `WebUntisClient` und eine `AsyncSession` entgegen und ist einzeln aufrufbar/testbar; der Orchestrator verkettet sie nur. `asv_csv_import` braucht keinen `WebUntisClient` (reine Dateiverarbeitung), nur `db`. Entspricht dem bestehenden Muster von `app/services/nutzer_klasse_sync.py` (nimmt nur `db: AsyncSession`).

**Upsert-Muster (einheitlich für alle Sync-Funktionen in diesem Plan):** bestehende Zeilen per `SELECT` über den jeweiligen Unique-Key laden, in Python gegen die WebUntis-/CSV-Antwort abgleichen, geänderte Felder auf dem geladenen ORM-Objekt setzen (kein raw `ON CONFLICT`) und für neue Keys neue Objekte anlegen. Kein Delete-then-Insert wie bei `nutzer_klasse_sync` — dort ist Vollständig-Neuschreiben sinnvoll, weil die Zielmenge pro Klasse klein ist; hier würde Löschen historische Zeilen (z.B. `fehlzeit`) unnötig anfassen.

**Neue Env-Vars** (`.env.example`, `app/core/config.py`):
- `WEBUNTIS_SERVER`, `WEBUNTIS_SCHOOL`, `WEBUNTIS_USERNAME`, `WEBUNTIS_PASSWORD`
- `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` (Default `30`)
- `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS` (Default `4`)
- `ASV_CSV_PATH` (Pfad zur live-gemounteten CSV-Datei, kein Default — Pflichtangabe)
- `ASV_CSV_COLUMN_EXTERNE_ID` (Default `idnumber`), `ASV_CSV_COLUMN_VORNAME` (Default `firstname`), `ASV_CSV_COLUMN_NACHNAME` (Default `lastname`), `ASV_CSV_COLUMN_KLASSE` (Default `Klasse`), `ASV_CSV_COLUMN_EINTRITTSDATUM` (Default `Eintrittsdatum`), `ASV_CSV_COLUMN_AUSTRITTSDATUM` (Default `Austrittsdatum`) — Spaltennamen sind schulspezifisch (TECH-SPEC.md Abschnitt 1.3), Defaults passen zur Referenzschule.

**Neue Dependencies:** `apscheduler` (Produktivcode). `respx` (nur `requirements-dev.txt`, HTTP-Mocking für Tests). Für den CSV-Import genügt Pythons eingebautes `csv`-Modul (`;`-Delimiter, Standard-Quoting — keine zusätzliche Dependency nötig).

**DB-Migration nötig:**
- `einstellung.letzter_sync_am` (`DateTime`, nullable) — Zeitpunkt des letzten vollständig erfolgreichen Sync-Laufs, Basis für den inkrementellen Fehlzeiten-/Klassenbuch-Abfragezeitraum (Phase 3).
- `einstellung.asv_csv_zuletzt_importiert_mtime` (`DateTime`, nullable) — mtime der zuletzt verarbeiteten CSV-Datei; unverändert ⇒ Import überspringen (Phase 2).
- `schueler.externe_id` (`String`, unique, not null) — neu, ersetzt die bisherigen `schueler.webuntis_id`/`webuntis_key`-Felder aus Plan 1 (werden in derselben Migration entfernt — beide waren aus `getStudents` gedacht, das in diesem Plan nicht mehr aufgerufen wird, siehe Phase 2).

## Phase 1: WebUntis-Client, Klassen- & Kategorie-Sync

**`WebUntisClient`** (`app/integrations/webuntis_client.py`): async Context-Manager um `httpx.AsyncClient`. Kapselt:
- `authenticate()`: JSON-RPC `authenticate` mit `WEBUNTIS_USERNAME`/`_PASSWORD`, liefert Session-ID, wird als `JSESSIONID`-Cookie gehalten.
- `call(method, params)`: führt den JSON-RPC-Call aus; bei `error.code == -8520` (Session Expired) einmalig `authenticate()` erneut + Request wiederholen. Kein Session-Caching über Sync-Läufe hinweg — jeder Lauf loggt sich frisch ein und am Ende aus (`logout`-RPC-Methode im `__aexit__`).
- Instanziierung pro Sync-Lauf: `async with WebUntisClient(settings) as client: ...`.

**`webuntis_klassen_sync.sync_klassen(client, db)`:** `getKlassen` → Upsert nach `klasse.webuntis_id` (Felder: `name`, `webuntis_teacher1_id`=`teacher1`, `webuntis_teacher2_id`=`teacher2`; `stufe`/`schulart` bleiben `NULL`, da WebUntis dafür keine bestätigten Quellfelder liefert). Danach `seed_nutzer_klasse_from_webuntis(db)` (bereits vorhanden, unverändert) aufrufen.

**`webuntis_kategorie_sync.sync_kategorien(client, db)`:** `getClassregCategories` + `getClassregCategoryGroups` → Upsert nach `classreg_category.webuntis_id`/`name` (`name`, `long_name`, `group_name`).

## Phase 2: ASV-BW-CSV-Import (Schüler-Stammdaten & Klassenzuordnung)

**`asv_csv_import.import_schueler(db)`** (kein `WebUntisClient` nötig):

1. `mtime = os.path.getmtime(settings.asv_csv_path)`. Ist `mtime <= einstellung.asv_csv_zuletzt_importiert_mtime` (und dieses Feld nicht `NULL`): sofort zurückkehren, nichts tun (TECH-SPEC.md Abschnitt 1.3 — >2000 Zeilen bei dieser Schule, unnötiges Neuverarbeiten bei jedem Sync-Takt vermeiden).
2. Datei mit `csv.DictReader` einlesen (`delimiter=";"`, UTF-8; Spaltennamen aus den `ASV_CSV_COLUMN_*`-Settings). Pro Zeile:
   - `externe_id = row[settings.asv_csv_column_externe_id]`.
   - `vorname = row[settings.asv_csv_column_vorname]`, `nachname = row[settings.asv_csv_column_nachname]`.
   - `klasse_name = row[settings.asv_csv_column_klasse]` → `klasse_id` per `SELECT klasse.id WHERE klasse.name == klasse_name` (Cache aus Phase 1). Kein Treffer ⇒ `klasse_id = NULL`, `logging.warning`.
   - `eintrittsdatum`/`austrittsdatum` mit `datetime.strptime(wert, "%d.%m.%Y").date()` geparst (leerer Wert bei `austrittsdatum` ⇒ `None`, kein Enddatum). `aktiv = eintrittsdatum <= heute and (austrittsdatum is None or austrittsdatum >= heute)`.
   - Upsert (siehe Upsert-Muster oben) nach `schueler.externe_id`: `vorname`, `nachname`, `klasse_id`, `aktiv`, `klassenzuordnung_aktualisiert_am = jetzt` setzen.
3. `einstellung.asv_csv_zuletzt_importiert_mtime = mtime`, ein `db.commit()`.

`email`, `birthday`, `login`, `shortname`, `volljaehrig` aus der CSV werden nicht übernommen (keine fachliche Notwendigkeit, YAGNI — TECH-SPEC.md Abschnitt 1.3).

## Phase 3: Fehlzeiten- & Klassenbuch-Sync

Zeitraum für beide: `von = einstellung.letzter_sync_am` (minus 1 Tag Overlap-Puffer für nachträgliche WebUntis-Änderungen) `bis heute`; ist `letzter_sync_am` `NULL` (allererster Lauf), `von = einstellung.schuljahr_start_cache` bzw. `getCurrentSchoolyear().startDate`, falls Cache noch leer (initialer Import, SPECS.md 5.1).

**`webuntis_fehlzeit_sync.sync_fehlzeiten(client, db, von, bis)`:**
- `getTimetableWithAbsences(von, bis)` → pro Eintrag in `periodsWithAbsences[]`:
  - `typ = "stunde"` wenn `subjectId` gesetzt, sonst `"tag"`.
  - `invalid == true` ⇒ überspringen.
  - `studentId` (UUID-String) → `schueler_id`: direkter Gleichheits-Lookup `SELECT schueler.id WHERE schueler.externe_id == studentId` (TECH-SPEC.md Abschnitt 1.3 — kein Namensabgleich mehr nötig, `externe_id` ist exakt dieselbe UUID). Kein Treffer ⇒ Log (`logging.warning`) + Eintrag überspringen (Schüler evtl. noch nicht im ASV-BW-Export oder verlassen — holt sich beim nächsten Lauf, sobald vorhanden).
  - `excuseStatus`-String → `excuse_status_id`: Namensabgleich gegen `excuse_status.name` (das bleibt Namensabgleich — `excuse_status` ist eine kleine, manuell gepflegte Stammdaten-Tabelle ohne UUID, TECH-SPEC.md Abschnitt 1.2). Kein Treffer ⇒ `NULL`.
  - `absenceReason` → `grund_text`; `fach = subjectId` (nur bei `typ="stunde"` — laut TECH-SPEC 1.2 ist `subjectId` selbst bereits der Fachname-String, z.B. `"Deutsch"`, kein numerischer Fremdschlüssel, also keine zusätzliche Auflösung nötig).
  - Upsert (siehe Upsert-Muster oben) über bestehenden Unique-Constraint (`schueler_id`, `datum`, `start_zeit`, `end_zeit`, `typ`).

**`webuntis_klassenbuch_sync.sync_klassenbuch(client, db, von, bis)`:**
- `getClassregEvents(von, bis)` → pro Eintrag: Upsert nach `klassenbuch_eintrag.webuntis_id` (=`eventId`). `studentid` → `schueler_id` per direktem `externe_id`-Gleichheits-Lookup (wie oben). `subject`-Kürzel → `kategorie_id` per `classreg_category.name`, kein Treffer ⇒ Log + überspringen (Kategorie sollte durch Phase 1 immer vorhanden sein — Datenintegritätsproblem, wenn nicht). `text` → `text`, `lessonId` → `lesson_id`, `createTeacher.id`/`updateTeacher.id` → `erstellt_von_teacher_id`/`geaendert_von_teacher_id`.

## Phase 4: Orchestrierung

**`sync_orchestrator.run_full_sync(db)`:**
1. `async with WebUntisClient(settings) as client:`
2. Phase 1: `sync_klassen`, `sync_kategorien`.
3. Phase 2: `asv_csv_import.import_schueler(db)` (kein WebUntis-Aufruf, aber im selben transaktionalen Lauf — braucht den `klasse`-Cache aus Schritt 2; mtime-Check macht wiederholte Aufrufe günstig).
4. `getCurrentSchoolyear()` → falls `startDate != einstellung.schuljahr_start_cache`: Cache aktualisieren (reine Aktualisierung, kein Zähler-Reset — das ist Plan 3, TECH-SPEC 1.3a/SPECS.md 5).
5. Zeitraum für Phase 3 bestimmen (siehe oben), `sync_fehlzeiten`, `sync_klassenbuch`.
6. Bei vollständigem Erfolg: `einstellung.letzter_sync_am = jetzt`; falls `initialer_import_abgeschlossen == false`: auf `true` setzen (TECH-SPEC 1.3b — Datengrundlage für die künftige Eskalations-Engine, wird von dieser noch nicht gelesen). Ein `db.commit()`.
7. Bei Fehler in irgendeinem Schritt (WebUntis-Fehler oder CSV-Lesefehler, z.B. Datei fehlt/kaputt): `db.rollback()` (kein Teil-Commit dieses Versuchs), Fehler loggen, nach `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` erneuter Versuch (derselbe Ablauf von vorn), bis `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS` erreicht ist; danach Abbruch + Log, nächster regulärer Cron-Termin läuft unabhängig weiter (TECH-SPEC 1.3b).

**`app/core/scheduler.py`:** APScheduler (`AsyncIOScheduler`), im FastAPI-Lifespan-Hook gestartet/gestoppt. **Ein** Job (Haupt-Sync — die früher separate nächtliche Klassenzuordnungs-Refresh-Batch entfällt ersatzlos, da Phase 2 jetzt bei jedem regulären Lauf mitläuft, siehe TECH-SPEC.md Abschnitt 1.3): liest `einstellung.sync_interval_cron` bei jedem Reschedule frisch aus der DB (Trigger wird nach jedem Lauf-Ende neu mit dem aktuellen Cron-Wert gesetzt — Admin-Änderungen wirken ab dem nächsten Lauf, kein Neustart nötig).

## Fehlerbehandlung, Retry, Logging

Retry-Einheit ist der gesamte `run_full_sync`-Lauf (nicht einzelne Phasen), wie TECH-SPEC 1.3b beschreibt. Alle WebUntis-Fehler außer `-8520` (intern im Client behandelt) sowie CSV-Lesefehler brechen den aktuellen Versuch ab. Kein eigenes DB-Log für Sync-Läufe — `audit_log` ist für Nutzeraktionen gedacht (siehe TECH-SPEC Abschnitt 2), Sync-Lauf-Historie läuft über Python-`logging`. Das ist bewusst minimal; ein UI-sichtbares Sync-Status-Log wäre neuer Scope und nicht durch SPECS.md/TECH-SPEC.md gefordert.

## Testing-Strategie

- DB-Tests wie bisher gegen echte Test-Postgres (`tests/conftest.py`-Muster, kein DB-Mock).
- WebUntis-Calls: `respx` mockt `httpx`-Requests an die JSON-RPC-URL. Fixture-Payloads bilden exakt die in TECH-SPEC.md Abschnitt 1.2 dokumentierten realen Beispielstrukturen nach (u.a. `getKlassen` mit `teacher1`/`teacher2`, `getTimetableWithAbsences` mit Tag-/Stunden-Typ-Beispielen inkl. `invalid`, `-8520`-Fehlerantwort für den Re-Auth-Test, `getClassregEvents` mit `eventId`/`createTeacher`).
- CSV-Import-Tests: temporäre CSV-Datei (`tmp_path`-Pytest-Fixture) mit Beispielzeilen im bestätigten Format (TECH-SPEC.md Abschnitt 1.3), gegen `settings.asv_csv_path` gepatcht (`monkeypatch`, analog dem bestehenden Muster in `tests/test_deps_wordpress_proxy.py` für `settings.wordpress_proxy_secret`).
- Kein Test gegen die echte WebUntis-Instanz (wie beim Spike in `scratchpad/webuntis_spike.py` — bleibt Ad-hoc-Handarbeit, kein CI-Bestandteil).

## Nicht-Ziele (bewusst außerhalb dieses Plans)

- `POST /admin/sync-now`-REST-Endpunkt (späterer Plan "Backend: REST-Endpunkte"; ruft dann `run_full_sync` auf, die hier bereits als eigenständige Funktion entsteht).
- Eskalations-Engine: Schwellwert-Prüfung, Zähler (`schueler_zaehlerstand`), Benachrichtigungen (`benachrichtigung`), Zähler-Reset bei Schuljahreswechsel, Maßnahmen/Ausnahmen. Das war in Plan 1 explizit als "bewusst nächster Plan" markiert — hier "Plan 3".
- Alternative Schüler-Datenquellen (z.B. Untis Platform API) — der CSV-Import ist bereits schul-unabhängig konfigurierbar (Spaltennamen per Env-Var), eine zusätzliche Abstraktionsebene ist ohne einen zweiten konkreten Anwendungsfall nicht gerechtfertigt (YAGNI, TECH-SPEC.md Abschnitt 1.3).
- `excuse_status`-Pflege im Admin-Bereich (kein WebUntis-Sync möglich, siehe TECH-SPEC 1.2 — bleibt manuell, REST-Endpunkt dafür ist Teil des REST-Endpunkte-Plans).
- Validierung/Fehlerbehandlung für strukturell fehlerhafte CSV-Zeilen über Logging hinaus (z.B. fehlende Pflichtspalte) — bei einem Parse-Fehler bricht der gesamte Sync-Lauf ab und wird gemäß der regulären Retry-Logik erneut versucht (kein Sonderfall nötig).
