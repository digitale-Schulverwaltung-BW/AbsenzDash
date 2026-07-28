<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Shortcode {

	public function __construct() {
		add_shortcode( 'absenzdash', array( $this, 'render' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'enqueue_assets' ) );
		add_filter( 'script_loader_tag', array( $this, 'add_module_type' ), 10, 3 );
	}

	private function get_manifest_entry(): ?array {
		$manifest_path = ABSENZDASH_PLUGIN_DIR . 'assets/spa/.vite/manifest.json';
		if ( ! file_exists( $manifest_path ) ) {
			return null;
		}
		$manifest = json_decode( file_get_contents( $manifest_path ), true );
		return $manifest['index.html'] ?? null;
	}

	public function enqueue_assets(): void {
		if ( ! is_singular() || ! has_shortcode( get_post()->post_content, 'absenzdash' ) ) {
			return;
		}

		if ( defined( 'ABSENZDASH_VITE_DEV_SERVER' ) && ABSENZDASH_VITE_DEV_SERVER ) {
			$dev_server = rtrim( ABSENZDASH_VITE_DEV_SERVER, '/' );
			wp_enqueue_script( 'absenzdash-vite-client', $dev_server . '/@vite/client', array(), null, true );
			wp_enqueue_script(
				'absenzdash-spa',
				$dev_server . '/src/main.tsx',
				array( 'absenzdash-vite-client' ),
				null,
				true
			);
		} else {
			$entry = $this->get_manifest_entry();
			if ( null === $entry ) {
				return;
			}
			foreach ( $entry['css'] ?? array() as $index => $css_file ) {
				wp_enqueue_style(
					'absenzdash-spa-' . $index,
					ABSENZDASH_PLUGIN_URL . 'assets/spa/' . $css_file,
					array(),
					ABSENZDASH_VERSION
				);
			}
			wp_enqueue_script(
				'absenzdash-spa',
				ABSENZDASH_PLUGIN_URL . 'assets/spa/' . $entry['file'],
				array(),
				ABSENZDASH_VERSION,
				true
			);
		}

		wp_localize_script(
			'absenzdash-spa',
			'absenzdashConfig',
			array(
				'restUrl'  => esc_url_raw( rest_url( 'absenzdash/v1/api' ) ),
				'nonce'    => wp_create_nonce( 'wp_rest' ),
				'basename' => wp_parse_url( get_permalink(), PHP_URL_PATH ),
			)
		);
	}

	public function add_module_type( string $tag, string $handle, string $src ): string {
		if ( in_array( $handle, array( 'absenzdash-vite-client', 'absenzdash-spa' ), true ) ) {
			return str_replace( ' src=', ' type="module" src=', $tag );
		}
		return $tag;
	}

	public function render(): string {
		if ( ! is_user_logged_in() ) {
			return '<p>AbsenzDash: Bitte einloggen.</p>';
		}
		return '<div id="absenzdash-root"></div>';
	}
}
