# AbsenzDash — Roadmap

Stand: 2026-07-26

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

## Geplant (noch nicht als Plan ausgearbeitet)

Grobe, noch unverbindliche Reihenfolge — jeder Punkt braucht vor der Umsetzung noch einen eigenen Brainstorming-/Planungsdurchlauf:

1. **Backend: REST-API fürs WP-Plugin** — `/students`, `/students/{id}`, Maßnahmen-/Ausnahmen-Endpunkte, `/admin/*`-Konfigurationsendpunkte inkl. `/admin/sync-now` (TECH-SPEC.md §3). Setzt die bereits vorhandene WP-Proxy-Auth-Dependency (Plan 1) tatsächlich in Routen ein.
2. **Frontend: React/TS-SPA** — Übersicht, Schüler-Detail, Admin-Bereich, PDF-Export (SPECS.md §2/§7). Bisher nichts gebaut.
3. **WordPress-Plugin** — Shortcode-Einbindung der SPA, Options-API für Backend-URL/Secret, Rollen-/WebUntis-Code-Zuordnung per User-Meta, Bereichsdefinition-Admin-Seite (SPECS.md §2, TECH-SPEC.md §4). Bisher nichts gebaut.
4. **Excuse-Status-Admin-Pflege** — manuelle Verwaltung im Dashboard-Admin-Bereich, da kein WebUntis-Sync möglich (TECH-SPEC.md §1.2/§5). Kann Teil von Punkt 2/3 sein statt eigener Plan.

## Technische Schulden

Bekannte, nicht dringende Verbesserungen — kein eigener Plan nötig, bei Gelegenheit oder wenn die Performance tatsächlich zum Problem wird:

- **`SchwellwertStufe`-Caching in `pruefe_schwellwerte`** (`backend/app/services/eskalations_pruefung.py`): `_ermittle_erreichte_stufe` fragt die Stufen einer Regel pro Schüler neu ab, obwohl sie pro Regel innerhalb eines Sync-Laufs invariant sind — gleiches Cache-Muster wie bereits für `resolve_schwellwert_regel` und die Zählerstand-Wiederverwendung in Plan 3.1 umgesetzt. Bei Schulgröße (~1500 Schüler) ca. 20% weniger verbleibende DB-Round-Trips in dieser Funktion. Identifiziert im Abschlussreview von [Plan 3.1](docs/superpowers/plans/2026-07-26-eskalations-engine-followups.md), bewusst nicht mit umgesetzt.
- **Stufenvergleich bei Klassenwechsel in anders nummerierte Regel** (`schueler_zaehlerstand`, siehe TECH-SPEC.md Abschnitt 2 "Bekannte Einschränkung"): wechselt ein Schüler in eine Klasse mit einer Regel, deren Stufen anders nummeriert sind, kann `neue_stufe_nr > alte_stufe_nr` fachlich falsch (nicht) zutreffen — Folge kann eine ausbleibende oder eine doppelte Benachrichtigung sein. In Plan 3 bewusst für den Zähler in Kauf genommen; im finalen Review von Plan 4 (E-Mail-Benachrichtigungen) erneut bewusst zurückgestellt, da der Branch die bestehende Einschränkung nicht verschlimmert, jetzt aber statt eines Log-Eintrags eine tatsächliche E-Mail betrifft. Aufgreifen, falls das in der Praxis auffällt (z.B. eigener Regelwechsel-Erkennungsmechanismus in `pruefe_schwellwerte`).

## Nicht-Ziele (dauerhaft außerhalb des Scopes, aus SPECS.md §9)

- Kein direkter E-Mail-Versand an Eltern.
- Kein öffentliches/externes API.
- Keine eigene Passwortverwaltung (Auth läuft über WordPress/LDAP).
