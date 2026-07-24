# Backend: WebUntis-Sync-Job — Design

Stand: 2026-07-24. Aufbauend auf dem fertigen Backend-Grundgerüst (`docs/superpowers/plans/2026-07-24-backend-grundgeruest.md`, "Plan 1"). Dies ist "Plan 2". Referenz für alle Feldnamen/Endpunkte: [TECH-SPEC.md](../../../TECH-SPEC.md) Abschnitt 1, 2.1, 6; [SPECS.md](../../../SPECS.md) Abschnitt 4, 5.1.

## Ziel

Ein WebUntis-Sync-Job, der Klassen, Klassenbuch-Kategorien, Schüler (inkl. Klassenzuordnung), Fehlzeiten und Klassenbucheinträge aus WebUntis in die lokale Datenbank zieht — regelmäßig nach konfigurierbarem Intervall sowie über eine nächtliche Klassenzuordnungs-Refresh-Batch. Reiner Daten-Sync; keine Schwellwert-Prüfung, keine Benachrichtigungen (das ist ein späterer Plan, siehe "Nicht-Ziele" unten).

## Scope-Einordnung

Vier Subsysteme, in einem Plan mit vier Phasen umgesetzt (nicht als separate Pläne, um Overhead klein zu halten — Entscheidung im Brainstorming):

1. **JSON-RPC-Client + Klassen/Kategorie-Sync** — risikoarm, keine Abhängigkeiten.
2. **Schüler-Sync + Klassenzuordnung** — harte Voraussetzung für Phase 3 (Namensabgleich).
3. **Fehlzeiten- + Klassenbuch-Sync** — braucht den Schüler-Cache aus Phase 2.
4. **Orchestrierung** — Gesamtlauf, Retry, Scheduler, Schuljahr-Erkennung.

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
    schueler_roster.py             # SchuelerRosterProvider-Protokoll + JsonRpcSchuelerRosterProvider (Phase 2)
    webuntis_schueler_sync.py      # getStudents → schueler + Klassenzuordnungs-Batch (Phase 2)
    webuntis_fehlzeit_sync.py      # getTimetableWithAbsences → fehlzeit (Phase 3)
    webuntis_klassenbuch_sync.py   # getClassregEvents → klassenbuch_eintrag (Phase 3)
    sync_orchestrator.py           # run_full_sync(), run_klassenzuordnung_refresh() (Phase 4)
  core/
    scheduler.py               # APScheduler-Setup, Lifespan-Integration (Phase 4)
