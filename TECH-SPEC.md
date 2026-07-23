# AbsenzDash — Technische Spezifikation

Stand: 2026-07-23

Begleitdokument zu [SPECS.md](SPECS.md). Konkretisiert Datenmodell, API-Vertrag und WebUntis-Feldmapping auf Basis der Recherche im Referenzprojekt [VertretungsFlow](https://github.com/digitale-Schulverwaltung-BW/VertretungsFlow) (intern "AbsenzFlow" genannt) und der `python-webuntis`-Bibliothek. Weiterhin keine Implementierung — dieses Dokument liefert die Fakten, die ein späterer Umsetzungsplan (`writing-plans`) braucht, um ohne Platzhalter auszukommen.

## 1. WebUntis-Integration

### 1.1 Auth gegen WebUntis

Wie VertretungsFlow: eigener JSON-RPC-2.0-Client gegen `https://{server}/WebUntis/jsonrpc.do` (kein Drittanbieter-Package nötig, ca. 150 Zeilen). Service-Account-Login per `authenticate`-Methode (Username/Passwort aus `.env`), Session-ID wird als `JSESSIONID`-Cookie an Folge-Requests gehängt. Bei Session-Expiry (`error.code == -8520`) automatischer Re-Auth + Retry. Gleiches Muster wie VertretungsFlow (`WEBUNTIS_SERVER`, `WEBUNTIS_USERNAME`, `WEBUNTIS_PASSWORD` als Env-Vars).

### 1.2 Endpunkte & Feldmapping

**Klassen-Stammdaten (inkl. Klassenlehrkraft):** `getKlassen` (bereits von VertretungsFlow genutztes Muster für Stammdaten). Am 2026-07-23 gegen die reale Instanz bestätigt: Antwort enthält direkt `id` (Integer), `name`, `longName`, `active`, `did` (Abteilungs-ID, Bedeutung noch zu prüfen), `teacher1`, `teacher2` (Integer-IDs, aufzulösen über `getTeachers`). Kein zusätzlicher Aufruf zur reinen ID-Zuordnung nötig — nur zur Auflösung der Teacher-ID auf Name/E-Mail.

**Fehlzeiten:** Am 2026-07-23 gegen die reale Schul-Instanz verifiziert (Spike-Ergebnis, siehe Abschnitt 5). **Entscheidung: klassisches JSON-RPC `getTimetableWithAbsences`.** Der neuere REST-Endpunkt (`/WebUntis/api/classreg/absences/students`) liefert an dieser Instanz durchgehend `500 INTERNAL_ERROR` (Body: `{"errors":[{"code":"INTERNAL_ERROR",...}]}`) und wird nicht weiterverfolgt.

`getTimetableWithAbsences(startDate, endDate)` liefert unter `periodsWithAbsences[]` zwei unterscheidbare Eintragstypen — unterscheidbar am Vorhandensein von `subjectId`:

| | Tag-Ebene (`subjectId` leer/fehlt) | Stunden-Ebene (`subjectId` gesetzt, z.B. `"Deutsch"`) |
|---|---|---|
| Zweck | Ganztägiger Abwesenheits-Rahmen (`startTime: 0`, `endTime: 2359`) | Einzelne betroffene Unterrichtsstunde |
| Beobachtete Felder | `date`, `startTime`, `endTime`, `studentId`, `checked`, teils `status: "irregular"` | zusätzlich `absenceReason` (Freitext, im Sample leer), `absentTime` (Zahl, Einheit/Bedeutung unklar — **nicht verlässlich für Dauerberechnung**), `excuseStatus` (String, bestätigter Beispielwert: `"nicht entsch."`), `invalid` (bool) |
| Anteil im 30-Tage-Testzeitraum | ~87% von 80.882 Einträgen (kein `subjectId`) | ~20% mit `absenceReason`, ~14% mit `excuseStatus` |
| Keine eigene WebUntis-ID | — jeder Eintrag hat weder auf Tag- noch auf Stunden-Ebene ein `id`/`eventId`-Feld — anders als bei Klassenbucheinträgen (siehe unten) | |

Das deckt sich gut mit der Fehltage/Fehlstunden-Unterscheidung aus SPECS.md Abschnitt 4: **Tag-Ebene-Einträge zählen als Fehltage, Stunden-Ebene-Einträge (mit `subjectId`) als Fehlstunden — eine Fehlstunde pro Eintrag**, statt sich auf das unklare `absentTime`-Feld zu verlassen.

`excuseStatus` referenziert **keinen freien String, sondern schulspezifisch konfigurierbare WebUntis-Stammdaten** ("Entschuldigungsstatus", WebUntis-Admin-UI: Stammdaten → Entschuldigungsstatus) — analog zu den Klassenbuch-Kategorien in Abschnitt 1.2 unten. Laut Admin-UI-Ansicht dieser Schule (Screenshot vom 2026-07-23) hat jeder Status: `Name` (Kurzform, z.B. `"nicht entsch."` — deckt sich exakt mit dem im Spike beobachteten `excuseStatus`-Wert), `Langname` (z.B. `"nicht entschuldigt"`), **`Entschuldigung zählt`** (Boolean — die für unseren Filter maßgebliche Information), `Aktiv`. An dieser Schule aktuell 4 Status: `entsch.`/`entschuldigt` (zählt: ja), `nicht akzep.`/`nicht akzeptiert` (zählt: nein), `nicht entsch.`/`nicht entschuldigt` (zählt: nein), `hybrid`/`online-Teilnahme am Präsenzunterricht` (zählt: ja).

Das macht den Fehlzeiten-Filter (SPECS.md Abschnitt 4) robust: statt String-Heuristik ("beginnt mit `nicht `") kann direkt auf das `Entschuldigung zählt`-Flag des referenzierten Status geprüft werden. **Offen:** der JSON-RPC-Methodenname, um diese Stammdaten programmatisch abzurufen, ist in keiner öffentlichen Quelle (`python-webuntis`, Community-API-Docs) dokumentiert. Das Spike-Skript probiert dafür naheliegende Kandidaten (`getExcuseStatuses` u.a., siehe Abschnitt 5) — Ergebnis steht noch aus. Notfalls lässt sich die kleine, stabile Liste (aktuell 4 Einträge) auch einmalig manuell in `excuse_status` gepflegt werden, statt sie zu synchronisieren.

`invalid: true` markiert vermutlich stornierte/ungültige Einträge und wird beim Sync ausgeschlossen. `studentId` ist kein Integer, sondern ein WebUntis-interner, UUID-artiger String (Beispiel: `8a90419d-7c91f2a7-017c-92b5db31-0203`) — relevant für den Feldtyp in Abschnitt 2.

**Klassenbucheinträge:** Nur über klassische JSON-RPC verfügbar (kein REST-Äquivalent gefunden). Am 2026-07-23 gegen die reale Instanz bestätigt (Service-Account hat die nötige Berechtigung — 66 Einträge im 30-Tage-Testzeitraum ohne Fehler):
- `getClassregEvents(startDate, endDate, [id, type])` → Liste von Einträgen mit Feldern (bestätigt, reichhaltiger als in `python-webuntis` dokumentiert): `studentid` (String, gleiches UUID-artiges Format wie bei Fehlzeiten), `surname`, `forname`, `date`, `subject` (Kürzel, z.B. `"LBT1"`), `reason` (im Sample leer), `text` (Freitext-Notiz), **`eventId`** (Integer, eindeutig — nutzbar als stabile WebUntis-ID für Idempotenz), `lessonId` (Integer, Referenz auf die Unterrichtsstunde), `time` (Integer, Uhrzeit-artiges Format wie `1110` = 11:10 — vermutlich Erstellungszeitpunkt der Stunde, nicht der Notiz), `createTeacher`/`updateTeacher` (je `{id, name}` — wer den Eintrag angelegt/zuletzt geändert hat).
- `getClassregCategories()` → Kategorie-Stammdaten, laut Bibliotheks-Doku `name`, `longName`, `groupId` (im Spike nur Namen ausgelesen — volle Struktur vor dem Bau verifizieren). Bestätigte Kategorien an dieser Schule: `stören`, `Bem`, `§90`, `Tel`, `SP-Kleid vergessen`, `SP anw. freigestellt`, `Corona-Verordnung`, `Hinweis Fehlzeiten`.
- `getClassregCategoryGroups()` → Gruppen-Stammdaten: `name`. Bestätigte Gruppen: `§90`, `Info`, `Störung`.
- **Wichtig:** Kategorien sind schulspezifisch in WebUntis konfigurierte Laufzeit-Daten, kein festes API-Enum — oben bestätigt. AbsenzDash muss `getClassregCategories`/`getClassregCategoryGroups` beim Sync mit abrufen und lokal cachen (Tabelle `classreg_category`, siehe Abschnitt 2), damit Schwellwert-Regeln (SPECS.md Abschnitt 4) auf diese konkreten Kategorien referenzieren können. Für "Verspätung" (hier nicht als eigene Kategorie vorhanden, evtl. Teil von `"stören"`) gibt es kein separates Minuten-/Dauer-Feld.
- Berechtigung "classregevents read for all" ist für den genutzten Service-Account vorhanden — kein offener Punkt mehr.

## 2. Datenbank-Schema

PostgreSQL, SQLAlchemy 2.0-Style mit `Mapped[]`-Typannotationen (Verbesserung gegenüber VertretungsFlow, das den Legacy-`declarative_base()`-Stil ohne durchgängige Typisierung nutzt). Alembic-Migrationen von Anfang an real genutzt (VertretungsFlow hat Alembic nur als ungenutzte Dependency gelistet und pflegt Schema-Änderungen stattdessen über handgeschriebene, durchnummerierte SQL-Dateien ohne Down-Migration — das übernehmen wir bewusst **nicht**). Gemeinsame `TimestampMixin` (`created_at`, `updated_at`) für alle Tabellen, ebenfalls eine Verbesserung gegenüber VertretungsFlow, das dies pro Modell dupliziert.

| Tabelle                 | Wesentliche Felder                                                                                                                                                                                                                                                        | Bezug                                                                                                                                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `klasse`                | `webuntis_id` (Integer, unique), `name`, `stufe`, `schulart`, `webuntis_teacher1_id`/`webuntis_teacher2_id` (Integer, nullable)                                                                                                                                          | Cache aus `getKlassen`                                                                                                                                                                              |
| `bereich`               | `name`                                                                                                                                                                                                                                                                    | lokal, nicht aus WebUntis (SPECS.md Abschnitt 4)                                                                                                                                                    |
| `bereich_klasse` (m:n)  | `bereich_id`, `klasse_id`                                                                                                                                                                                                                                                 | Bereichsdefinition                                                                                                                                                                                  |
| `schueler`              | `webuntis_id` (**String**, unique — WebUntis-Elementkey, kein Integer), `vorname`, `nachname`, `klasse_id`                                                                                                                                                               | Cache aus WebUntis                                                                                                                                                                                  |
| `fehlzeit`              | `schueler_id`, `typ` (`tag`/`stunde`, abgeleitet aus Vorhandensein von `subjectId`), `datum`, `start_zeit`/`end_zeit` (nullable bei `typ=tag`), `fach` (nullable, nur bei `typ=stunde`), `excuse_status_id` (FK auf `excuse_status`, nullable solange nicht geprüft/kein Status gesetzt), `grund_text` (nullable), `invalid` (bool, Sync filtert `invalid=true` aus) | Cache aus `getTimetableWithAbsences`. **Kein `webuntis_id`-Feld** — WebUntis liefert für Fehlzeiten-Einträge keine eigene ID; Unique-Constraint stattdessen über (`schueler_id`, `datum`, `start_zeit`, `end_zeit`, `typ`) für Idempotenz beim Re-Sync |
| `excuse_status`         | `name` (unique, Kurzform, z.B. `"nicht entsch."`), `long_name`, `zaehlt_als_entschuldigt` (bool), `aktiv` (bool)                                                                                                                                                          | Cache der WebUntis-Stammdaten "Entschuldigungsstatus" (Abschnitt 1.2); Sync-Methode noch zu bestätigen (Abschnitt 5) — Fallback: einmalig manuell gepflegt                                         |
| `klassenbuch_eintrag`   | `webuntis_id` (Integer, unique — aus `eventId`), `schueler_id`, `kategorie_id`, `datum`, `text`, `lesson_id` (Integer), `erstellt_von_teacher_id`/`geaendert_von_teacher_id` (Integer, aus `createTeacher.id`/`updateTeacher.id`)                                       | Cache aus `getClassregEvents`                                                                                                                                                                       |
| `classreg_category`     | `webuntis_id`, `name`, `long_name`, `group_name`                                                                                                                                                                                                                          | Cache aus `getClassregCategories`/`-CategoryGroups`                                                                                                                                                 |
| `schwellwert_regel`     | `typ` (`fehlzeiten`/`klassenbuch`), `geltungsbereich` (`schulweit`/`stufe`/`schulart`), `geltungswert` (nullable, z.B. Stufe-5-Wert)                                                                                                                                      | SPECS.md Abschnitt 4                                                                                                                                                                                |
| `schwellwert_stufe`     | `regel_id`, `stufe_nr`, `einheit` (`fehltage`/`fehlstunden`, nur bei Fehlzeiten-Regeln), `schwellenwert`, `fehlzeiten_filter` (`nur_unentschuldigt`/`alle`, nur bei Fehlzeiten-Regeln), `empfaenger_rollen` (Array: `klassenlehrkraft`\|`bereichsleiter`\|`schulleitung`) |                                                                                                                                                                                                     |
| `schueler_zaehlerstand` | `schueler_id`, `regel_id`, `aktueller_stand`, `erreichte_stufe_nr`, `letzter_reset_am`                                                                                                                                                                                    | pro Schüler+Regel geführter Eskalations-Zähler (SPECS.md Abschnitt 5)                                                                                                                               |
| `massnahmen_typ`        | `name`, `setzt_zaehler_zurueck` (bool), `betroffene_regel_ids` (Array)                                                                                                                                                                                                    | konfigurierbarer Katalog, Default-Set siehe SPECS.md Abschnitt 4                                                                                                                                    |
| `massnahme`             | `schueler_id`, `massnahmen_typ_id`, `datum`, `notiz`, `erfasst_von_user_id`                                                                                                                                                                                               |                                                                                                                                                                                                     |
| `ausnahme`              | `schueler_id`, `kategorie` (`fehlzeiten`/`klassenbuch`), `grund`, `gueltig_bis` (nullable), `aktiv` (bool)                                                                                                                                                                | SPECS.md Abschnitt 4                                                                                                                                                                                |
| `audit_log`             | `user_id`, `aktion`, `resource_typ`, `resource_id`, `details` (JSON), `zeitpunkt`                                                                                                                                                                                         | analog VertretungsFlow `audit.py`, aber als echte Tabelle statt Ad-hoc-Aufrufen ohne feste Struktur                                                                                                 |
| `nutzer`                | `wp_user_id`, `email`, `name`, `rolle` (`klassenlehrkraft`/`bereichsleiter`/`schulleitung`), `webuntis_teacher_id` (Integer, nullable, aus `X-WordPress-WebUntis-Code`)                                                                                                   | get-or-create bei erstem Proxy-Request, analog VertretungsFlow. `webuntis_teacher_id` ist das Matching-Ziel für `klasse.webuntis_teacher1_id`/`teacher2_id` beim Seeden von `nutzer_klasse` (2.1)  |
| `nutzer_klasse` (m:n)   | `nutzer_id`, `klasse_id`, `quelle` (`webuntis_seed`/`manuell`)                                                                                                                                                                                                            | löst SPECS.md Abschnitt 4 auf: WebUntis-geseedete + manuell im WP-Backend ergänzte Klassenlehrkraft-Zuordnungen in einer Tabelle, `quelle` unterscheidet Herkunft für Re-Sync-Verhalten (siehe 2.1) |
| `nutzer_bereich` (m:n)  | `nutzer_id`, `bereich_id`                                                                                                                                                                                                                                                 | Bereichsleiter-Zuordnung                                                                                                                                                                            |

### 2.1 Sync-Verhalten für `nutzer_klasse`

Beim WebUntis-Sync werden Zeilen mit `quelle = 'webuntis_seed'` für die betroffene Klasse gelöscht und aus der aktuellen `getKlassen`-Antwort neu geschrieben: für jede Klasse wird `webuntis_teacher1_id`/`teacher2_id` gegen `nutzer.webuntis_teacher_id` gematcht; existiert (noch) kein passender `nutzer`-Datensatz (z.B. weil die Lehrkraft sich noch nie im Dashboard angemeldet hat), wird das Seeding für diese Klasse übersprungen und beim nächsten Sync erneut versucht. Zeilen mit `quelle = 'manuell'` bleiben unangetastet. Damit können im WP-Backend manuell ergänzte Co-Klassenlehrkräfte einen WebUntis-Wechsel der Klassenlehrkraft überleben, ohne dass der Sync sie versehentlich löscht.

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

## 5. WebUntis-Spike: Ergebnisse

Am 2026-07-23 mit [scratchpad/webuntis_spike.py](scratchpad/webuntis_spike.py) gegen die reale Schul-Instanz geprüft (Service-Account). Alle vier ursprünglich offenen Risiken sind geklärt, die Ergebnisse sind bereits in Abschnitt 1.2 und 2 eingearbeitet:

1. ✅ **Fehlzeiten-Endpunkt:** REST-Endpunkt liefert `500 INTERNAL_ERROR`, verworfen. Klassisches JSON-RPC `getTimetableWithAbsences` funktioniert und liefert zwei Eintragstypen (Tag-/Stunden-Ebene), die sich gut auf Fehltage/Fehlstunden abbilden lassen (Abschnitt 1.2).
2. ✅ **Klassenlehrkraft-Feld:** `getKlassen` liefert `teacher1`/`teacher2` direkt mit.
3. ✅ **Service-Account-Berechtigungen:** vorhanden, `getClassregEvents` liefert sogar mehr Felder als in `python-webuntis` dokumentiert (`eventId`, `lessonId`, `time`, `createTeacher`/`updateTeacher`).
4. ✅ **Klassenbuch-Kategorien:** 8 konkrete Kategorien, 3 Gruppen bestätigt (Abschnitt 1.2).

**Nachtrag (Admin-UI-Screenshot):** `excuseStatus` referenziert schulspezifische WebUntis-Stammdaten ("Entschuldigungsstatus") mit Name, Langname, `Entschuldigung zählt`-Boolean und Aktiv-Flag (Abschnitt 1.2) — damit ist die ursprüngliche Lücke aus dem letzten Update inhaltlich geschlossen, der Fehlzeiten-Filter kann sich auf dieses Boolean statt auf String-Heuristik stützen.

**Verbleibende kleine, nicht blockierende Lücke:** Der JSON-RPC-Methodenname zum programmatischen Abruf dieser Entschuldigungsstatus-Stammdaten ist noch nicht bestätigt (Kandidaten `getExcuseStatuses` u.a. im Spike-Skript ergänzt, Testlauf steht aus). Bei aktuell nur 4 Status an dieser Schule ist auch eine einmalige manuelle Pflege in `excuse_status` eine akzeptable Fallback-Option — kein Hindernis für die weitere Spezifikationsarbeit.

## 6. Deployment

Docker-Compose analog VertretungsFlow: `postgres` (Healthcheck via `pg_isready`), `backend` (FastAPI/Uvicorn), beide auf einem internen Netzwerk; `backend` zusätzlich auf einem **externen** Docker-Netzwerk, über das die vorhandene WordPress-Instanz erreichbar ist (kein eigener WordPress-Container in diesem Compose-Setup). Env-Vars analog: DB-Credentials, `WEBUNTIS_SERVER`/`_USERNAME`/`_PASSWORD`, `SMTP_*`, `WORDPRESS_PROXY_SECRET`, `SYNC_INTERVAL_CRON`.
