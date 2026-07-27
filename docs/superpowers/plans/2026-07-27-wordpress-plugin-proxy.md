# WordPress-Plugin — Mini-Proxy & Shortcode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein schlankes WordPress-Plugin bauen, das als Reverse-Proxy (Trusted-Header ans FastAPI-Backend) und Shortcode-Grundgerüst dient, damit die spätere React-SPA von Anfang an gegen echte WP-Plugin-Auth entwickelt werden kann statt gegen einen Dev-Stub.

**Architecture:** Reines PHP-Plugin (`wordpress-plugin/absenzdash/`) mit vier fokussierten Klassen (Optionen, Proxy, Shortcode, Benutzerprofil). Der Proxy ist ein generischer WP-REST-Route-Passthrough, der eingeloggte WP-User per `wp_remote_request()` mit Trusted-Headern ans Backend weiterreicht — Autorisierung/Scope bleibt vollständig im Backend (`backend/app/api/deps.py`).

**Tech Stack:** WordPress-Plugin-API (PHP, kein Composer/Build-Tooling), WP REST API, Vanilla-JS für die Smoke-Test-Ansicht.

## Global Constraints

- Wire-Contract-Namen bleiben exakt wie in TECH-SPEC.md §3/§4 und `backend/app/api/deps.py` dokumentiert: HTTP-Header `X-WordPress-Secret`/`-User`/`-Email`/`-Name`/`-Role`/`-WebUntis-Code`, User-Meta-Keys `absenzdash_role`/`absenzdash_webuntis_code`, Rollenwerte `klassenlehrkraft`/`bereichsleiter`/`schulleitung`.
- Neue, projekteigene Bezeichner (Klassennamen, Kommentare, UI-Texte) sind deutsch, siehe Design-Dok.
- Kein PHPUnit für dieses Plugin (YAGNI) — jede Task wird manuell auf der bereits vorhandenen WP-Staging-Instanz (`localhost:8080`) verifiziert, siehe Design-Dok.
- Proxy ist ein generischer Passthrough (kein Endpunkt-Allowlist) — Autorisierung/Scope bleibt vollständig im Backend.
- Commit-Messages auf Englisch (Nutzer-Konvention aus globaler CLAUDE.md).
- Design-Referenz: [docs/superpowers/specs/2026-07-27-wordpress-plugin-proxy-design.md](../specs/2026-07-27-wordpress-plugin-proxy-design.md).

## Voraussetzungen (einmalig, vor Task 1)

Diese Schritte sind manuell auf der WP-Staging-Instanz (`http://localhost:8080`) durchzuführen, bevor mit Task 1 begonnen wird:

1. WP-Admin öffnen, unter **Einstellungen → Permalinks** die Struktur auf "Beitragsname" (oder eine andere nicht-"Einfach"-Option) stellen und speichern. Ohne das liefert `/wp-json/...` einen 404, weil WordPress dann nur die Query-String-Form `?rest_route=/...` unterstützt (unser Proxy-Code behandelt beide Formen, aber die Browser-Tests in diesem Plan nutzen die hübsche Form).
2. Sicherstellen, dass mindestens ein Testnutzer mit Administrator-Rechten eingeloggt werden kann.

## Task 1: Plugin-Grundgerüst & Bootstrap

**Files:**
- Create: `wordpress-plugin/absenzdash/absenzdash.php`
- Create: `wordpress-plugin/absenzdash/includes/class-optionen.php`
- Create: `wordpress-plugin/absenzdash/includes/class-proxy.php`
- Create: `wordpress-plugin/absenzdash/includes/class-shortcode.php`
- Create: `wordpress-plugin/absenzdash/includes/class-benutzerprofil.php`

**Interfaces:**
- Produces: vier PHP-Klassen `Absenzdash_Optionen`, `Absenzdash_Proxy`, `Absenzdash_Shortcode`, `Absenzdash_Benutzerprofil` (in diesem Task nur leere Konstruktoren als Stubs — Task 2–5 füllen sie), instanziiert über `plugins_loaded`.

- [ ] **Step 1: Bootstrap-Datei erstellen**

`wordpress-plugin/absenzdash/absenzdash.php`:

