# AbsenzDash — Deployment & lokale Entwicklung

## Backend

Siehe [backend-setup.md](backend-setup.md).

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
4. Für jeden Testnutzer unter **Benutzer → Profil** die Rolle (`klassenlehrkraft` /
   `bereichsleiter` / `schulleitung`) und optional die numerische WebUntis-Lehrkraft-ID setzen. Das
   ist ein Übergangsmechanismus für Tests — die richtige Rollen-/Bereichs-Admin-Oberfläche folgt in
   einem späteren Plan. Diese Felder sind nur für Benutzer mit der Fähigkeit `edit_users` (also
   WordPress-Administratoren) sichtbar/editierbar.
5. Voraussetzung: `npm run build` in `frontend/` mindestens einmal ausgeführt haben — das Build-Ergebnis
   (`wordpress-plugin/absenzdash/assets/spa/`) ist gitignored und existiert bei einem frischen Checkout
   nicht. Danach eine Seite mit dem Shortcode `[absenzdash]` anlegen und aufrufen: das Landing-Dashboard
   mit den Kennzahlen sollte erscheinen — das bestätigt die gesamte Proxy-Kette (WP-Auth → Backend →
   SPA-Rendering).

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

## Netzwerk

Das Backend tritt dem externen Docker-Netzwerk `absenzflow-shared` bei (siehe
`backend/docker-compose.yml`), damit der WordPress-Container es unter dem Service-/Containernamen
`absenzdash-backend` erreicht. Das Netzwerk wird von der WordPress-Staging-`docker-compose.yml`
erzeugt; falls das Backend zuerst gestartet wird, einmalig `docker network create
absenzflow-shared` ausführen.
