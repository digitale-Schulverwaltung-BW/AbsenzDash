# AbsenzDash — Roadmap

Stand: 2026-07-27

Übergeordneter Fortschritts-Tracker über [SPECS.md](SPECS.md)/[TECH-SPEC.md](TECH-SPEC.md) hinweg. Die fachlichen/technischen Details stehen dort und in den einzelnen Umsetzungsplänen unter `docs/superpowers/plans/` — dieses Dokument bildet nur ab, welcher Teil des Gesamtsystems (SPECS.md) bereits durch welchen Plan abgedeckt ist und was noch offen ist.

**Pflege-Hinweis:** Nach Abschluss jedes weiteren Plans hier den entsprechenden Punkt von "Geplant" nach "Abgeschlossen" verschieben und ggf. neue Erkenntnisse (z.B. Scope-Änderungen wie beim ASV-BW-CSV-Pivot in Plan 2) kurz vermerken.

## Abgeschlossen

| Plan | Deckt ab | Bewusst nicht enthalten |
|---|---|---|
| **Plan 1** — [Backend-Grundgerüst & Datenmodell](docs/superpowers/plans/2026-07-24-backend-grundgeruest.md) | FastAPI-Skelett, komplettes DB-Schema für Stammdaten (`klasse`, `bereich`, `schueler`, `fehlzeit`, `klassenbuch_eintrag`, `excuse_status`, `classreg_category`, `einstellung`, `audit_log`, `nutzer`, `nutzer_klasse`, `nutzer_bereich`), WordPress-Proxy-Authentifizierung, `nutzer_klasse`-Seeding | WebUntis-Anbindung, REST-Endpunkte, Eskalations-Engine |
| **Plan 2** — [Backend WebUntis-Sync-Job](docs/superpowers/plans/2026-07-24-webuntis-sync.md) | WebUntis-JSON-RPC-Client, Klassen-/Kategorie-Sync, ASV-BW-CSV-Import für Schüler-Stammdaten (ersetzt ursprünglich geplanten WebUntis-Roster-Abgleich, siehe Design-Dok), Fehlzeiten-/Klassenbuch-Sync, Retry-Orchestrator, APScheduler | `/admin/sync-now`-Endpunkt, Eskalations-Engine, Excuse-Status-Admin-Pflege |
| **Plan 3** — [Eskalations-Engine](docs/superpowers/plans/2026-07-26-eskalations-engine.md) | Schwellwert-Regeln (schulweit/abteilungsweit/klassenweit-Präzedenz), mehrstufige Eskalation, Maßnahmen-Katalog inkl. Default-Set und Zähler-Reset, Ausnahmen, Benachrichtigungs-Log (inkl. Empfänger-Auflösung und initial_import/kein_empfaenger-Sonderfälle) | Admin-UI/API für Regel-/Maßnahmen-Pflege, tatsächlicher E-Mail-Versand |
| **Plan 3.1** — [Eskalations-Engine Follow-Ups](docs/superpowers/plans/2026-07-26-eskalations-engine-followups.md) | Nicht-blockierende Findings aus dem Plan-3-Abschlussreview: Query-Caching in `pruefe_schwellwerte` (Regel-Auflösung, Zählerstand-Wiederverwendung), fehlender Index auf `benachrichtigung.schueler_id`/`regel_id`, 3 nachgezogene Regressionstests, Log-Spam-Fix | — |
| **Plan 4** — [E-Mail-Benachrichtigungen](docs/superpowers/plans/2026-07-26-email-benachrichtigungen.md) | SMTP-Versand bei neu erreichter Eskalationsstufe (`app/services/mailer.py`), admin-anpassbares Text-Template (gitignorete Override-Datei), neuer `benachrichtigung.status`-Wert `"fehler"` bei Versandfehlern | Automatischer Retry bei fehlgeschlagenem Versand (bewusst, siehe Design-Dokument) |
| **Plan 5** — [Backend REST-API fürs WP-Plugin — Kern-Endpunkte](docs/superpowers/plans/2026-07-27-rest-api-wordpress-kern.md) | Scope-Check (`nutzer_klasse`/`nutzer_bereich`), `GET /students` (paginiert, gefiltert), `GET /students/{id}`, `POST /students/{id}/measures`, `POST/DELETE /students/{id}/exemptions`, Audit-Log für Maßnahmen/Ausnahmen (TECH-SPEC.md §3, SPECS.md §3/4/7) | Admin-Konfigurationsendpunkte (`/admin/*`), PDF-Export |

## Geplant (noch nicht als Plan ausgearbeitet)

Grobe, noch unverbindliche Reihenfolge — jeder Punkt braucht vor der Umsetzung noch einen eigenen Brainstorming-/Planungsdurchlauf:

1. **Backend: REST-API fürs WP-Plugin — Admin-Konfiguration & PDF-Export** — `/admin/*`-Konfigurationsendpunkte inkl. `/admin/sync-now`, `GET /students/{id}/export.pdf` (TECH-SPEC.md §3). Kern-Endpunkte (Übersicht/Detail/Maßnahmen/Ausnahmen) sind mit Plan 5 fertig.
2. **Frontend: React/TS-SPA** — Übersicht, Schüler-Detail, Admin-Bereich, PDF-Export (SPECS.md §2/§7). Bisher nichts gebaut.
3. **WordPress-Plugin** — Shortcode-Einbindung der SPA, Options-API für Backend-URL/Secret, Rollen-/WebUntis-Code-Zuordnung per User-Meta, Bereichsdefinition-Admin-Seite (SPECS.md §2, TECH-SPEC.md §4). Bisher nichts gebaut.
4. **Excuse-Status-Admin-Pflege** — manuelle Verwaltung im Dashboard-Admin-Bereich, da kein WebUntis-Sync möglich (TECH-SPEC.md §1.2/§5). Kann Teil von Punkt 2/3 sein statt eigener Plan.