```php
<?php
/**
 * Plugin Name: AbsenzDash
 * Description: Reverse-Proxy und Shortcode-Einbindung fuer die AbsenzDash-SPA im Schulintranet.
 * Version: 0.1.0
 * Author: HHS Karlsruhe
 * License: GPL-2.0-or-later
 * Text Domain: absenzdash
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'ABSENZDASH_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'ABSENZDASH_PLUGIN_URL', plugin_dir_url( __FILE__ ) );
define( 'ABSENZDASH_VERSION', '0.1.0' );

require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-optionen.php';
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-proxy.php';
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-shortcode.php';
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-benutzerprofil.php';

add_action(
	'plugins_loaded',
	function () {
		new Absenzdash_Optionen();
		new Absenzdash_Proxy();
		new Absenzdash_Shortcode();
		new Absenzdash_Benutzerprofil();
	}
);
```

- [ ] **Step 2: Stub-Klassen erstellen**

`wordpress-plugin/absenzdash/includes/class-optionen.php`:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Optionen {
	public function __construct() {}
}
```

`wordpress-plugin/absenzdash/includes/class-proxy.php`:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Proxy {
	public function __construct() {}
}
```

`wordpress-plugin/absenzdash/includes/class-shortcode.php`:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Shortcode {
	public function __construct() {}
}
```

`wordpress-plugin/absenzdash/includes/class-benutzerprofil.php`:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Benutzerprofil {
	public function __construct() {}
}
```

- [ ] **Step 3: Manuell verifizieren**

Voraussetzung: das Plugin-Verzeichnis dieses Repos (`wordpress-plugin/absenzdash/`) ist in der externen WP-Staging-`docker-compose.yml` als Volume nach `/var/www/html/wp-content/plugins/absenzdash` gemountet (siehe Task 7, Dokumentation — falls das noch nicht eingerichtet ist, jetzt einmalig manuell nachziehen, damit ab hier getestet werden kann).

In WP-Admin unter **Plugins** nach "AbsenzDash" suchen und aktivieren.
Erwartet: Aktivierung ohne PHP-Fehler/White-Screen, Plugin erscheint als "Aktiv".

- [ ] **Step 4: Commit**

```bash
git add wordpress-plugin/absenzdash/
git commit -m "feat: add AbsenzDash WordPress plugin skeleton"
```

## Task 2: Backend-URL/Secret-Konfiguration (Options-Seite)

**Files:**
- Modify: `wordpress-plugin/absenzdash/includes/class-optionen.php`

**Interfaces:**
- Consumes: nichts (steht am Anfang der Kette)
- Produces: `Absenzdash_Optionen::get_backend_url(): string`, `Absenzdash_Optionen::get_shared_secret(): string` — beide von `Absenzdash_Proxy` (Task 4) konsumiert. Option gespeichert unter Key `absenzdash_optionen` als Array `['backend_url' => ..., 'shared_secret' => ...]`.

- [ ] **Step 1: Optionen-Klasse implementieren**

