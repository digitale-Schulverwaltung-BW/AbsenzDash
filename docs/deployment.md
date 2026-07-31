# AbsenzDash — Deployment & lokale Entwicklung

## Backend

Siehe [backend-setup.md](backend-setup.md).

### Fehlzeit-Daten manuell zurücksetzen

Gelegentlich ist es nötig, den Inhalt der `fehlzeit`-Tabelle manuell zu leeren — z.B. um nach der
Behebung eines Datenkorrektheits-Bugs im Sync (wie der Ganztages-Merge-Fix vom 2026-07-28,
siehe `docs/superpowers/specs/2026-07-28-fehltag-merge-fix-design.md`) fehlerhaft synchronisierte
Altdaten zu entfernen, bevor der nächste Sync sie korrekt neu einliest.

**Wichtig:** Dabei dürfen nicht nur die `fehlzeit`-Zeilen gelöscht werden — `einstellung.letzter_sync_am`
muss im selben Zug auf `NULL` zurückgesetzt werden. Der Grund: `sync_orchestrator._fehlzeiten_zeitraum`
wählt den Start des Sync-Zeitraums als `letzter_sync_am - 1 Tag`, sofern `letzter_sync_am` gesetzt ist,
und fällt nur bei `NULL` auf `einstellung.schuljahr_start_cache` zurück. Wird also nur die Tabelle
geleert, aber `letzter_sync_am` nicht zurückgesetzt, holt der nächste Sync nur die letzten ein bis zwei
Tage aus WebUntis nach — der Rest des Schuljahres fehlt danach stillschweigend, ohne Fehlermeldung.

Beide Schritte gemeinsam ausführen:

```bash
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "TRUNCATE fehlzeit;"
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "UPDATE einstellung SET letzter_sync_am = NULL;"
```

Danach holt der nächste geplante oder manuell ausgelöste Sync (`POST /admin/sync-now`) den vollständigen
Zeitraum ab `einstellung.schuljahr_start_cache` erneut ab.

### Default-Schwellwert-Regeln und Maßnahmen-Katalog

Migration `ecbb0df17a38` seedet bei jedem `alembic upgrade head` (idempotent, `ON CONFLICT`/`NOT EXISTS`-
guarded) zwei produktiv benötigte Grunddaten, ohne die das Dashboard sonst dauerhaft nutzlos bliebe:

- **Default-Maßnahmen-Katalog** aus SPECS.md Abschnitt 4 (Gespräch, Elterngespräch, Nachsitzen,
  4h Nachsitzen, Schulverweis, Bußgeld, Zwangsgeld). War bereits einmal in einer früheren Migration
  (`00e96fea061a`) geseedet worden, die Zeilen wurden aber in mindestens einer Umgebung wieder gelöscht
  (z.B. durch einen DB-Reset ohne Reseed) — Alembic führt eine bereits angewendete Migration nicht erneut
  aus, daher die neue, idempotente Nachhol-Migration.
- **Je eine schulweite Schwellwert-Regel für `fehlzeiten` und `klassenbuch`**, jeweils mit drei Stufen:
  - Fehlzeiten: Stufe 1 ab 4 Fehltagen (Klassenlehrkraft), Stufe 2 ab 8 (+ Bereichsleiter), Stufe 3 ab 12
    (+ Schulleitung); zählt alle Fehltage (`fehlzeiten_filter = 'alle'`, nicht nur unentschuldigte).
  - Klassenbuch: Stufe 1 ab 3 Einträgen, Stufe 2 ab 6, Stufe 3 ab 9, gleiche Rollen-Eskalation.

  **Ohne mindestens eine Regel wird für keinen Schüler jemals ein `schueler_zaehlerstand` angelegt**
  (`pruefe_schwellwerte` in `eskalations_pruefung.py` überspringt Schüler ohne auflösbare Regel komplett) —
  Übersicht und Schüler-Detail zeigen dann bei jedem Schüler dauerhaft „–“ als Zählerstand, unabhängig
  davon, wie viele Fehlzeiten/Klassenbucheinträge tatsächlich vorliegen. Nach dem Seed-Migration-Lauf
  einmal `POST /admin/sync-now` (oder auf den nächsten geplanten Sync warten) auslösen, damit die
  Zählerstände für bereits vorhandene Altdaten nachberechnet werden.

  Diese Werte sind ein **Startpunkt**, keine endgültige Schul-Policy — sobald die Admin-Oberfläche für
  Schwellwert-Regeln gebaut ist (siehe ROADMAP.md, Punkt "Admin-Bereich"), können/sollen sie dort von der
  Schulleitung angepasst werden (`GET`/`PUT /admin/threshold-rules`, bereits seit Plan 6 vorhanden).

