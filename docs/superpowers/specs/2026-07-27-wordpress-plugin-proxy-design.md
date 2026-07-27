# Design: WordPress-Plugin — Mini-Proxy & Shortcode

Stand: 2026-07-27

## Kontext & Motivation

SPECS.md/ROADMAP.md sahen als nächsten Schritt "Frontend: React/TS-SPA" vor, gefolgt vom
WordPress-Plugin. Beim Brainstorming zeigte sich: die SPA kann laut TECH-SPEC.md §3 nicht direkt
mit dem Backend sprechen, weil die Trusted-Header (`X-WordPress-*`) serverseitig vom WP-Plugin
gesetzt werden müssen, nicht vom Browser. Ohne WP-Plugin bräuchte die SPA-Entwicklung einen
Dev-Auth-Stub (Backend-Dev-Modus, lokaler Mini-Proxy oder komplett gemockte API) — reine
Blindleistung, die beim späteren echten Plugin wieder verworfen würde.

**Entscheidung:** Reihenfolge umdrehen. Dieser Plan baut zuerst ein bewusst kleines WordPress-Plugin
(Reverse-Proxy + Shortcode-Grundgerüst), gegen das die eigentliche SPA (nächster Plan) dann von
Anfang an real entwickelt wird. Die volle Rollen-/Bereichs-Admin-Oberfläche (Roadmap-Punkt 2/3)
bleibt bewusst ausgeklammert.

**Scope-Abgrenzung:**
- ✅ Reverse-Proxy (WP-REST-Route → FastAPI-Backend mit Trusted-Headern)
- ✅ Shortcode mit sichtbarer Smoke-Test-Debug-Ansicht (Beweis der kompletten Kette)
- ✅ Backend-URL/Shared-Secret-Konfiguration (WP-Options-Seite)
- ✅ Minimale Profilfelder für `absenzdash_role`/`absenzdash_webuntis_code` (Test-Zwecke)
- ❌ Bereichsdefinition-Admin-Seite (Roadmap-Punkt 2)
- ❌ Vollwertige Rollen-Zuweisungs-Oberfläche (Roadmap-Punkt 2)
- ❌ Die eigentliche React/TS-SPA (folgt als eigener Plan, entwickelt sich gegen dieses Plugin)
- ❌ Excuse-Status-Admin-Pflege (Roadmap-Punkt 3)

## Architektur & Verzeichnisstruktur

Neuer Ordner `wordpress-plugin/absenzdash/` im Repo, analog zu `backend/`. Reines PHP, kein
Build-Tooling — die Smoke-Test-Ansicht kommt mit Vanilla-JS/`fetch` aus.

```
wordpress-plugin/absenzdash/
  absenzdash.php              # Plugin-Bootstrap (Plugin-Header, lädt Klassen, registriert Hooks)
  includes/
    class-optionen.php        # Settings-Seite: Backend-URL + Shared Secret (WP Options API)
    class-proxy.php           # REST-Route, generischer Passthrough ans Backend
    class-shortcode.php       # [absenzdash]-Shortcode, rendert Smoke-Test-Debug-Ansicht
    class-benutzerprofil.php  # minimale Profilfelder für absenzdash_role/-webuntis_code
```

**Namenskonvention:** Die bereits in TECH-SPEC.md §3/§4 fixierten Wire-Contract-Namen (HTTP-Header
`X-WordPress-*`, Meta-Keys `absenzdash_role`/`absenzdash_webuntis_code`, Rollenwerte
`klassenlehrkraft`/`bereichsleiter`/`schulleitung`) bleiben unverändert — bereits dokumentierter
Vertrag mit dem Backend (siehe `backend/app/api/deps.py`). Deutsch kommt bei allem zum Tragen, was
neu entschieden wird: Klassennamen (s.o.), Kommentare, Options-Feldbezeichnungen im Settings-Screen.

## Auth- & Proxy-Datenfluss

1. Browser lädt die Shortcode-Seite (bestehende WP-Session/Cookie, kein zusätzlicher Login).
2. JS im Shortcode ruft `fetch('/wp-json/absenzdash/v1/api/{path}', {headers: {'X-WP-Nonce': ...}})`
   — Nonce kommt per `wp_localize_script`, WP-Standard für eingeloggte REST-Zugriffe.
3. `register_rest_route()`: `permission_callback` prüft `is_user_logged_in()`. Kein Rollen-Check
   auf WP-Seite — das bleibt vollständig im Backend (Scope-Prüfung über
   `nutzer_klasse`/`nutzer_bereich`, siehe `backend/app/api/deps.py`).
4. Handler baut die Trusted-Header aus dem aktuellen WP-User + Meta:
   - `X-WordPress-Secret` — aus den Plugin-Optionen (serverseitig, nie im Browser sichtbar)
   - `X-WordPress-User` — `(string) $user->ID`
   - `X-WordPress-Email` / `X-WordPress-Name` — `$user->user_email` / `$user->display_name`
   - `X-WordPress-Role` — `get_user_meta($user->ID, 'absenzdash_role', true)`
   - `X-WordPress-WebUntis-Code` — optionales Meta, nur gesetzt wenn vorhanden
5. Ist `absenzdash_role` leer (Nutzer noch nicht zugewiesen), antwortet der Proxy direkt mit `400`
   ("Keine Rolle zugewiesen") statt einen leeren Header ans Backend zu schicken, der dort in ein
   generisches `Unknown role: ` münden würde (siehe `deps.py:50-51`).