`wordpress-plugin/absenzdash/includes/class-optionen.php` komplett ersetzen:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Optionen {

	const OPTION_KEY = 'absenzdash_optionen';

	public function __construct() {
		add_action( 'admin_menu', array( $this, 'registriere_menu' ) );
		add_action( 'admin_init', array( $this, 'registriere_einstellungen' ) );
	}

	public static function get_backend_url(): string {
		$optionen = get_option( self::OPTION_KEY, array() );
		return isset( $optionen['backend_url'] ) ? rtrim( $optionen['backend_url'], '/' ) : '';
	}

	public static function get_shared_secret(): string {
		$optionen = get_option( self::OPTION_KEY, array() );
		return isset( $optionen['shared_secret'] ) ? $optionen['shared_secret'] : '';
	}

	public function registriere_menu(): void {
		add_options_page(
			'AbsenzDash',
			'AbsenzDash',
			'manage_options',
			'absenzdash',
			array( $this, 'render_seite' )
		);
	}

	public function registriere_einstellungen(): void {
		register_setting(
			'absenzdash_optionen_gruppe',
			self::OPTION_KEY,
			array( $this, 'sanitize_optionen' )
		);
	}

	public function sanitize_optionen( $eingabe ): array {
		return array(
			'backend_url'   => isset( $eingabe['backend_url'] ) ? esc_url_raw( trim( $eingabe['backend_url'] ) ) : '',
			'shared_secret' => isset( $eingabe['shared_secret'] ) ? sanitize_text_field( trim( $eingabe['shared_secret'] ) ) : '',
		);
	}

	public function render_seite(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		$optionen = get_option( self::OPTION_KEY, array() );
		?>
		<div class="wrap">
			<h1>AbsenzDash-Einstellungen</h1>
			<form method="post" action="options.php">
				<?php settings_fields( 'absenzdash_optionen_gruppe' ); ?>
				<table class="form-table">
					<tr>
						<th scope="row"><label for="absenzdash_backend_url">Backend-URL</label></th>
						<td>
							<input type="url" id="absenzdash_backend_url" name="<?php echo esc_attr( self::OPTION_KEY ); ?>[backend_url]"
								value="<?php echo esc_attr( $optionen['backend_url'] ?? '' ); ?>" class="regular-text"
								placeholder="http://absenzdash-backend:8000" />
						</td>
					</tr>
					<tr>
						<th scope="row"><label for="absenzdash_shared_secret">Shared Secret</label></th>
						<td>
							<input type="text" id="absenzdash_shared_secret" name="<?php echo esc_attr( self::OPTION_KEY ); ?>[shared_secret]"
								value="<?php echo esc_attr( $optionen['shared_secret'] ?? '' ); ?>" class="regular-text" />
						</td>
					</tr>
				</table>
				<?php submit_button(); ?>
			</form>
		</div>
		<?php
	}
}
```

- [ ] **Step 2: Manuell verifizieren**

In WP-Admin unter **Einstellungen → AbsenzDash** öffnen. Backend-URL `http://absenzdash-backend:8000` und ein Secret (identisch zu `WORDPRESS_PROXY_SECRET` in `backend/.env`) eintragen, speichern, Seite neu laden.
Erwartet: beide Werte bleiben nach dem Reload sichtbar (aus `wp_options` gelesen).

- [ ] **Step 3: Commit**

```bash
git add wordpress-plugin/absenzdash/includes/class-optionen.php
git commit -m "feat: add backend URL and shared secret settings page"
```

## Task 3: Rollen-Profilfelder (Test-Zuweisung)

**Files:**
- Modify: `wordpress-plugin/absenzdash/includes/class-benutzerprofil.php`

**Interfaces:**
- Consumes: nichts
- Produces: User-Meta `absenzdash_role` (einer von `klassenlehrkraft`/`bereichsleiter`/`schulleitung` oder leer) und `absenzdash_webuntis_code` (String oder leer), gelesen von `Absenzdash_Proxy` (Task 4) und `Absenzdash_Shortcode` (Task 5).

- [ ] **Step 1: Profilfelder-Klasse implementieren**