## WordPress-Plugin (Mini-Proxy & Shortcode)

Voraussetzung: eine laufende WordPress-Instanz mit einer `docker-compose.yml`, die Plugin-Verzeichnisse
per Volume nach `wp-content/plugins/` mountet (Beispiel, analog zu den Schwesterprojekten
AbsenzFlow/Ondisos):

```yaml
services:
  wordpress:
    volumes:
      - ../AbsenzDash/wordpress-plugin/absenzdash:/var/www/html/wp-content/plugins/absenzdash
```

Danach in WP-Admin:

1. Plugin "AbsenzDash" unter **Plugins** aktivieren.
2. Unter **Einstellungen → Permalinks** eine nicht-"Einfach"-Struktur wählen (z.B. "Beitragsname"),
   sonst funktionieren `/wp-json/...`-URLs nicht.
3. Unter **Einstellungen → AbsenzDash** die Backend-URL (z.B. `http://absenzdash-backend:8000`,
   erreichbar über das gemeinsame `absenzflow-shared`-Docker-Netzwerk) und das Shared Secret
   eintragen — das Secret muss exakt `WORDPRESS_PROXY_SECRET` aus `backend/.env` entsprechen.
4. Rollen-Zuweisung & Bereichsdefinition konfigurieren (siehe Abschnitt unten).
5. Voraussetzung: `npm run build` in `frontend/` mindestens einmal ausgeführt haben — das Build-Ergebnis
   (`wordpress-plugin/absenzdash/assets/spa/`) ist gitignored und existiert bei einem frischen Checkout
   nicht. Danach eine Seite mit dem Shortcode `[absenzdash]` anlegen und aufrufen: das Landing-Dashboard
   mit den Kennzahlen sollte erscheinen — das bestätigt die gesamte Proxy-Kette (WP-Auth → Backend →
   SPA-Rendering).

### Rollen-Zuweisung & Bereichsdefinition

Seit Plan 11 (`docs/superpowers/plans/2026-07-29-wordpress-plugin-rollen-bereiche.md`) ersetzen zwei
dedizierte Admin-Seiten die vorherigen Profilfelder:

- **Einstellungen → AbsenzDash-Rollen**: Rolle (Klassenlehrkraft/Bereichsleiter/Schulleitung) und
  WebUntis-Kürzel je Nutzer, als Listenansicht statt Einzel-Profilbearbeitung. Die Kürzelliste wird
  live aus WebUntis geladen (`GET /admin/webuntis-teachers`) — Backend muss dafür erreichbar sein.
- **Einstellungen → AbsenzDash-Bereiche**: Bereiche anlegen, Klassen zuordnen, Bereichsleiter
  zuweisen. Der Button "Aus WebUntis-Abteilungen vorbefüllen" schlägt einen Bereich pro
  WebUntis-Abteilung vor (reiner Formular-Vorschlag, keine laufende Synchronisation).

Beide Seiten sind nur für WP-Administratoren (`manage_options`) sichtbar und benötigen eine
funktionierende Backend-Verbindung (Options-Seite, siehe oben).

