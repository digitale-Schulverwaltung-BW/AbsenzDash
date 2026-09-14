<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Optionen {

	const OPTION_KEY = 'absenzdash_optionen';

	private ?string $hook_suffix = null;

	public function __construct() {
		add_action( 'admin_menu', array( $this, 'registriere_menu' ) );
		add_action( 'admin_init', array( $this, 'registriere_einstellungen' ) );
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_assets' ) );
	}

	public static function get_backend_url(): string {
		if ( defined( 'ABSENZDASH_BACKEND_URL' ) && ABSENZDASH_BACKEND_URL ) {
			return rtrim( ABSENZDASH_BACKEND_URL, '/' );
		}
		$optionen = get_option( self::OPTION_KEY, array() );
		return isset( $optionen['backend_url'] ) ? rtrim( $optionen['backend_url'], '/' ) : '';
	}

	public static function get_shared_secret(): string {
		if ( defined( 'ABSENZDASH_SHARED_SECRET' ) && ABSENZDASH_SHARED_SECRET ) {
			return ABSENZDASH_SHARED_SECRET;
		}
		$optionen = get_option( self::OPTION_KEY, array() );
		return isset( $optionen['shared_secret'] ) ? $optionen['shared_secret'] : '';
	}

	public function registriere_menu(): void {
		add_menu_page(
			'AbsenzDash',
			'AbsenzDash',
			'manage_options',
			'absenzdash',
			array( $this, 'render_seite' ),
			'dashicons-groups',
			80
		);
		$this->hook_suffix = add_submenu_page(
			'absenzdash',
			'AbsenzDash-Einstellungen',
			'Einstellungen',
			'manage_options',
			'absenzdash',
			array( $this, 'render_seite' )
		);
	}

	public function enqueue_assets( string $hook_suffix ): void {
		if ( $hook_suffix !== $this->hook_suffix ) {
			return;
		}
		wp_enqueue_script(
			'absenzdash-einstellungen-seite',
			ABSENZDASH_PLUGIN_URL . 'assets/admin/einstellungen-seite.js',
			array(),
			filemtime( ABSENZDASH_PLUGIN_DIR . 'assets/admin/einstellungen-seite.js' ),
			true
		);
		wp_localize_script(
			'absenzdash-einstellungen-seite',
			'absenzdashEinstellungenConfig',
			array(
				'restUrl' => esc_url_raw( rest_url( 'absenzdash/v1/api' ) ),
				'nonce'   => wp_create_nonce( 'wp_rest' ),
			)
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
							<?php if ( defined( 'ABSENZDASH_BACKEND_URL' ) && ABSENZDASH_BACKEND_URL ) : ?>
								<p class="description">Wird aktuell durch die wp-config.php-Konstante <code>ABSENZDASH_BACKEND_URL</code> überschrieben.</p>
							<?php endif; ?>
						</td>
					</tr>
					<tr>
						<th scope="row"><label for="absenzdash_shared_secret">Shared Secret</label></th>
						<td>
							<input type="password" id="absenzdash_shared_secret" name="<?php echo esc_attr( self::OPTION_KEY ); ?>[shared_secret]"
								value="<?php echo esc_attr( $optionen['shared_secret'] ?? '' ); ?>" class="regular-text" />
							<?php if ( defined( 'ABSENZDASH_SHARED_SECRET' ) && ABSENZDASH_SHARED_SECRET ) : ?>
								<p class="description">Wird aktuell durch die wp-config.php-Konstante <code>ABSENZDASH_SHARED_SECRET</code> überschrieben.</p>
							<?php endif; ?>
						</td>
					</tr>
				</table>
				<?php submit_button(); ?>
			</form>
			<h2>Verbindungstest</h2>
			<p>
				<button type="button" id="absenzdash-test-email-senden" class="button">Test-E-Mail senden</button>
				<span id="absenzdash-test-email-ergebnis"></span>
			</p>
		</div>
		<?php
	}
}