`wordpress-plugin/absenzdash/includes/class-benutzerprofil.php` komplett ersetzen:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Benutzerprofil {

	const ROLLEN = array( 'klassenlehrkraft', 'bereichsleiter', 'schulleitung' );

	public function __construct() {
		add_action( 'show_user_profile', array( $this, 'render_felder' ) );
		add_action( 'edit_user_profile', array( $this, 'render_felder' ) );
		add_action( 'personal_options_update', array( $this, 'speichere_felder' ) );
		add_action( 'edit_user_profile_update', array( $this, 'speichere_felder' ) );
	}

	public function render_felder( WP_User $user ): void {
		$rolle         = get_user_meta( $user->ID, 'absenzdash_role', true );
		$webuntis_code = get_user_meta( $user->ID, 'absenzdash_webuntis_code', true );
		?>
		<h2>AbsenzDash</h2>
		<table class="form-table">
			<tr>
				<th><label for="absenzdash_role">Rolle</label></th>
				<td>
					<select name="absenzdash_role" id="absenzdash_role">
						<option value="">(keine)</option>
						<?php foreach ( self::ROLLEN as $moegliche_rolle ) : ?>
							<option value="<?php echo esc_attr( $moegliche_rolle ); ?>" <?php selected( $rolle, $moegliche_rolle ); ?>>
								<?php echo esc_html( $moegliche_rolle ); ?>
							</option>
						<?php endforeach; ?>
					</select>
				</td>
			</tr>
			<tr>
				<th><label for="absenzdash_webuntis_code">WebUntis-Code</label></th>
				<td>
					<input type="text" name="absenzdash_webuntis_code" id="absenzdash_webuntis_code"
						value="<?php echo esc_attr( $webuntis_code ); ?>" class="regular-text" />
				</td>
			</tr>
		</table>
		<?php
	}

	public function speichere_felder( int $user_id ): void {
		if ( ! current_user_can( 'edit_user', $user_id ) ) {
			return;
		}
		$rolle = isset( $_POST['absenzdash_role'] ) ? sanitize_text_field( wp_unslash( $_POST['absenzdash_role'] ) ) : '';
		if ( in_array( $rolle, self::ROLLEN, true ) ) {
			update_user_meta( $user_id, 'absenzdash_role', $rolle );
		} else {
			delete_user_meta( $user_id, 'absenzdash_role' );
		}

		$webuntis_code = isset( $_POST['absenzdash_webuntis_code'] ) ? sanitize_text_field( wp_unslash( $_POST['absenzdash_webuntis_code'] ) ) : '';
		if ( '' !== $webuntis_code ) {
			update_user_meta( $user_id, 'absenzdash_webuntis_code', $webuntis_code );
		} else {
			delete_user_meta( $user_id, 'absenzdash_webuntis_code' );
		}
	}
}
```

- [ ] **Step 2: Manuell verifizieren**

Als eingeloggter Admin zu **Benutzer → Profil** navigieren. Im neuen Abschnitt "AbsenzDash" die Rolle auf `schulleitung` setzen, WebUntis-Code leer lassen, speichern.
Erwartet: nach Reload zeigt das Dropdown weiterhin `schulleitung` (aus `absenzdash_role`-Meta gelesen).

- [ ] **Step 3: Commit**

```bash
git add wordpress-plugin/absenzdash/includes/class-benutzerprofil.php
git commit -m "feat: add minimal role/webuntis-code profile fields"
```

## Task 4: Proxy-REST-Route (Reverse-Proxy)

**Files:**
- Modify: `wordpress-plugin/absenzdash/includes/class-proxy.php`

**Interfaces:**
- Consumes: `Absenzdash_Optionen::get_backend_url()`, `Absenzdash_Optionen::get_shared_secret()` (Task 2); User-Meta `absenzdash_role`/`absenzdash_webuntis_code` (Task 3)
- Produces: REST-Route `GET/POST/PUT/DELETE /wp-json/absenzdash/v1/api/{pfad}`, konsumiert vom Smoke-Test-JS in Task 5 und später von der SPA.

- [ ] **Step 1: Proxy-Klasse implementieren**

`wordpress-plugin/absenzdash/includes/class-proxy.php` komplett ersetzen:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Proxy {

	const NAMESPACE_ = 'absenzdash/v1';

	private ?string $roh_body        = null;
	private ?string $roh_content_typ = null;

	public function __construct() {
		add_action( 'rest_api_init', array( $this, 'registriere_route' ) );
		add_filter( 'rest_pre_serve_request', array( $this, 'serviere_rohantwort' ), 10, 4 );
	}

	public function registriere_route(): void {
		register_rest_route(
			self::NAMESPACE_,
			'/api/(?P<pfad>.+)',
			array(
				'methods'             => WP_REST_Server::ALLMETHODS,
				'callback'            => array( $this, 'weiterleiten' ),
				'permission_callback' => 'is_user_logged_in',
			)
		);
	}

	public function weiterleiten( WP_REST_Request $request ) {
		$backend_url = Absenzdash_Optionen::get_backend_url();
		if ( empty( $backend_url ) ) {
			return new WP_Error( 'absenzdash_keine_backend_url', 'Backend-URL ist nicht konfiguriert.', array( 'status' => 500 ) );
		}

		$user  = wp_get_current_user();
		$rolle = get_user_meta( $user->ID, 'absenzdash_role', true );
		if ( empty( $rolle ) ) {
			return new WP_Error( 'absenzdash_keine_rolle', 'Keine Rolle zugewiesen.', array( 'status' => 400 ) );
		}

		$pfad  = '/' . ltrim( $request->get_param( 'pfad' ), '/' );
		$query = $request->get_query_params();
		unset( $query['pfad'], $query['rest_route'] );
		$ziel_url = $backend_url . $pfad;
		if ( ! empty( $query ) ) {
			$ziel_url .= '?' . http_build_query( $query );
		}

		$webuntis_code = get_user_meta( $user->ID, 'absenzdash_webuntis_code', true );

		$header = array(
			'X-WordPress-Secret' => Absenzdash_Optionen::get_shared_secret(),
			'X-WordPress-User'   => (string) $user->ID,
			'X-WordPress-Email'  => $user->user_email,
			'X-WordPress-Name'   => $user->display_name,
			'X-WordPress-Role'   => $rolle,
		);
		if ( ! empty( $webuntis_code ) ) {
			$header['X-WordPress-WebUntis-Code'] = $webuntis_code;
		}

		$argumente = array(
			'method'  => $request->get_method(),
			'headers' => $header,
			'timeout' => 15,
		);
		$body = $request->get_body();
		if ( ! empty( $body ) ) {
			$argumente['body'] = $body;
			$content_type = $request->get_header( 'content_type' );
			if ( ! empty( $content_type ) ) {
				$argumente['headers']['Content-Type'] = $content_type;
			}
		}

		$antwort = wp_remote_request( $ziel_url, $argumente );

		if ( is_wp_error( $antwort ) ) {
			return new WP_Error( 'absenzdash_backend_nicht_erreichbar', $antwort->get_error_message(), array( 'status' => 502 ) );
		}

		$status          = wp_remote_retrieve_response_code( $antwort );
		$antwort_body    = wp_remote_retrieve_body( $antwort );
		$antwort_content = wp_remote_retrieve_header( $antwort, 'content-type' );

		if ( ! empty( $antwort_content ) && false === strpos( $antwort_content, 'application/json' ) ) {
			$this->roh_body        = $antwort_body;
			$this->roh_content_typ = $antwort_content;
			$response = new WP_REST_Response( null, $status );
			$response->header( 'Content-Type', $antwort_content );
			return $response;
		}

		return new WP_REST_Response( json_decode( $antwort_body, true ), $status );
	}

	public function serviere_rohantwort( bool $serviert, $result, WP_REST_Request $request, WP_REST_Server $server ): bool {
		if ( null === $this->roh_body ) {
			return $serviert;
		}
		header( 'Content-Type: ' . $this->roh_content_typ );
		echo $this->roh_body;
		return true;
	}
}
```