```

Jede `*_sync`-Funktion nimmt einen offenen `WebUntisClient` und eine `AsyncSession` entgegen und ist einzeln aufrufbar/testbar; der Orchestrator verkettet sie nur. Entspricht dem bestehenden Muster von `app/services/nutzer_klasse_sync.py` (nimmt nur `db: AsyncSession`).

**Upsert-Muster (einheitlich für alle Sync-Funktionen in diesem Plan):** bestehende Zeilen per `SELECT` über den jeweiligen Unique-Key laden, in Python gegen die WebUntis-Antwort abgleichen, geänderte Felder auf dem geladenen ORM-Objekt setzen (kein raw `ON CONFLICT`) und für neue Keys neue Objekte anlegen. Kein Delete-then-Insert wie bei `nutzer_klasse_sync` — dort ist Vollständig-Neuschreiben sinnvoll, weil die Zielmenge pro Klasse klein ist; hier würde Löschen historische Zeilen (z.B. `fehlzeit`) unnötig anfassen.

**Neue Env-Vars** (`.env.example`, `app/core/config.py`):
- `WEBUNTIS_SERVER`, `WEBUNTIS_SCHOOL`, `WEBUNTIS_USERNAME`, `WEBUNTIS_PASSWORD`
- `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` (Default `30`)
- `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS` (Default `4`)
- `WEBUNTIS_KLASSENZUORDNUNG_CONCURRENCY` (Default `5`)
- `WEBUNTIS_KLASSENZUORDNUNG_REFRESH_TAGE` (Default `7`)

**Neue Dependencies:** `apscheduler` (Produktivcode). `respx` (nur `requirements-dev.txt`, HTTP-Mocking für Tests).

**Neues DB-Feld:** `einstellung.letzter_sync_am` (`DateTime`, nullable) — Zeitpunkt des letzten vollständig erfolgreichen Sync-Laufs, Basis für den inkrementellen Fehlzeiten-/Klassenbuch-Abfragezeitraum (siehe Phase 3). Migration erforderlich.

## Phase 1: WebUntis-Client, Klassen- & Kategorie-Sync

**`WebUntisClient`** (`app/integrations/webuntis_client.py`): async Context-Manager um `httpx.AsyncClient`. Kapselt:
- `authenticate()`: JSON-RPC `authenticate` mit `WEBUNTIS_USERNAME`/`_PASSWORD`, liefert Session-ID, wird als `JSESSIONID`-Cookie gehalten.
- `call(method, params)`: führt den JSON-RPC-Call aus; bei `error.code == -8520` (Session Expired) einmalig `authenticate()` erneut + Request wiederholen. Kein Session-Caching über Sync-Läufe hinweg — jeder Lauf loggt sich frisch ein und am Ende aus (`logout`-RPC-Methode im `__aexit__`).
- Instanziierung pro Sync-Lauf: `async with WebUntisClient(settings) as client: ...`.

**`webuntis_klassen_sync.sync_klassen(client, db)`:** `getKlassen` → Upsert nach `klasse.webuntis_id` (Felder: `name`, `webuntis_teacher1_id`=`teacher1`, `webuntis_teacher2_id`=`teacher2`; `stufe`/`schulart` bleiben `NULL`, da WebUntis dafür keine bestätigten Quellfelder liefert). Danach `seed_nutzer_klasse_from_webuntis(db)` (bereits vorhanden, unverändert) aufrufen.

**`webuntis_kategorie_sync.sync_kategorien(client, db)`:** `getClassregCategories` + `getClassregCategoryGroups` → Upsert nach `classreg_category.webuntis_id`/`name` (`name`, `long_name`, `group_name`).

## Phase 2: Schüler-Sync & Klassenzuordnung

**`SchuelerRosterProvider`** (`app/services/schueler_roster.py`): `Protocol` mit einer Methode, die für den aktuellen Lauf eine Liste `RosterEntry {vorname, nachname, klasse_name, aktiv}` liefert (TECH-SPEC 1.3 — bewusst `klasse_name` statt `klasse_id` für spätere Austauschbarkeit gegen die Untis Platform API).

**`JsonRpcSchuelerRosterProvider`:** kapselt `getStudents({})` + pro neuem Schüler `getTimetable(options.element={id, type: 5}, startDate, endDate)` (Zeitraum: aktuelles Schuljahr, aus `getCurrentSchoolyear` — siehe Phase 4). Häufigste `kl.id` aus den Timetable-Perioden wird zu `klasse_name` aufgelöst (gegen den lokalen `klasse`-Cache aus Phase 1 per `webuntis_id`). Nebenläufigkeit über `WEBUNTIS_KLASSENZUORDNUNG_CONCURRENCY` (Default 5, `asyncio.Semaphore`).

**`webuntis_schueler_sync.sync_neue_schueler(client, db)`** (Teil des Haupt-Sync-Laufs, Phase 4):
1. `getStudents({})` → `webuntis_id`s, die noch nicht in `schueler` existieren, werden angelegt (`webuntis_key`, `vorname`, `nachname`; `klasse_id=NULL`, `aktiv=false`).
2. Für jeden neu angelegten Schüler sofort über `JsonRpcSchuelerRosterProvider` klassifizieren: `klasse_name` → `klasse_id` (per `klasse.name`-Abgleich), `aktiv=true`, `klassenzuordnung_aktualisiert_am=jetzt`. Kein Treffer im Timetable (Schüler ohne Unterrichtsstunden) ⇒ bleibt `aktiv=false`, `klasse_id=NULL`.

**`webuntis_schueler_sync.refresh_klassenzuordnung(client, db)`** (nächtlicher Batch, Phase 4, separat eingeplant):
- Wählt `schueler` mit `aktiv=true` und `klassenzuordnung_aktualisiert_am` älter als `WEBUNTIS_KLASSENZUORDNUNG_REFRESH_TAGE` (Default 7).
- Klassifiziert diese neu (gleiche Logik wie oben, gleiche Concurrency-Begrenzung).

## Phase 3: Fehlzeiten- & Klassenbuch-Sync

Zeitraum für beide: `von = einstellung.letzter_sync_am` (minus 1 Tag Overlap-Puffer für nachträgliche WebUntis-Änderungen) `bis heute`; ist `letzter_sync_am` `NULL` (allererster Lauf), `von = einstellung.schuljahr_start_cache` bzw. `getCurrentSchoolyear().startDate`, falls Cache noch leer (initialer Import, SPECS.md 5.1).

**`webuntis_fehlzeit_sync.sync_fehlzeiten(client, db, von, bis)`:**
- `getTimetableWithAbsences(von, bis)` → pro Eintrag in `periodsWithAbsences[]`:
  - `typ = "stunde"` wenn `subjectId` gesetzt, sonst `"tag"`.
  - `invalid == true` ⇒ überspringen.
  - `studentId` (UUID-String) → `schueler_id`: Namensabgleich (normalisiert: lowercase, whitespace-getrimmt) gegen `schueler.vorname`/`nachname` aus dem lokalen Cache. Kein Treffer ⇒ Log (`logging.warning`) + Eintrag überspringen (holt sich beim nächsten Lauf, sobald der Schüler lokal existiert).
  - `excuseStatus`-String → `excuse_status_id`: Namensabgleich gegen `excuse_status.name`. Kein Treffer ⇒ `NULL`.
  - `absenceReason` → `grund_text`; `fach = subjectId` (nur bei `typ="stunde"` — laut TECH-SPEC 1.2 ist `subjectId` selbst bereits der Fachname-String, z.B. `"Deutsch"`, kein numerischer Fremdschlüssel, also keine zusätzliche Auflösung nötig).
  - Upsert (siehe Upsert-Muster oben) über bestehenden Unique-Constraint (`schueler_id`, `datum`, `start_zeit`, `end_zeit`, `typ`).

**`webuntis_klassenbuch_sync.sync_klassenbuch(client, db, von, bis)`:**
- `getClassregEvents(von, bis)` → pro Eintrag: Upsert nach `klassenbuch_eintrag.webuntis_id` (=`eventId`). `studentid` → `schueler_id` per Namensabgleich (wie oben). `subject`-Kürzel → `kategorie_id` per `classreg_category.name`, kein Treffer ⇒ Log + überspringen (Kategorie sollte durch Phase 1 immer vorhanden sein — Datenintegritätsproblem, wenn nicht). `text` → `text`, `lessonId` → `lesson_id`, `createTeacher.id`/`updateTeacher.id` → `erstellt_von_teacher_id`/`geaendert_von_teacher_id`.

## Phase 4: Orchestrierung

**`sync_orchestrator.run_full_sync(db)`:**
1. `async with WebUntisClient(settings) as client:`
2. Phase 1: `sync_klassen`, `sync_kategorien`
3. Phase 2 (nur neue Schüler): `sync_neue_schueler`
4. `getCurrentSchoolyear()` → falls `startDate != einstellung.schuljahr_start_cache`: Cache aktualisieren (reine Aktualisierung, kein Zähler-Reset — das ist Plan 3, TECH-SPEC 1.3a/SPECS.md 5).
5. Zeitraum für Phase 3 bestimmen (siehe oben), `sync_fehlzeiten`, `sync_klassenbuch`.
6. Bei vollständigem Erfolg: `einstellung.letzter_sync_am = jetzt`; falls `initialer_import_abgeschlossen == false`: auf `true` setzen (TECH-SPEC 1.3b — Datengrundlage für die künftige Eskalations-Engine, wird von dieser noch nicht gelesen). Ein `db.commit()`.
7. Bei Fehler in irgendeinem Schritt: `db.rollback()` (kein Teil-Commit dieses Versuchs), Fehler loggen, nach `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` erneuter Versuch (derselbe Ablauf von vorn), bis `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS` erreicht ist; danach Abbruch + Log, nächster regulärer Cron-Termin läuft unabhängig weiter (TECH-SPEC 1.3b).

**`sync_orchestrator.run_klassenzuordnung_refresh(db)`:** ruft `webuntis_schueler_sync.refresh_klassenzuordnung` in einem eigenen `WebUntisClient`-Context auf. Kein Retry-Mechanismus wie bei `run_full_sync` — schlägt der nächtliche Lauf fehl, greift er in der nächsten Nacht erneut (kein SLA-kritischer Pfad, da bereits aktive Schüler betroffen sind, nicht neue).

**`app/core/scheduler.py`:** APScheduler (`AsyncIOScheduler`), im FastAPI-Lifespan-Hook gestartet/gestoppt. Zwei Jobs:
- Haupt-Sync: liest `einstellung.sync_interval_cron` bei jedem Reschedule frisch aus der DB (Trigger wird nach jedem Lauf-Ende neu mit dem aktuellen Cron-Wert gesetzt — Admin-Änderungen wirken ab dem nächsten Lauf, kein Neustart nötig).
- Klassenzuordnungs-Refresh: fester Cron `0 2 * * *` (02:00 nachts), kein DB-Setting.

## Fehlerbehandlung, Retry, Logging

Retry-Einheit ist der gesamte `run_full_sync`-Lauf (nicht einzelne Phasen), wie TECH-SPEC 1.3b beschreibt. Alle WebUntis-Fehler außer `-8520` (intern im Client behandelt) brechen den aktuellen Versuch ab. Kein eigenes DB-Log für Sync-Läufe — `audit_log` ist für Nutzeraktionen gedacht (siehe TECH-SPEC Abschnitt 2), Sync-Lauf-Historie läuft über Python-`logging`. Das ist bewusst minimal; ein UI-sichtbares Sync-Status-Log wäre neuer Scope und nicht durch SPECS.md/TECH-SPEC.md gefordert.

## Testing-Strategie

- DB-Tests wie bisher gegen echte Test-Postgres (`tests/conftest.py`-Muster, kein DB-Mock).
- WebUntis-Calls: `respx` mockt `httpx`-Requests an die JSON-RPC-URL. Fixture-Payloads bilden exakt die in TECH-SPEC.md Abschnitt 1.2/1.3 dokumentierten realen Beispielstrukturen nach (u.a. `getKlassen` mit `teacher1`/`teacher2`, `getTimetableWithAbsences` mit Tag-/Stunden-Typ-Beispielen inkl. `invalid`, `-8520`-Fehlerantwort für den Re-Auth-Test, `getClassregEvents` mit `eventId`/`createTeacher`).
- Kein Test gegen die echte WebUntis-Instanz (wie beim Spike in `scratchpad/webuntis_spike.py` — bleibt Ad-hoc-Handarbeit, kein CI-Bestandteil).

## Nicht-Ziele (bewusst außerhalb dieses Plans)

- `POST /admin/sync-now`-REST-Endpunkt (späterer Plan "Backend: REST-Endpunkte"; ruft dann `run_full_sync`/`run_klassenzuordnung_refresh` auf, die hier bereits als eigenständige Funktionen entstehen).
- Eskalations-Engine: Schwellwert-Prüfung, Zähler (`schueler_zaehlerstand`), Benachrichtigungen (`benachrichtigung`), Zähler-Reset bei Schuljahreswechsel, Maßnahmen/Ausnahmen. Das war in Plan 1 explizit als "bewusst nächster Plan" markiert — hier "Plan 3".
- `PlatformApiSchuelerRosterProvider` (erst bei Zugang zur Untis Platform API — die `SchuelerRosterProvider`-Abstraktion aus Phase 2 macht den späteren Austausch aber möglich, ohne Schema-Änderung).
- `excuse_status`-Pflege im Admin-Bereich (kein WebUntis-Sync möglich, siehe TECH-SPEC 1.2 — bleibt manuell, REST-Endpunkt dafür ist Teil des REST-Endpunkte-Plans).
