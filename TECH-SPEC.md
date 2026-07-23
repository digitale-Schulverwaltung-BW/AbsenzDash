# AbsenzDash — Technische Spezifikation

Stand: 2026-07-23

Begleitdokument zu [SPECS.md](SPECS.md). Konkretisiert Datenmodell, API-Vertrag und WebUntis-Feldmapping auf Basis der Recherche im Referenzprojekt [VertretungsFlow](https://github.com/digitale-Schulverwaltung-BW/VertretungsFlow) (intern "AbsenzFlow" genannt) und der `python-webuntis`-Bibliothek. Weiterhin keine Implementierung — dieses Dokument liefert die Fakten, die ein späterer Umsetzungsplan (`writing-plans`) braucht, um ohne Platzhalter auszukommen.

## 1. WebUntis-Integration

### 1.1 Auth gegen WebUntis

Wie VertretungsFlow: eigener JSON-RPC-2.0-Client gegen `https://{server}/WebUntis/jsonrpc.do` (kein Drittanbieter-Package nötig, ca. 150 Zeilen). Service-Account-Login per `authenticate`-Methode (Username/Passwort aus `.env`), Session-ID wird als `JSESSIONID`-Cookie an Folge-Requests gehängt. Bei Session-Expiry (`error.code == -8520`) automatischer Re-Auth + Retry. Gleiches Muster wie VertretungsFlow (`WEBUNTIS_SERVER`, `WEBUNTIS_USERNAME`, `WEBUNTIS_PASSWORD` als Env-Vars).

### 1.2 Endpunkte & Feldmapping

**Klassen-Stammdaten (inkl. Klassenlehrkraft):** `getKlassen` (bereits von VertretungsFlow genutztes Muster für Stammdaten). Liefert Klassen-ID, Name, sowie Referenz(en) auf Lehrkraft — Feldname am Server zu verifizieren, da VertretungsFlow diese Response bisher nicht auf Klassenlehrkraft-Zuordnung hin ausgewertet hat (nutzt `getKlassen` nur für Namen/IDs). **Zu validieren:** ob `getKlassen` die Klassenlehrkraft direkt mitliefert oder ob dafür ein separater Aufruf (z.B. `getTeachers` + Zuordnung über `getKlassen`-Feld `teacher1`/`teacher2`) nötig ist.

**Fehlzeiten:** Zwei WebUntis-Schnittstellen kommen infrage, mit unterschiedlicher Feldqualität — **Entscheidung ist ein Validierungs-Risiko, siehe Abschnitt 5**:

| | Klassisch (JSON-RPC `getTimetableWithAbsences`) | Neuer (REST `/WebUntis/api/classreg/absences/students`) |
|---|---|---|
| Response-Root | `periodsWithAbsences[]` | flache Liste |
| Schüler-Referenz | `studentId` | `studentName` (kein ID-Feld dokumentiert) |
| Zeitraum | `date` + `startTime`/`endTime` | `startDate`/`endDate` + `startTime`/`endTime` |
| Entschuldigt-Status | `excuseStatus` (opaker String, keine feste Werteliste dokumentiert) | `isExcused` (Boolean) + `excuseStatus` |
| Wer hat entschuldigt | nicht verfügbar | verschachteltes `excuse`-Objekt: `{userId, username, excuseDate, text}` |
| Grund/Text | `absenceReason` (Freitext) | `reasonId` + `reason` + `text` |
| Dauer | `absentTime` (nur auf einem von mehreren Duplikat-Einträgen gesetzt, wenn Schüler mehrere gleichzeitige Lehrkraft-/Gruppeneinträge hat) | über `startTime`/`endTime` + `interruptions` |
| Bearbeitbar-Flag | nicht verfügbar | `canEdit` |
| Offizielle Doku | nein (Community-reverse-engineered) | nein (Community-reverse-engineered, "MobileNew"-API) |

Für den konfigurierbaren Fehlzeiten-Filter ("nur unentschuldigt / alle", siehe SPECS.md Abschnitt 4) ist ein sauberes Boolean deutlich robuster als ein unspezifizierter String — daher **Empfehlung: REST-Endpunkt für Fehlzeiten**, mit Fallback auf die klassische JSON-RPC-Methode, falls der REST-Endpunkt am Schul-Server nicht erreichbar/freigeschaltet ist (unterschiedliche Berechtigungen möglich).

**Klassenbucheinträge:** Nur über klassische JSON-RPC verfügbar (kein REST-Äquivalent gefunden):
- `getClassregEvents(startDate, endDate, [id, type])` → Liste von Einträgen mit Feldern: `studentid`, `surname`, `forname`, `reason`, `text` (Freitext-Notiz), `date`, `subject`, `categoryId`.
- `getClassregCategories()` → Kategorie-Stammdaten: `name`, `longName`, `groupId`.
- `getClassregCategoryGroups()` → Gruppen-Stammdaten: `name`.
- **Wichtig:** Kategorien (z.B. "Verspätung", "Fehlverhalten") sind schulspezifisch in WebUntis konfigurierte Laufzeit-Daten, kein festes API-Enum. AbsenzDash muss `getClassregCategories`/`getClassregCategoryGroups` beim Sync mit abrufen und lokal cachen (Tabelle `classreg_category`, siehe Abschnitt 2), damit Schwellwert-Regeln (SPECS.md Abschnitt 4) auf konkrete, an dieser Schule tatsächlich existierende Kategorien referenzieren können. Für "Verspätung" gibt es kein separates Minuten-/Dauer-Feld — falls benötigt, steckt das im Freitext `text`, nicht strukturiert.
- Erfordert laut Library-Docstring die WebUntis-Berechtigung "classregevents read for all" für den Service-Account.

## 2. Datenbank-Schema

PostgreSQL, SQLAlchemy 2.0-Style mit `Mapped[]`-Typannotationen (Verbesserung gegenüber VertretungsFlow, das den Legacy-`declarative_base()`-Stil ohne durchgängige Typisierung nutzt). Alembic-Migrationen von Anfang an real genutzt (VertretungsFlow hat Alembic nur als ungenutzte Dependency gelistet und pflegt Schema-Änderungen stattdessen über handgeschriebene, durchnummerierte SQL-Dateien ohne Down-Migration — das übernehmen wir bewusst **nicht**). Gemeinsame `TimestampMixin` (`created_at`, `updated_at`) für alle Tabellen, ebenfalls eine Verbesserung gegenüber VertretungsFlow, das dies pro Modell dupliziert.

| Tabelle                 | Wesentliche Felder                                                                                                                                                                                                                                                        | Bezug                                                                                                                                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `klasse`                | `webuntis_id` (unique), `name`, `stufe`, `schulart`                                                                                                                                                                                                                       | Cache aus `getKlassen`                                                                                                                                                                              |
| `bereich`               | `name`                                                                                                                                                                                                                                                                    | lokal, nicht aus WebUntis (SPECS.md Abschnitt 4)                                                                                                                                                    |
| `bereich_klasse` (m:n)  | `bereich_id`, `klasse_id`                                                                                                                                                                                                                                                 | Bereichsdefinition                                                                                                                                                                                  |
| `schueler`              | `webuntis_id` (unique), `vorname`, `nachname`, `klasse_id`                                                                                                                                                                                                                | Cache aus WebUntis                                                                                                                                                                                  |
| `fehlzeit`              | `webuntis_id` (unique, für Idempotenz beim Re-Sync), `schueler_id`, `start`, `ende`, `ist_entschuldigt` (bool, aus `isExcused`), `grund_text`, `dauer_einheit` (`tag`/`stunde`), `dauer_wert`                                                                             | Cache aus WebUntis-Absence-Endpunkt                                                                                                                                                                 |
| `klassenbuch_eintrag`   | `webuntis_id` (unique), `schueler_id`, `kategorie_id`, `datum`, `text`                                                                                                                                                                                                    | Cache aus `getClassregEvents`                                                                                                                                                                       |
| `classreg_category`     | `webuntis_id`, `name`, `long_name`, `group_name`                                                                                                                                                                                                                          | Cache aus `getClassregCategories`/`-CategoryGroups`                                                                                                                                                 |
| `schwellwert_regel`     | `typ` (`fehlzeiten`/`klassenbuch`), `geltungsbereich` (`schulweit`/`stufe`/`schulart`), `geltungswert` (nullable, z.B. Stufe-5-Wert)                                                                                                                                      | SPECS.md Abschnitt 4                                                                                                                                                                                |
| `schwellwert_stufe`     | `regel_id`, `stufe_nr`, `einheit` (`fehltage`/`fehlstunden`, nur bei Fehlzeiten-Regeln), `schwellenwert`, `fehlzeiten_filter` (`nur_unentschuldigt`/`alle`, nur bei Fehlzeiten-Regeln), `empfaenger_rollen` (Array: `klassenlehrkraft`\|`bereichsleiter`\|`schulleitung`) |                                                                                                                                                                                                     |
| `schueler_zaehlerstand` | `schueler_id`, `regel_id`, `aktueller_stand`, `erreichte_stufe_nr`, `letzter_reset_am`                                                                                                                                                                                    | pro Schüler+Regel geführter Eskalations-Zähler (SPECS.md Abschnitt 5)                                                                                                                               |
| `massnahmen_typ`        | `name`, `setzt_zaehler_zurueck` (bool), `betroffene_regel_ids` (Array)                                                                                                                                                                                                    | konfigurierbarer Katalog, Default-Set siehe SPECS.md Abschnitt 4                                                                                                                                    |
| `massnahme`             | `schueler_id`, `massnahmen_typ_id`, `datum`, `notiz`, `erfasst_von_user_id`                                                                                                                                                                                               |                                                                                                                                                                                                     |
| `ausnahme`              | `schueler_id`, `kategorie` (`fehlzeiten`/`klassenbuch`), `grund`, `gueltig_bis` (nullable), `aktiv` (bool)                                                                                                                                                                | SPECS.md Abschnitt 4                                                                                                                                                                                |
| `audit_log`             | `user_id`, `aktion`, `resource_typ`, `resource_id`, `details` (JSON), `zeitpunkt`                                                                                                                                                                                         | analog VertretungsFlow `audit.py`, aber als echte Tabelle statt Ad-hoc-Aufrufen ohne feste Struktur                                                                                                 |
| `nutzer`                | `wp_user_id`, `email`, `name`, `rolle` (`klassenlehrkraft`/`bereichsleiter`/`schulleitung`)                                                                                                                                                                               | get-or-create bei erstem Proxy-Request, analog VertretungsFlow                                                                                                                                      |
| `nutzer_klasse` (m:n)   | `nutzer_id`, `klasse_id`, `quelle` (`webuntis_seed`/`manuell`)                                                                                                                                                                                                            | löst SPECS.md Abschnitt 4 auf: WebUntis-geseedete + manuell im WP-Backend ergänzte Klassenlehrkraft-Zuordnungen in einer Tabelle, `quelle` unterscheidet Herkunft für Re-Sync-Verhalten (siehe 2.1) |
| `nutzer_bereich` (m:n)  | `nutzer_id`, `bereich_id`                                                                                                                                                                                                                                                 | Bereichsleiter-Zuordnung                                                                                                                                                                            |

### 2.1 Sync-Verhalten für `nutzer_klasse`

Beim WebUntis-Sync werden Zeilen mit `quelle = 'webuntis_seed'` für die betroffene Klasse gelöscht und aus der aktuellen `getKlassen`-Antwort neu geschrieben; Zeilen mit `quelle = 'manuell'` bleiben unangetastet. Damit können im WP-Backend manuell ergänzte Co-Klassenlehrkräfte einen WebUntis-Wechsel der Klassenlehrkraft überleben, ohne dass der Sync sie versehentlich löscht.

## 3. API-Vertrag WordPress-Plugin ↔ Backend

Wiederverwendung des VertretungsFlow-Musters (Shared-Secret + vertrauenswürdige Header, serverseitig durch das WP-Plugin gesetzt, nicht vom Browser):

**Request-Header (WP-Plugin → Backend), pro Aufruf:**
- `X-WordPress-Secret` — Shared Secret, Backend prüft mit zeitkonstantem Vergleich (`hmac.compare_digest`)
- `X-WordPress-User`, `X-WordPress-Email`, `X-WordPress-Name`
- `X-WordPress-Role` — einer von `klassenlehrkraft`/`bereichsleiter`/`schulleitung`, gemappt aus WP-User-Meta-Key `absenzdash_role` (analog VertretungsFlows `map_wp_role_to_absenzflow()`)
- `X-WordPress-WebUntis-Code` — optional, für Matching mit dem WebUntis-Klassenlehrkraft-Stammdatum

Backend: `get_wordpress_proxy_user()`-Äquivalent macht Get-or-Create/Update auf `nutzer`, schreibt `audit_log`-Eintrag mit `quelle: wordpress_proxy`. Rolle wird direkt aus dem Header übernommen (kein Re-Check gegen WP nötig, da der Secret die Vertrauensbasis ist — identisch zum VertretungsFlow-Modell).

**Kern-Endpunkte (Backend-API, vom WP-Plugin bzw. dessen React-SPA konsumiert):**

| Methode & Pfad | Zweck | Rollen |
|---|---|---|
| `GET /students` | gefilterte Übersicht (SPECS.md Abschnitt 7), Filter nach Klasse/Bereich/Status je nach Rolle des Aufrufers | alle |
| `GET /students/{id}` | Detailansicht: Fehlzeiten, Klassenbuch, Maßnahmen, Ausnahmen | alle (scope-geprüft) |
| `POST /students/{id}/measures` | Maßnahme erfassen | alle (scope-geprüft) |
| `POST /students/{id}/exemptions` | Ausnahme setzen | alle (scope-geprüft) |
| `DELETE /students/{id}/exemptions/{exemption_id}` | Ausnahme aufheben | alle (scope-geprüft) |
| `GET /students/{id}/export.pdf` | PDF-Export (SPECS.md Abschnitt 7) | alle (scope-geprüft) |
| `GET/PUT /admin/threshold-rules` | Schwellwert-Regeln verwalten | nur `schulleitung` |
| `GET/PUT /admin/measure-types` | Maßnahmen-Katalog pflegen | nur `schulleitung` |
| `GET/PUT /admin/sync-settings` | Sync-/Prüfintervall konfigurieren | nur `schulleitung` |

Scope-Prüfung (welche Schüler ein Nutzer sehen/bearbeiten darf) erfolgt serverseitig über `nutzer_klasse`/`nutzer_bereich`, nicht über den Rollen-Header allein.

## 4. WordPress-Plugin-Datenhaltung

Analog VertretungsFlow: **keine eigenen WP-DB-Tabellen**. Stattdessen:
- Plugin-Grundeinstellungen (Backend-URL, Shared Secret) über die WP-Options-API, ein serialisiertes Array (`add_option('absenzdash_options', ...)`, analog `absenzflow_options`).
- Pro Nutzer: WP-User-Meta-Keys `absenzdash_role` (Rolle) und optional `absenzdash_webuntis_code` (für Klassenlehrkraft-Matching), analog `absenzflow_role`/`absenzflow_webuntis_code`.
- Bereichsdefinition (Klassen ↔ Bereich, Bereich ↔ Bereichsleiter) und manuelle Zusatz-Klassenlehrkraft-Zuordnungen: administrative Oberfläche ist gemäß SPECS.md Abschnitt 2 das **WP-Backend** (neue PHP-Admin-Seite im Plugin, analog `class-admin.php`). Die Daten selbst werden aber **abweichend von VertretungsFlows Options-API/User-Meta-Pattern** nicht in WordPress, sondern direkt in der AbsenzDash-Datenbank gehalten (Tabellen `bereich`, `bereich_klasse`, `nutzer_klasse` mit `quelle='manuell'`, siehe Abschnitt 2): Diese WP-Admin-Seite ruft dafür lesend/schreibend die AbsenzDash-Backend-API auf (Abschnitt 3), statt eigene WP-Optionen/-Postmeta zu pflegen — sinnvoll, weil die Daten ohnehin relational mit `klasse`/`schueler` verknüpft sind und sonst dupliziert werden müssten. Fachliche Konfiguration (Schwellwerte, Maßnahmen-Katalog, Sync-Intervall) bleibt wie in SPECS.md Abschnitt 2/3 festgelegt ausschließlich im Dashboard-Admin-Bereich (SPA), nicht im WP-Backend.

## 5. Offene Risiken zur Validierung an der echten WebUntis-Instanz

Diese Punkte lassen sich nicht durch weitere Recherche klären, sondern nur durch einen kurzen technischen Spike gegen die reale Schul-WebUntis-Instanz vor bzw. zu Beginn der Umsetzung:

1. **Fehlzeiten-Endpunkt:** REST (`/WebUntis/api/classreg/absences/students`) vs. klassisches JSON-RPC (`getTimetableWithAbsences`) — Verfügbarkeit/Berechtigung des REST-Endpunkts für den Service-Account ist unklar (Abschnitt 1.2).
2. **Klassenlehrkraft-Feld:** ob `getKlassen` die Klassenlehrkraft-Zuordnung direkt liefert oder ein zusätzlicher Abgleich mit `getTeachers` nötig ist (Abschnitt 1.2).
3. **Service-Account-Berechtigungen:** `getClassregEvents` benötigt laut Library-Dokumentation explizit die Berechtigung "classregevents read for all" — muss für den WebUntis-Service-Account beantragt/geprüft werden.
4. **Klassenbuch-Kategorien:** welche Kategorien an dieser Schule tatsächlich in WebUntis gepflegt sind (relevant für sinnvolle Default-Schwellwert-Regeln in Abschnitt 2).

## 6. Deployment

Docker-Compose analog VertretungsFlow: `postgres` (Healthcheck via `pg_isready`), `backend` (FastAPI/Uvicorn), beide auf einem internen Netzwerk; `backend` zusätzlich auf einem **externen** Docker-Netzwerk, über das die vorhandene WordPress-Instanz erreichbar ist (kein eigener WordPress-Container in diesem Compose-Setup). Env-Vars analog: DB-Credentials, `WEBUNTIS_SERVER`/`_USERNAME`/`_PASSWORD`, `SMTP_*`, `WORDPRESS_PROXY_SECRET`, `SYNC_INTERVAL_CRON`.