- [ ] **Step 2: Manuell verifizieren — Erfolgsfall**

Voraussetzung: Backend läuft (`docker compose up` im `backend`-Verzeichnis), Options-Seite (Task 2) korrekt befüllt, eingeloggter Nutzer hat `absenzdash_role = schulleitung` (Task 3).

Im Browser (eingeloggt) navigieren zu `http://localhost:8080/wp-json/absenzdash/v1/api/students`.
Erwartet: HTTP 200, JSON-Array (ggf. leer, falls noch keine Schüler-Stammdaten importiert wurden) — kein PHP-Fehler.

- [ ] **Step 3: Manuell verifizieren — Fehlerfälle**

Nacheinander durchspielen und jeweils danach zurücksetzen:

1. Unter **Benutzer → Profil** die Rolle auf "(keine)" setzen, speichern, dieselbe URL erneut aufrufen. Erwartet: HTTP 400 mit `"Keine Rolle zugewiesen."`. Danach Rolle wieder auf `schulleitung` zurücksetzen.
2. Unter **Einstellungen → AbsenzDash** das Shared Secret kurzzeitig auf einen falschen Wert ändern, URL erneut aufrufen. Erwartet: HTTP 401 (vom Backend durchgereicht, siehe `deps.py:47-48`). Danach Secret zurücksetzen.
3. Backend-Container stoppen (`docker compose stop backend` im `backend`-Verzeichnis), URL erneut aufrufen. Erwartet: HTTP 502 mit einer Fehlermeldung. Danach Backend wieder starten (`docker compose start backend`).

