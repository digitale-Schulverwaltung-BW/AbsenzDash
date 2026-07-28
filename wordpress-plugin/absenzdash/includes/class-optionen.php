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