6. Weiterleitung per `wp_remote_request()` an `{backend_url}{path}`, Methode/Query/Body 1:1
   durchgereicht; Response (Status-Code, Body, `Content-Type`) 1:1 zurück an den Browser — inkl.
   `application/pdf` für den späteren Export (Body wird als Rohstring ohne Charset-Reencoding
   durchgereicht).
7. Ist das Backend nicht erreichbar (`wp_remote_request()` liefert `WP_Error`), antwortet der Proxy
   mit `502` + JSON-Fehlermeldung statt eines rohen PHP-Fehlers.
8. Ein `401` vom Backend (Secret-Mismatch) wird unverändert durchgereicht.

Der Proxy-Pfad ist ein **generischer Passthrough**, kein Allowlist pro Endpunkt — neue
Backend-Endpunkte brauchen keine Plugin-Änderung. Autorisierung bleibt vollständig serverseitig im
FastAPI-Backend.

## Rollen-Setzung (Minimal-Profilfeld)

`show_user_profile`/`edit_user_profile`-Hooks hängen zwei einfache Felder in den Standard-WP-
Benutzerprofil-Bildschirm:
- `absenzdash_role` als Dropdown mit den drei erlaubten Werten (`klassenlehrkraft`,
  `bereichsleiter`, `schulleitung`)
- `absenzdash_webuntis_code` als Freitext (optional)

Kein eigenes Admin-Menü, kein Styling — reiner Zweck: End-to-End-Tests mit verschiedenen Rollen
fahren können, bis Roadmap-Punkt 2 das durch die richtige Bereichs-/Rollen-Admin-Seite ersetzt.

## Shortcode `[absenzdash]` — Smoke-Test-Debug-Ansicht

Rendert eine simple, unstylische Ausgabe:
- Login-Status + aufgelöste Rolle (serverseitig aus `get_user_meta`)
- Ein "GET /students laden"-Button, der per JS über den Proxy `GET /students` aufruft und das
  Roh-JSON anzeigt
- Fehlerfälle sichtbar als Text (401/400/502), kein Silent-Fail

Das beweist die komplette Kette (WP-Login → Nonce → Proxy → Trusted-Header → Backend →
Scope-gefiltertes JSON) sichtbar im Browser. Der nächste Plan (SPA) ersetzt diese Debug-Ansicht
durch den echten SPA-Mount-Point (leeres Div + Asset-Enqueue).

## Konfiguration (Options-Seite)

Einfache Settings-Seite (`add_options_page`) mit zwei Feldern: Backend-URL, Shared Secret.
Gespeichert als serialisiertes Array via WP Options API (`absenzdash_optionen`), analog zum in
TECH-SPEC.md §4 beschriebenen VertretungsFlow-Muster (`absenzflow_options`).

## Backend-Netzwerk-Ergänzung

`backend/docker-compose.yml` bekommt den `backend`-Service zusätzlich im
`absenzflow-shared`-Netzwerk (externes Docker-Netzwerk, bereits in TECH-SPEC.md §6 vorgesehen),
damit der WP-Container ihn per Service-Name erreicht (z.B. `http://absenzdash-backend:8000`) statt
über `host.docker.internal`. Näher an der späteren Produktions-Netzwerktopologie, direkt lokal
gegen die vorhandene Staging-WP-Instanz testbar.

## Testing

Kein PHPUnit für dieses dünne Plugin (YAGNI) — Verifikation läuft manuell über die
Staging-WP-Instanz:
- Smoke-Test-Ansicht mit verschiedenen Rollen durchspielen (`klassenlehrkraft` sieht nur eigene
  Klasse, `schulleitung` sieht alle)
- Falsches Secret → `401`
- Backend gestoppt → `502`
- Kein `absenzdash_role`-Meta gesetzt → `400` mit klarer Meldung

Das Backend hat bereits volle Testabdeckung für die eigentliche Business-Logik; dieses Plugin ist
reine Transport-/Auth-Schicht ohne eigene Fachlogik.

## Dokumentation (gemäß CLAUDE.md)

Neue Datei `docs/deployment.md` mit:
- Volume-Mount-Zeile für die externe `docker-compose.yml` der WP-Staging-Instanz
  (`../AbsenzDash/wordpress-plugin/absenzdash:/var/www/html/wp-content/plugins/absenzdash`)
- Hinweis auf die `absenzflow-shared`-Netzwerk-Erweiterung im Backend
- Einrichtung der Plugin-Optionen (Backend-URL/Secret)
- Setzen der minimalen Profilfelder pro Test-Nutzer

ROADMAP.md wird nach Abschluss aktualisiert: neuer abgeschlossener Punkt "Plan 8 — WordPress-Plugin
Mini-Proxy & Shortcode", mit Anmerkung zur Reihenfolge-Umkehr (Plugin-Proxy vor SPA) und Begründung
(Vermeidung von Dev-Auth-Blindleistung).

## Offene Punkte für den nächsten Plan (SPA)

- Shortcode-Rendering wird von Debug-Ansicht auf echten SPA-Mount-Point + Asset-Enqueue umgestellt
- Bereichsdefinition- und vollwertige Rollen-Admin-Seite bleiben separate spätere Pläne
  (Roadmap-Punkt 2/3)