- [ ] **Step 4: Commit**

```bash
git add wordpress-plugin/absenzdash/includes/class-proxy.php
git commit -m "feat: add generic reverse-proxy REST route to backend"
```

## Task 5: Shortcode & Smoke-Test-Debug-Ansicht

**Files:**
- Modify: `wordpress-plugin/absenzdash/includes/class-shortcode.php`
- Create: `wordpress-plugin/absenzdash/assets/smoke-test.js`

**Interfaces:**
- Consumes: REST-Route aus Task 4 (`/wp-json/absenzdash/v1/api/students`), User-Meta `absenzdash_role` aus Task 3
- Produces: Shortcode `[absenzdash]`, der im nächsten Plan (SPA) gegen den echten SPA-Mount-Point ausgetauscht wird

- [ ] **Step 1: Smoke-Test-JS erstellen**

`wordpress-plugin/absenzdash/assets/smoke-test.js`:

```javascript
document.addEventListener( 'DOMContentLoaded', function () {
	var button = document.getElementById( 'absenzdash-smoke-test-button' );
	var output = document.getElementById( 'absenzdash-smoke-test-output' );
	if ( ! button || ! output || typeof absenzdashConfig === 'undefined' ) {
		return;
	}
	button.addEventListener( 'click', function () {
		output.textContent = 'Lade...';
		fetch( absenzdashConfig.restUrl, {
			headers: { 'X-WP-Nonce': absenzdashConfig.nonce }
		} )
			.then( function ( response ) {
				return response.text().then( function ( text ) {
					return { status: response.status, text: text };
				} );
			} )
			.then( function ( ergebnis ) {
				output.textContent = 'Status ' + ergebnis.status + '\n' + ergebnis.text;
			} )
			.catch( function ( fehler ) {
				output.textContent = 'Fehler: ' + fehler.message;
			} );
	} );
} );
```

- [ ] **Step 2: Shortcode-Klasse implementieren**

