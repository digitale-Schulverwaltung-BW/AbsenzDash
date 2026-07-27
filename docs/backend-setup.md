# Backend-Setup

## Voraussetzungen

- Docker (Python 3.11 läuft ausschließlich containerisiert — auf der Entwicklungsmaschine muss kein Python installiert sein)
- Für den WebUntis-Sync: WebUntis-Service-Account-Zugangsdaten, sowie ein lesbar gemountetes Verzeichnis mit der aktuellen ASV-BW-CSV-Exportdatei (siehe unten)

## Setup

1. `cp backend/.env.example backend/.env` und `WORDPRESS_PROXY_SECRET`, `WEBUNTIS_SERVER`/`_SCHOOL`/`_USERNAME`/`_PASSWORD`, `ASV_CSV_PATH`, `SMTP_HOST`, `SMTP_FROM_ADDRESS`, `DASHBOARD_BASE_URL` auf echte Werte setzen (die SMTP-Platzhalter im Beispiel starten den Backend zwar, lassen aber jede Benachrichtigung mit `status="fehler"` fehlschlagen).
2. `docker compose -f backend/docker-compose.yml up -d --build`
3. `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`

Das Backend läuft danach unter `http://localhost:8000`, Health-Check unter `GET /health`. Der WebUntis-Sync-Job startet automatisch beim Backend-Start (APScheduler, siehe unten) und läuft nach dem in `einstellung.sync_interval_cron` konfigurierten Intervall (Default: alle 30 Minuten).

## Tests

`docker compose -f backend/docker-compose.yml run --rm backend pytest` (benötigt laufende PostgreSQL-Instanz: `docker compose -f backend/docker-compose.yml up -d postgres`). Jeder Test läuft in einer frisch aufgesetzten Datenbank (`tests/conftest.py` erstellt/verwirft alle Tabellen automatisch pro Test). WebUntis-Calls sind in Tests über `respx`/Mocks abgedeckt — keine echte WebUntis-Instanz nötig.

## Migrationen

