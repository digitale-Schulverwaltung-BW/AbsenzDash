# Backend-Setup

## Voraussetzungen

- Docker (Python 3.11 läuft ausschließlich containerisiert — auf der Entwicklungsmaschine muss kein Python installiert sein)
- Für den WebUntis-Sync: WebUntis-Service-Account-Zugangsdaten, sowie ein lesbar gemountetes Verzeichnis mit der aktuellen ASV-BW-CSV-Exportdatei (siehe unten)

## Setup

1. `cp backend/.env.example backend/.env` und `WORDPRESS_PROXY_SECRET`, `WEBUNTIS_SERVER`/`_SCHOOL`/`_USERNAME`/`_PASSWORD`, `ASV_CSV_PATH` auf echte Werte setzen.
2. `docker compose -f backend/docker-compose.yml up -d --build`
3. `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`

Das Backend läuft danach unter `http://localhost:8000`, Health-Check unter `GET /health`. Der WebUntis-Sync-Job startet automatisch beim Backend-Start (APScheduler, siehe unten) und läuft nach dem in `einstellung.sync_interval_cron` konfigurierten Intervall (Default: alle 30 Minuten).

## Tests

`docker compose -f backend/docker-compose.yml run --rm backend pytest` (benötigt laufende PostgreSQL-Instanz: `docker compose -f backend/docker-compose.yml up -d postgres`). Jeder Test läuft in einer frisch aufgesetzten Datenbank (`tests/conftest.py` erstellt/verwirft alle Tabellen automatisch pro Test). WebUntis-Calls sind in Tests über `respx`/Mocks abgedeckt — keine echte WebUntis-Instanz nötig.

## Migrationen

Nach jeder Modelländerung: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "<beschreibung>"`, danach `... alembic upgrade head`.

## WebUntis-Sync (ab Plan 2)

- **Ablauf:** Klassen/Kategorien-Sync → ASV-BW-CSV-Import (Schüler-Stammdaten/Klassenzuordnung) → Fehlzeiten-/Klassenbuch-Sync, orchestriert in `app/services/sync_orchestrator.py`. Läuft automatisch nach `einstellung.sync_interval_cron` (APScheduler, `app/core/scheduler.py`), Änderungen an diesem Cron-Wert wirken ab dem nächsten Lauf ohne Neustart.
- **ASV-BW-CSV:** `ASV_CSV_PATH` muss auf ein live-gemountetes Verzeichnis zeigen, in das ein externes System die aktuelle Export-Datei unter festem Dateinamen ablegt (TECH-SPEC.md Abschnitt 1.3). Spaltennamen sind über `ASV_CSV_COLUMN_*`-Env-Vars konfigurierbar, falls sie von der Referenzschule abweichen. Der Import überspringt unveränderte Dateien (mtime-Vergleich) — bei einer neuen Datei mit identischem Namen und späterer mtime wird beim nächsten Sync-Lauf automatisch neu importiert.
- **Retry:** Schlägt ein Sync-Lauf fehl (WebUntis nicht erreichbar, CSV nicht lesbar), wird er bis zu `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS`-mal (Default 4) im Abstand von `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` (Default 30) erneut versucht, bevor er endgültig abgebrochen und geloggt wird.
- **Noch nicht abgedeckt:** manueller "Sync jetzt"-Endpunkt, Eskalations-Engine/Benachrichtigungen (beides spätere Pläne).

## Aktueller Stand

Plan 1 (`docs/superpowers/plans/2026-07-24-backend-grundgeruest.md`) deckt das Datenschema und die WordPress-Proxy-Authentifizierung ab. Plan 2 (dieser Plan, `docs/superpowers/plans/2026-07-24-webuntis-sync.md`) ergänzt den vollständigen WebUntis-Sync inkl. ASV-BW-CSV-Import. Noch **keine** fachlichen REST-Endpunkte (`/students`, `/admin/...`) und keine Eskalations-Engine (Schwellwerte, Benachrichtigungen, Maßnahmen) — beides folgt in separaten Plänen.