`wordpress-plugin/absenzdash/includes/class-shortcode.php` komplett ersetzen:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Shortcode {

	public function __construct() {
		add_shortcode( 'absenzdash', array( $this, 'render' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'enqueue_assets' ) );
	}

	public function enqueue_assets(): void {
		wp_enqueue_script(
			'absenzdash-smoke-test',
			ABSENZDASH_PLUGIN_URL . 'assets/smoke-test.js',
			array(),
			ABSENZDASH_VERSION,
			true
		);
		wp_localize_script(
			'absenzdash-smoke-test',
			'absenzdashConfig',
			array(
				'restUrl' => esc_url_raw( rest_url( 'absenzdash/v1/api/students' ) ),
				'nonce'   => wp_create_nonce( 'wp_rest' ),
			)
		);
	}

	public function render(): string {
		if ( ! is_user_logged_in() ) {
			return '<p>AbsenzDash: Bitte einloggen.</p>';
		}
		$user  = wp_get_current_user();
		$rolle = get_user_meta( $user->ID, 'absenzdash_role', true );
		ob_start();
		?>
		<div id="absenzdash-smoke-test">
			<p>Eingeloggt als <strong><?php echo esc_html( $user->display_name ); ?></strong>,
				Rolle: <strong><?php echo esc_html( $rolle ?: '(keine)' ); ?></strong></p>
			<button type="button" id="absenzdash-smoke-test-button">GET /students laden</button>
			<pre id="absenzdash-smoke-test-output"></pre>
		</div>
		<?php
		return ob_get_clean();
	}
}
```

- [ ] **Step 3: Testseite mit Shortcode anlegen**

In WP-Admin eine neue Seite anlegen (z.B. "AbsenzDash-Test"), Inhalt: `[absenzdash]`, veröffentlichen.

- [ ] **Step 4: Manuell verifizieren**

Die veröffentlichte Seite im Browser (eingeloggt, Rolle `schulleitung` gesetzt) öffnen.
Erwartet: Text "Eingeloggt als ... Rolle: schulleitung" sichtbar. Auf "GET /students laden" klicken.
Erwartet: `<pre>`-Block zeigt "Status 200" gefolgt vom JSON-Array.

Rolle testweise wieder auf "(keine)" setzen (Benutzer → Profil), Seite neu laden, erneut klicken.
Erwartet: `<pre>`-Block zeigt "Status 400" mit der Fehlermeldung. Rolle danach zurücksetzen.

- [ ] **Step 5: Commit**

```bash
git add wordpress-plugin/absenzdash/includes/class-shortcode.php wordpress-plugin/absenzdash/assets/smoke-test.js
git commit -m "feat: add [absenzdash] shortcode with smoke-test debug view"
```

## Task 6: Backend-Netzwerk-Ergänzung

**Files:**
- Modify: `backend/docker-compose.yml`

**Interfaces:**
- Consumes: externes Docker-Netzwerk `absenzflow-shared` (bereits von der WP-Staging-`docker-compose.yml` erstellt/genutzt, siehe Voraussetzungen)
- Produces: `backend`-Service im Netzwerk `absenzflow-shared` erreichbar unter dem Service-Namen `absenzdash-backend` (Container-Name, siehe bestehende Zeile 21) — von der Options-Seite (Task 2) als Backend-URL genutzt

- [ ] **Step 1: Netzwerk-Konfiguration ergänzen**

`backend/docker-compose.yml` — den `backend`-Service um ein `networks`-Feld ergänzen und das externe Netzwerk am Dateiende deklarieren:

```yaml
services:
  postgres:
    image: postgres:15-alpine
    container_name: absenzdash-db
    environment:
      POSTGRES_USER: absenzdash
      POSTGRES_PASSWORD: absenzdash
      POSTGRES_DB: absenzdash
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U absenzdash"]
      interval: 5s
      timeout: 5s
      retries: 5
    volumes:
      - absenzdash-db-data:/var/lib/postgresql/data

  backend:
    build: .
    container_name: absenzdash-backend
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - .:/app
    networks:
      - default
      - absenzflow-shared

volumes:
  absenzdash-db-data:

networks:
  default:
  absenzflow-shared:
    external: true
```

- [ ] **Step 2: Manuell verifizieren**

Voraussetzung: das externe Netzwerk existiert bereits (wird von der WP-Staging-`docker-compose.yml` erzeugt, siehe deren `networks.absenzflow-shared`-Deklaration). Falls das Backend vor der WP-Instanz gestartet wird, vorher einmalig `docker network create absenzflow-shared` ausführen (idempotent, kein Fehler falls es schon existiert).

```bash
cd backend && docker compose up -d
docker network inspect absenzflow-shared --format '{{range .Containers}}{{.Name}} {{end}}'
```

Erwartet: `absenzdash-backend` erscheint in der Ausgabe (neben ggf. dem WordPress-Container, falls dieser bereits läuft).

Danach von innerhalb des WordPress-Containers die Erreichbarkeit prüfen (WP-Compose-Verzeichnis, `wordpress`-Service):

```bash
docker compose exec wordpress curl -s -o /dev/null -w '%{http_code}\n' http://absenzdash-backend:8000/docs
```

Erwartet: `200`.

- [ ] **Step 3: Commit**

```bash
git add backend/docker-compose.yml
git commit -m "feat: join backend service to shared WordPress docker network"
```

## Task 7: Dokumentation & Roadmap-Update

**Files:**
- Create: `docs/deployment.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: nichts (reine Dokumentation)
- Produces: nichts (Endpunkt der Kette)

- [ ] **Step 1: Deployment-Doku schreiben**

`docs/deployment.md`:

