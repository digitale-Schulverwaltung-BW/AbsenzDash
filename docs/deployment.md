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
5. Eine Seite mit dem Shortcode `[absenzdash]` anlegen, um die Proxy-Kette per Smoke-Test-Ansicht
   zu prüfen (Button "GET /students laden").

## Netzwerk

Das Backend tritt dem externen Docker-Netzwerk `absenzflow-shared` bei (siehe
`backend/docker-compose.yml`), damit der WordPress-Container es unter dem Service-/Containernamen
`absenzdash-backend` erreicht. Das Netzwerk wird von der WordPress-Staging-`docker-compose.yml`
erzeugt; falls das Backend zuerst gestartet wird, einmalig `docker network create
absenzflow-shared` ausführen.