## Technical debt

Bekannte, nicht dringende Verbesserungen — kein eigener Plan nötig, bei Gelegenheit oder wenn die Performance tatsächlich zum Problem wird:

- **`SchwellwertStufe`-Caching in `pruefe_schwellwerte`** (`backend/app/services/eskalations_pruefung.py`): `_ermittle_erreichte_stufe` fragt die Stufen einer Regel pro Schüler neu ab, obwohl sie pro Regel innerhalb eines Sync-Laufs invariant sind — gleiches Cache-Muster wie bereits für `resolve_schwellwert_regel` und die Zählerstand-Wiederverwendung in Plan 3.1 umgesetzt. Bei Schulgröße (~1500 Schüler) ca. 20% weniger verbleibende DB-Round-Trips in dieser Funktion. Identifiziert im Abschlussreview von [Plan 3.1](docs/superpowers/plans/2026-07-26-eskalations-engine-followups.md), bewusst nicht mit umgesetzt.
- **Stufenvergleich bei Klassenwechsel in anders nummerierte Regel** (`schueler_zaehlerstand`, siehe TECH-SPEC.md Abschnitt 2 "Bekannte Einschränkung"): wechselt ein Schüler in eine Klasse mit einer Regel, deren Stufen anders nummeriert sind, kann `neue_stufe_nr > alte_stufe_nr` fachlich falsch (nicht) zutreffen — Folge kann eine ausbleibende oder eine doppelte Benachrichtigung sein. In Plan 3 bewusst für den Zähler in Kauf genommen; im finalen Review von Plan 4 (E-Mail-Benachrichtigungen) erneut bewusst zurückgestellt, da der Branch die bestehende Einschränkung nicht verschlimmert, jetzt aber statt eines Log-Eintrags eine tatsächliche E-Mail betrifft. Aufgreifen, falls das in der Praxis auffällt (z.B. eigener Regelwechsel-Erkennungsmechanismus in `pruefe_schwellwerte`).
- **Doppelte `MassnahmenTyp`-Abfrage in `POST /students/{id}/measures`** (`backend/app/api/routes/students.py`, `backend/app/services/massnahme_service.py`): die Route lädt den Typ für die 404-Prüfung, `record_massnahme` lädt ihn intern nochmal. Harmlos, aber unnötig; bei einem Lösch-Race zwischen beiden Abfragen führt das aktuell zu einem 500 statt eines 404. Fix: `record_massnahme` den bereits geladenen `typ_row` übergeben (analog zum `revoke_ausnahme(db, ausnahme, ...)`-Muster). Identifiziert im Abschlussreview von Plan 5, bewusst nicht mit umgesetzt.
- **`MassnahmeOut`-Konstruktion dupliziert** (`backend/app/api/routes/students.py`, in `get_student_detail` und `create_measure`): zwei identische 8-zeilige kwarg-Blöcke aus unterschiedlichen Quellen (Tupel vs. lose Variablen). Ein `_massnahme_out(...)`-Helfer (analog zum bereits vorhandenen `_benachrichtigung_out(...)`) würde das DRY machen. Identifiziert im Abschlussreview von Plan 5.
- **Schema-Modul-Nähte in `backend/app/schemas/students.py`**: über vier Teil-Pläne gewachsen, dadurch (a) inkonsistente Namenskonvention (Response-Schemas deutsch, Request-Schemas englisch — nirgends dokumentiert, warum), (b) `StudentOverviewOut` trägt unnötig `ConfigDict(from_attributes=True)`, obwohl es nie aus einem ORM-Objekt validiert wird (nur `StudentDetailOut`/`MassnahmeOut` machen es korrekt ohne), (c) `AusnahmeOut` in der `POST /exemptions`-Antwort spiegelt `schueler_id` nicht (aus dem Pfad rekonstruierbar, nur API-Symmetrie). Identifiziert im Abschlussreview von Plan 5.
- **`min_stufe`-Query-Parameter ohne Validierung** (`GET /students`, `backend/app/api/routes/students.py`): `limit`/`offset` sind über `Query(ge=...)` validiert, `min_stufe` nicht — negative oder 0-Werte degradieren still zu `nur_auffaellige`-Semantik statt eines 422. Fix: `Query(ge=1)` ergänzen. Identifiziert im Abschlussreview von Plan 5.
- **Pytest-Kollisions-Warnung durch `test_app`-Namen** (`backend/tests/test_api_deps_scope.py`, analog bereits bestehend in `test_deps_wordpress_proxy.py`): eine lokale FastAPI-Instanz namens `test_app` wird von pytest fälschlich als Testfunktion kollisioniert und erzeugt eine harmlose `PytestCollectionWarning` bei jedem Lauf. Fix: umbenennen (z.B. `scope_test_app`). Identifiziert im Abschlussreview von Plan 5.

## Nicht-Ziele (dauerhaft außerhalb des Scopes, aus SPECS.md §9)

- Kein direkter E-Mail-Versand an Eltern.
- Kein öffentliches/externes API.
- Keine eigene Passwortverwaltung (Auth läuft über WordPress/LDAP).