```markdown
# AbsenzDash — Deployment & lokale Entwicklung

## Backend

Siehe [backend-setup.md](backend-setup.md).

## WordPress-Plugin (Mini-Proxy & Shortcode)

Voraussetzung: eine laufende WordPress-Instanz mit einer `docker-compose.yml`, die Plugin-Verzeichnisse
per Volume nach `wp-content/plugins/` mountet (Beispiel, analog zu den Schwesterprojekten
AbsenzFlow/Ondisos):

\`\`\`yaml
services:
  wordpress:
    volumes:
      - ../AbsenzDash/wordpress-plugin/absenzdash:/var/www/html/wp-content/plugins/absenzdash
\`\`\`

Danach in WP-Admin:

1. Plugin "AbsenzDash" unter **Plugins** aktivieren.
2. Unter **Einstellungen → Permalinks** eine nicht-"Einfach"-Struktur wählen (z.B. "Beitragsname"),
   sonst funktionieren `/wp-json/...`-URLs nicht.
3. Unter **Einstellungen → AbsenzDash** die Backend-URL (z.B. `http://absenzdash-backend:8000`,
   erreichbar über das gemeinsame `absenzflow-shared`-Docker-Netzwerk) und das Shared Secret
   eintragen — das Secret muss exakt `WORDPRESS_PROXY_SECRET` aus `backend/.env` entsprechen.
4. Für jeden Testnutzer unter **Benutzer → Profil** die Rolle (`klassenlehrkraft` /
   `bereichsleiter` / `schulleitung`) und optional den WebUntis-Code setzen. Das ist ein
   Übergangsmechanismus für Tests — die richtige Rollen-/Bereichs-Admin-Oberfläche folgt in einem
   späteren Plan.
5. Eine Seite mit dem Shortcode `[absenzdash]` anlegen, um die Proxy-Kette per Smoke-Test-Ansicht
   zu prüfen (Button "GET /students laden").

## Netzwerk

Das Backend tritt dem externen Docker-Netzwerk `absenzflow-shared` bei (siehe
`backend/docker-compose.yml`), damit der WordPress-Container es unter dem Service-/Containernamen
`absenzdash-backend` erreicht. Das Netzwerk wird von der WordPress-Staging-`docker-compose.yml`
erzeugt; falls das Backend zuerst gestartet wird, einmalig `docker network create
absenzflow-shared` ausführen.
```

- [ ] **Step 2: ROADMAP.md aktualisieren**

In `ROADMAP.md` in der Tabelle unter "Abgeschlossen" eine neue Zeile für Plan 8 ergänzen (nach der Plan-7-Zeile) und den entsprechenden Punkt aus "Geplant" entfernen/anpassen. Neue Tabellenzeile:

```markdown
| **Plan 8** — [WordPress-Plugin — Mini-Proxy & Shortcode](docs/superpowers/plans/2026-07-27-wordpress-plugin-proxy.md) | Reverse-Proxy-REST-Route (generischer Passthrough mit Trusted-Headern), Backend-URL/Secret-Konfiguration, minimale Rollen-Profilfelder (Test-Übergangslösung), `[absenzdash]`-Shortcode mit sichtbarer Smoke-Test-Debug-Ansicht, Backend-Beitritt zum `absenzflow-shared`-Docker-Netzwerk (TECH-SPEC.md §3/§6). Bewusste Reihenfolge-Umkehr gegenüber der ursprünglichen Roadmap-Planung: Plugin-Proxy vor SPA, um Dev-Auth-Blindleistung zu vermeiden, siehe [Design-Dok](docs/superpowers/specs/2026-07-27-wordpress-plugin-proxy-design.md) | Bereichsdefinition-Admin-Seite, vollwertige Rollen-Zuweisungs-Oberfläche, die eigentliche React-SPA (folgt als nächster Plan) |
```

Den Abschnitt "Geplant (noch nicht als Plan ausgearbeitet)" entsprechend anpassen: Punkt 1 ("Frontend: React/TS-SPA") bleibt offen, aber mit Hinweis, dass er jetzt gegen das fertige Plugin aus Plan 8 entwickelt wird statt gegen einen Dev-Stub; Punkt 2 ("WordPress-Plugin") wird präzisiert auf die verbleibenden Teile (Bereichsdefinition-Admin-Seite, vollwertige Rollen-Zuweisung), da der Proxy/Shortcode-Grundstock jetzt in Plan 8 abgedeckt ist.

- [ ] **Step 3: Commit**

```bash
git add docs/deployment.md ROADMAP.md
git commit -m "docs: document WP plugin deployment and update roadmap for Plan 8"
```