Nach jeder Modelländerung: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "<beschreibung>"`, danach `... alembic upgrade head`.

## Admin-Endpunkte (ab Plan 6)

- **Migration:** Plan 6 bringt eine neue Alembic-Migration mit (`massnahmen_typ.aktiv`) — sie ist im oben beschriebenen `alembic upgrade head` enthalten und muss beim Deploy mitlaufen.
- **`POST /admin/sync-now`** läuft synchron im Request und kann so lange dauern wie ein vollständiger WebUntis-Sync (mehrere Minuten) — Timeouts eines vorgelagerten Reverse-Proxys in der Produktion entsprechend großzügig setzen.
- **`PUT /admin/sync-settings`** plant den APScheduler-Job sofort neu, aber nur im Worker-Prozess, der den Request bearbeitet hat. Beim aktuellen Single-Process-Deployment ist das unkritisch; bei mehreren Backend-Worker-Prozessen würden die übrigen erst nach einem Neustart mit dem neuen Cron-Wert laufen.
- **`aktiv`-Flag** bei Maßnahmen-Typen und Entschuldigungsstatus: reines Anzeige-/Auswahlkriterium für das künftige Frontend, das Backend erzwingt es nicht (siehe TECH-SPEC.md Abschnitt 2).

## PDF-Export (ab Plan 7)

- **`GET /students/{id}/export.pdf`**: liefert ein PDF mit Fehlzeiten-/Klassenbuch-/Maßnahmen-/Ausnahmen-/Benachrichtigungs-Historie eines Schülers. Optionaler `sections`-Query-Parameter (kommasepariert, z.B. `?sections=fehlzeiten,massnahmen`) wählt die enthaltenen Abschnitte aus; ohne Parameter sind alle fünf enthalten. Rollenoffen, aber scope-geprüft wie `GET /students/{id}`.
- **Abhängigkeit:** WeasyPrint benötigt System-Bibliotheken (Pango/Cairo/GDK-Pixbuf), die im mitgelieferten `Dockerfile` bereits installiert werden — bei einem Rebuild des Images (`docker compose -f backend/docker-compose.yml build backend`) ist nichts weiter zu tun.
- **Audit-Log:** jeder Export erzeugt einen `audit_log`-Eintrag (`aktion="export_pdf"`) mit den angeforderten `sections`, da der Export für offizielle Meldungen (§90/Bußgeldverfahren) gedacht ist.

## WebUntis-Sync (ab Plan 2)

- **Ablauf:** Klassen/Kategorien-Sync → ASV-BW-CSV-Import (Schüler-Stammdaten/Klassenzuordnung) → Fehlzeiten-/Klassenbuch-Sync, orchestriert in `app/services/sync_orchestrator.py`. Läuft automatisch nach `einstellung.sync_interval_cron` (APScheduler, `app/core/scheduler.py`), Änderungen an diesem Cron-Wert wirken ab dem nächsten Lauf ohne Neustart.
- **ASV-BW-CSV:** `ASV_CSV_PATH` muss auf ein live-gemountetes Verzeichnis zeigen, in das ein externes System die aktuelle Export-Datei unter festem Dateinamen ablegt (TECH-SPEC.md Abschnitt 1.3). Spaltennamen sind über `ASV_CSV_COLUMN_*`-Env-Vars konfigurierbar, falls sie von der Referenzschule abweichen. Der Import überspringt unveränderte Dateien (mtime-Vergleich) — bei einer neuen Datei mit identischem Namen und späterer mtime wird beim nächsten Sync-Lauf automatisch neu importiert.
- **Retry:** Schlägt ein Sync-Lauf fehl (WebUntis nicht erreichbar, CSV nicht lesbar), wird er bis zu `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS`-mal (Default 4) im Abstand von `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` (Default 30) erneut versucht, bevor er endgültig abgebrochen und geloggt wird.
- **Manueller Anstoß:** `POST /admin/sync-now` (ab Plan 6, nur `schulleitung`) startet einen einzelnen Sync-Versuch sofort — ohne den oben beschriebenen Retry-Loop.

## E-Mail-Benachrichtigungen (ab Plan 4)

- **Config:** `SMTP_HOST`, `SMTP_FROM_ADDRESS`, `DASHBOARD_BASE_URL` sind Pflichtangaben (kein Start ohne sie, siehe `.env.example`). `SMTP_PORT` (Default 587), `SMTP_USER`/`SMTP_PASSWORD` (nur genutzt wenn `SMTP_USER` gesetzt ist) und `SMTP_USE_STARTTLS` (Default `true`) sind optional — für ein internes, unauthentifiziertes Relay `SMTP_USE_STARTTLS=false` und `SMTP_USER` leer lassen.
- **Mailinhalt anpassen:** `backend/app/templates/email_benachrichtigung.txt.default` ist die versionierte Default-Vorlage. Für schulspezifische Anpassungen `backend/app/templates/email_benachrichtigung.txt` anlegen (nicht versioniert, siehe `.gitignore`) — existiert diese Datei, wird sie statt der Default-Vorlage verwendet, ohne Neustart des Backends. Format: erste Zeile = Betreff, danach eine Leerzeile, danach der Mailtext. Verfügbare Platzhalter: `$schueler_vorname`, `$schueler_nachname`, `$klasse`, `$regel_typ`, `$stufe_nr`, `$zaehlerstand`, `$einheit`, `$dashboard_link`.
- **Bekannte Einschränkung:** Schlägt der SMTP-Versand fehl (z.B. Mailserver kurz nicht erreichbar), wird das im Benachrichtigungs-Log als `status="fehler"` vermerkt, aber **nicht automatisch erneut versucht** — durch die "Neuberechnung statt Inkrement"-Architektur des Sync-Jobs (siehe TECH-SPEC.md) würde ein unveränderter Zählerstand im nächsten Lauf ohnehin nicht erneut als "neu erreicht" erkannt. Betroffene Fälle sind im Benachrichtigungs-Log sichtbar und müssen bei Bedarf manuell nachverfolgt werden.

## Aktueller Stand

Plan 1-7 sind abgeschlossen: Backend-Grundgerüst & Datenmodell (Plan 1), WebUntis-Sync inkl. ASV-BW-CSV-Import (Plan 2), Eskalations-Engine mit Schwellwerten/Benachrichtigungen/Maßnahmen (Plan 3), echter E-Mail-Versand (Plan 4), REST-Kern-Endpunkte fürs WP-Plugin (`/students`, Plan 5), die Admin-Konfigurationsendpunkte (`/admin/...`, Plan 6) und der PDF-Export (`/students/{id}/export.pdf`, Plan 7). Noch offen: das Frontend und das WordPress-Plugin selbst (siehe ROADMAP.md, Abschnitt "Geplant").
