# AbsenzDash — Roadmap

Stand: 2026-07-26

Übergeordneter Fortschritts-Tracker über [SPECS.md](SPECS.md)/[TECH-SPEC.md](TECH-SPEC.md) hinweg. Die fachlichen/technischen Details stehen dort und in den einzelnen Umsetzungsplänen unter `docs/superpowers/plans/` — dieses Dokument bildet nur ab, welcher Teil des Gesamtsystems (SPECS.md) bereits durch welchen Plan abgedeckt ist und was noch offen ist.

**Pflege-Hinweis:** Nach Abschluss jedes weiteren Plans hier den entsprechenden Punkt von "Geplant" nach "Abgeschlossen" verschieben und ggf. neue Erkenntnisse (z.B. Scope-Änderungen wie beim ASV-BW-CSV-Pivot in Plan 2) kurz vermerken.

## Abgeschlossen

| Plan | Deckt ab | Bewusst nicht enthalten |
|---|---|---|
| **Plan 1** — [Backend-Grundgerüst & Datenmodell](docs/superpowers/plans/2026-07-24-backend-grundgeruest.md) | FastAPI-Skelett, komplettes DB-Schema für Stammdaten (`klasse`, `bereich`, `schueler`, `fehlzeit`, `klassenbuch_eintrag`, `excuse_status`, `classreg_category`, `einstellung`, `audit_log`, `nutzer`, `nutzer_klasse`, `nutzer_bereich`), WordPress-Proxy-Authentifizierung, `nutzer_klasse`-Seeding | WebUntis-Anbindung, REST-Endpunkte, Eskalations-Engine |
| **Plan 2** — [Backend WebUntis-Sync-Job](docs/superpowers/plans/2026-07-24-webuntis-sync.md) | WebUntis-JSON-RPC-Client, Klassen-/Kategorie-Sync, ASV-BW-CSV-Import für Schüler-Stammdaten (ersetzt ursprünglich geplanten WebUntis-Roster-Abgleich, siehe Design-Dok), Fehlzeiten-/Klassenbuch-Sync, Retry-Orchestrator, APScheduler | `/admin/sync-now`-Endpunkt, Eskalations-Engine, Excuse-Status-Admin-Pflege |

## Geplant (noch nicht als Plan ausgearbeitet)

Grobe, noch unverbindliche Reihenfolge — jeder Punkt braucht vor der Umsetzung noch einen eigenen Brainstorming-/Planungsdurchlauf:

1. **Backend: Eskalations-Engine** — Schwellwert-Regeln, mehrstufige Zähler, Maßnahmen-Katalog/-Einträge, Ausnahmen (SPECS.md §4/5). Bisher **keine** DB-Modelle vorhanden (`schwellwert_regel`, `schwellwert_stufe`, `schueler_zaehlerstand`, `massnahmen_typ`, `massnahme`, `ausnahme`) — in Plan 1 explizit als "bewusst nächster Plan" markiert.
2. **Backend: E-Mail-Benachrichtigungen** — Versand bei neu erreichter Eskalationsstufe, `benachrichtigung`-Log, Sonderfall initialer Import ohne Versand (SPECS.md §5.1/§6). Baut auf Punkt 1 auf.
3. **Backend: REST-API fürs WP-Plugin** — `/students`, `/students/{id}`, Maßnahmen-/Ausnahmen-Endpunkte, `/admin/*`-Konfigurationsendpunkte inkl. `/admin/sync-now` (TECH-SPEC.md §3). Setzt die bereits vorhandene WP-Proxy-Auth-Dependency (Plan 1) tatsächlich in Routen ein.
4. **Frontend: React/TS-SPA** — Übersicht, Schüler-Detail, Admin-Bereich, PDF-Export (SPECS.md §2/§7). Bisher nichts gebaut.
5. **WordPress-Plugin** — Shortcode-Einbindung der SPA, Options-API für Backend-URL/Secret, Rollen-/WebUntis-Code-Zuordnung per User-Meta, Bereichsdefinition-Admin-Seite (SPECS.md §2, TECH-SPEC.md §4). Bisher nichts gebaut.
6. **Excuse-Status-Admin-Pflege** — manuelle Verwaltung im Dashboard-Admin-Bereich, da kein WebUntis-Sync möglich (TECH-SPEC.md §1.2/§5). Kann Teil von Punkt 3/4 sein statt eigener Plan.

## Bekannte offene technische Schulden

- **Sync-Orchestrator-Retry-Robustheit** (aus Plan 2, bewusst zurückgestellt): DB-Session bleibt über den gesamten Retry-Loop offen (bis zu ~90 Min bei Default-Settings); ein fehlgeschlagener Lauf blockiert den nächsten regulären Cron-Termin statt unabhängig davon zu laufen (Abweichung von TECH-SPEC.md §1.3b). Siehe Memory `plan2_known_followups` für Details.

## Nicht-Ziele (dauerhaft außerhalb des Scopes, aus SPECS.md §9)

- Kein direkter E-Mail-Versand an Eltern.
- Kein öffentliches/externes API.
- Keine eigene Passwortverwaltung (Auth läuft über WordPress/LDAP).
