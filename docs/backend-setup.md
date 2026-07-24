# Backend-Setup

## Voraussetzungen

- Docker (Python 3.11 läuft ausschließlich containerisiert — auf der Entwicklungsmaschine muss kein Python installiert sein)

## Setup

1. `cp backend/.env.example backend/.env` und `WORDPRESS_PROXY_SECRET` auf einen echten Wert setzen.
2. `docker compose -f backend/docker-compose.yml up -d --build`
3. `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`

Das Backend läuft danach unter `http://localhost:8000`, Health-Check unter `GET /health`.

## Tests

`docker compose -f backend/docker-compose.yml run --rm backend pytest` (benötigt laufende PostgreSQL-Instanz: `docker compose -f backend/docker-compose.yml up -d postgres`). Jeder Test läuft in einer frisch aufgesetzten Datenbank (`tests/conftest.py` erstellt/verwirft alle Tabellen automatisch pro Test).

## Migrationen

Nach jeder Modelländerung: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "<beschreibung>"`, danach `... alembic upgrade head`. Handgeschriebene SQL-Migrationsdateien sind für dieses Projekt bewusst nicht vorgesehen (siehe TECH-SPEC.md Abschnitt 2).

## Aktueller Stand

Dieser Plan (`docs/superpowers/plans/2026-07-24-backend-grundgeruest.md`) deckt das komplette Datenschema (TECH-SPEC.md Abschnitt 2) und die WordPress-Proxy-Authentifizierung ab — noch **keine** WebUntis-Anbindung und noch keine fachlichen REST-Endpunkte (`/students`, `/admin/...`). Beides folgt in separaten Plänen.
