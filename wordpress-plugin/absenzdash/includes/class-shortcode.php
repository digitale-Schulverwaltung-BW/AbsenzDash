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
