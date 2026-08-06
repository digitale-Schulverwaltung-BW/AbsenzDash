# AbsenzDash für Administratoren

Diese Anleitung richtet sich an IT-erfahrene Administratoren, die AbsenzDash technisch betreiben (Deployment, Server-Konfiguration, WebUntis-/SMTP-Anbindung, Troubleshooting). Für die fachliche Konfiguration (Schwellwerte, Maßnahmen-Katalog, Rollen-Zuweisung, Bereichsdefinition) siehe [SL.md](SL.md) — diese Aufgaben liegen bei der Schulleitung, nicht bei der IT.

## Architekturüberblick

- **Frontend:** React/TypeScript-SPA, ausgeliefert als WordPress-Plugin (`wordpress-plugin/absenzdash/`), per Shortcode `[absenzdash]` in eine bestehende WP-Seite eingebunden.
- **Backend:** eigenständiger FastAPI-Server im Schul-Intranet (`backend/`), **ohne** Internet-Zugriff erreichbar.
- **Datenbank:** PostgreSQL.
- **Auth:** läuft vollständig über WordPress (lokal oder LDAP/AD); das Backend selbst hat keine eigene Nutzerverwaltung. WordPress und Backend kommunizieren über ein gemeinsames Secret (`WORDPRESS_PROXY_SECRET`).
- **WebUntis-Anbindung:** ein zentraler WebUntis-Service-Account, periodischer Sync-Job im Backend (APScheduler).
- **Referenzarchitektur:** analog zum Schwesterprojekt [VertretungsFlow](https://github.com/digitale-Schulverwaltung-BW/VertretungsFlow) (gleiche Schule).

Details zu Datenmodell und API-Vertrag: [TECH-SPEC.md](../TECH-SPEC.md). Fachlicher Gesamtüberblick: [SPECS.md](../SPECS.md).

## Setup & Deployment

Die vollständige technische Anleitung (Backend per Docker Compose, Datenbank-Migrationen, WordPress-Plugin-Einbindung, Frontend-Build, Netzwerk-Konfiguration) steht in:

- [backend-setup.md](backend-setup.md) — Backend-Voraussetzungen, Setup, Tests, Migrationen, Aktueller Stand
- [deployment.md](deployment.md) — Deployment/lokale Entwicklung für Backend, WordPress-Plugin und Frontend, inkl. Netzwerk-Konfiguration (`absenzflow-shared`-Docker-Netzwerk)
- [ci-cd-setup.md](ci-cd-setup.md) — Test-Pipeline (GitLab CI/CD)

Kurzfassung des Ablaufs bei einer Neuinstallation:

1. Backend: `.env` aus `.env.example` befüllen (siehe unten), `docker compose up -d --build`, dann `alembic upgrade head`.
2. WordPress: Plugin-Verzeichnis mounten, Plugin aktivieren, Permalink-Struktur auf nicht-"Einfach" stellen.
3. Backend-URL und Shared Secret im WP-Backend eintragen (siehe unten).
4. Rollen-Zuweisung & Bereichsdefinition — organisatorisch, wird von der Schulleitung gepflegt (siehe [SL.md](SL.md)), technische Voraussetzung ist nur eine funktionierende Backend-Verbindung.
5. Frontend bauen (`npm run build` in `frontend/`), Shortcode-Seite anlegen, aufrufen und prüfen, dass das Dashboard erscheint.

## WordPress-Plugin-Verbindung

![Backend-URL und Shared Secret](Screenshots/06-1-Backend-WP-AbsenzDash.png)

Unter **Einstellungen → AbsenzDash** im WP-Backend:

- **Backend-URL** — z.B. `http://absenzdash-backend:8000`, erreichbar über das gemeinsame Docker-Netzwerk `absenzflow-shared`.
- **Shared Secret** — muss exakt `WORDPRESS_PROXY_SECRET` aus `backend/.env` entsprechen. Ohne korrektes Secret schlägt jede Anfrage vom Plugin ans Backend fehl.
- **Test-E-Mail senden** — verschickt eine Test-Mail an die Adresse des eingeloggten WP-Nutzers und prüft damit direkt die SMTP-Konfiguration (`SMTP_*` in `backend/.env`), unabhängig von der eigentlichen Eskalations-Engine. Guter erster Schritt bei Problemen mit E-Mail-Benachrichtigungen.

**Kein Self-Lockout:** WP-Administratoren (`manage_options`) werden vom Proxy für alle `/admin/*`-Aufrufe automatisch als `schulleitung` erkannt, unabhängig von der tatsächlich zugewiesenen AbsenzDash-Rolle. Für den eigentlichen Dashboard-Zugriff (Shortcode-SPA) ist dagegen immer eine echte Rollenzuweisung nötig (siehe [SL.md](SL.md)) — ohne sie liefert der Proxy HTTP 400 ("Keine Rolle zugewiesen").

## WebUntis-Sync — technische Seite

Der Sync-Ablauf (Klassen/Kategorien → ASV-BW-CSV-Import → Fehlzeiten/Klassenbuch, orchestriert in `app/services/sync_orchestrator.py`) läuft automatisch nach dem in den Sync-Einstellungen konfigurierten Intervall (siehe [SL.md](SL.md) für die fachliche Konfigurationsoberfläche). Als IT-Administrator verantworten Sie die zugrundeliegende Infrastruktur:

- **WebUntis-Zugangsdaten:** `WEBUNTIS_SERVER`/`_SCHOOL`/`_USERNAME`/`_PASSWORD` in `backend/.env`.
- **ASV-BW-CSV-Import:** `ASV_CSV_PATH` muss auf ein live gemountetes Verzeichnis zeigen, in das ein externes System die aktuelle Export-Datei unter festem Dateinamen ablegt. Spaltennamen sind über `ASV_CSV_COLUMN_*`-Env-Vars anpassbar, falls sie von der Referenzschule abweichen. Unveränderte Dateien (per mtime-Vergleich) werden übersprungen.
- **Retry-Verhalten:** schlägt ein Sync-Lauf fehl (WebUntis nicht erreichbar, CSV nicht lesbar), wird er bis zu `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS`-mal (Default 4) im Abstand von `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` (Default 30) erneut versucht, bevor er endgültig abbricht und geloggt wird.
- **Manueller Einzel-Sync:** `POST /admin/sync-now` (bzw. der Button "Sync jetzt ausführen" im Dashboard, siehe [SL.md](SL.md)) läuft **synchron im Request ohne den obigen Retry-Loop** und kann mehrere Minuten dauern — Timeouts eines vorgelagerten Reverse-Proxys in Produktion entsprechend großzügig setzen.

## E-Mail-Versand

- Pflichtangaben in `backend/.env`: `SMTP_HOST`, `SMTP_FROM_ADDRESS`, `DASHBOARD_BASE_URL` (Backend startet ohne diese nicht). Optional: `SMTP_PORT` (Default 587), `SMTP_USER`/`SMTP_PASSWORD`, `SMTP_USE_STARTTLS` (Default `true`; bei einem internen, unauthentifizierten Relay `false` setzen und `SMTP_USER` leer lassen).
- **Bekannte Einschränkung:** Schlägt der SMTP-Versand fehl, wird das im Benachrichtigungs-Log als `status="fehler"` vermerkt, aber **nicht automatisch erneut versucht** — betroffene Fälle sind im Dashboard sichtbar (siehe [KL.md](KL.md), Abschnitt "Benachrichtigungen") und müssen bei Bedarf manuell nachverfolgt werden.
- Mailinhalt anpassen: `backend/app/templates/email_benachrichtigung.txt.default` ist die versionierte Default-Vorlage; für schulspezifische Anpassungen `backend/app/templates/email_benachrichtigung.txt` anlegen (nicht versioniert, wirkt ohne Neustart).

## Monitoring & Troubleshooting

- **Health-Check:** `GET /health` am Backend.
- **Migrationen:** nach jedem Update `docker compose run --rm backend alembic upgrade head` ausführen (siehe [backend-setup.md](backend-setup.md)).
- **Tests:** `docker compose run --rm backend pytest` (Backend), siehe [ci-cd-setup.md](ci-cd-setup.md) für die CI-Pipeline und häufige lokale Fehlerquellen (z.B. "database connection refused").
- **PDF-Export-Abhängigkeit:** WeasyPrint benötigt Pango/Cairo/GDK-Pixbuf, bereits im mitgelieferten `Dockerfile` installiert — nach einem Image-Rebuild ist nichts weiter zu tun.
- **Deep Links auf `/schueler` und `/schueler/:id`:** funktionieren nur bei In-App-Navigation. Ein direkter Aufruf, Reload oder weitergegebener Link auf diese Pfade liefert aktuell ein WordPress-404, da keine passende Rewrite-Regel existiert (siehe [deployment.md](deployment.md)).

## Datenschutz & Betrieb

- Kein Internet-Zugriff auf das Backend — Kommunikation ausschließlich innerhalb des Schul-Intranets.
- Aufbewahrung der Daten mindestens bis Schuljahresende bzw. bis Schulabschluss des Schülers; danach Löschung/Archivierung möglich.
- Jede Änderung an Maßnahmen und Ausnahmen sowie jeder PDF-Export wird im Audit-Log protokolliert.
- Die Einführung der automatisierten Verarbeitung sollte organisatorisch (nicht technisch) in das Verfahrensverzeichnis der Schule (Art. 30 DSGVO) aufgenommen werden — Zuständigkeit liegt bei der Schulleitung (siehe [SL.md](SL.md)).