**Kein Self-Lockout mehr:** Der Proxy erkennt WP-Administratoren (`manage_options`) und schickt für
alle `/admin/*`-Aufrufe (Bereiche, Rollen, Schwellwert-Regeln, Maßnahmen-Katalog, Sync-Einstellungen)
immer die Rolle `schulleitung` ans Backend, unabhängig davon, was in `absenzdash_role` gespeichert
ist — auch wenn dort noch nichts oder eine andere Rolle (z. B. `bereichsleiter` zu Vorschauzwecken)
hinterlegt ist. Ein Administrator kann sich damit weder direkt nach der Installation noch durch
Selbstzuweisung einer anderen Rolle aus den AbsenzDash-Einstellungsseiten aussperren. Für alle
übrigen (nicht-`/admin/*`) Aufrufe — also den eigentlichen Dashboard-Zugriff über das Shortcode-SPA —
gilt weiterhin die tatsächlich zugewiesene `absenzdash_role`; Nutzer ohne `manage_options` benötigen
dafür nach wie vor eine echte Rollenzuweisung auf der AbsenzDash-Rollen-Seite, sonst bricht der Proxy
mit HTTP 400 ("Keine Rolle zugewiesen") ab.

## Frontend (React/TS-SPA)

Voraussetzung: Node.js (getestet mit v24) und npm.

**Produktions-Build** (schreibt direkt nach `wordpress-plugin/absenzdash/assets/spa/`):

```bash
cd frontend
npm install
npm run build
```

**Lokale Entwicklung mit Hot-Module-Reload** gegen die echte WordPress-Instanz (Nonce/Session/Backend-Daten
sind sonst nicht nutzbar, siehe TECH-SPEC.md §3):

1. In `wp-config.php` der WordPress-Instanz eine Konstante setzen, die auf den laufenden Vite-Dev-Server zeigt:
   ```php
   define( 'ABSENZDASH_VITE_DEV_SERVER', 'http://localhost:5173' );
   ```
2. Den Vite-Dev-Server starten: `cd frontend && npm run dev`
3. Die Seite mit dem `[absenzdash]`-Shortcode im Browser öffnen — das Plugin lädt jetzt das Vite-Dev-Server-Skript
   statt der gebauten Dateien; Änderungen am Code werden per HMR live übernommen.
4. Die Konstante vor jedem Produktions-Deployment wieder entfernen bzw. auskommentieren.

Ohne WordPress-Einbindung kann `npm run dev` auch standalone geöffnet werden (`http://localhost:5173`) für
schnelle UI-Iteration ohne echte Backend-Daten (siehe `frontend/index.html`).

### Bekannte Einschränkung: Deep Links auf /schueler und /schueler/:id

Die SPA nutzt `BrowserRouter` (siehe `frontend/src/main.tsx`), matcht also echte Pfade wie
`/absenzdash/schueler/7` gegen `location.pathname`. In-App-Navigation über `<Link to="/schueler/:id">`
(Schülerliste → Schüler-Detail) funktioniert problemlos, weil dabei nie ein echter Page-Load ausgelöst
wird. Ein Lesezeichen, ein Browser-Reload auf der Detailseite oder ein weitergegebener Link auf
`/schueler` bzw. `/schueler/:id` gehen dagegen direkt an WordPress — dafür existiert aktuell keine
Rewrite-Regel, die WordPress-Instanz liefert also ein 404 statt die SPA zu laden.

Noch offen, vor einer Nutzung außerhalb der In-App-Navigation zu klären: entweder eine WordPress-
Rewrite-Regel für diese SPA-internen Pfade ergänzen, oder von `BrowserRouter` auf `HashRouter`
umstellen (dann laufen alle SPA-Routen unter einem einzigen WordPress-Pfad mit `#`-Fragment, das der
Server nie sieht).

## Netzwerk

Das Backend tritt dem externen Docker-Netzwerk `absenzflow-shared` bei (siehe
`backend/docker-compose.yml`), damit der WordPress-Container es unter dem Service-/Containernamen
`absenzdash-backend` erreicht. Das Netzwerk wird von der WordPress-Staging-`docker-compose.yml`
erzeugt; falls das Backend zuerst gestartet wird, einmalig `docker network create
absenzflow-shared` ausführen.
