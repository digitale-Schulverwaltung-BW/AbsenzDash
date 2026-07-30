<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Bereiche_Seite {

	private ?string $hook_suffix = null;

	public function __construct() {
		add_action( 'admin_menu', array( $this, 'registriere_seite' ) );
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_assets' ) );
	}

	public function registriere_seite(): void {
		$this->hook_suffix = add_submenu_page(
			'absenzdash',
			'AbsenzDash-Bereiche',
			'Bereiche',
			'manage_options',
			'absenzdash-bereiche',
			array( $this, 'render_seite' )
		);
	}

	private function get_wp_nutzer_liste(): array {
		$liste = array();
		foreach ( get_users() as $user ) {
			$liste[] = array(
				'wp_user_id' => (string) $user->ID,
				'email'      => $user->user_email,
				'name'       => $user->display_name,
				'rolle'      => get_user_meta( $user->ID, 'absenzdash_role', true ),
			);
		}
		return $liste;
	}

	public function enqueue_assets( string $hook_suffix ): void {
		if ( $hook_suffix !== $this->hook_suffix ) {
			return;
		}
		wp_enqueue_script(
			'absenzdash-bereiche-seite',
			ABSENZDASH_PLUGIN_URL . 'assets/admin/bereiche-seite.js',
			array(),
			filemtime( ABSENZDASH_PLUGIN_DIR . 'assets/admin/bereiche-seite.js' ),
			true
		);
		wp_localize_script(
			'absenzdash-bereiche-seite',
			'absenzdashBereicheConfig',
			array(
				'restUrl'  => esc_url_raw( rest_url( 'absenzdash/v1/api' ) ),
				'nonce'    => wp_create_nonce( 'wp_rest' ),
				'wpNutzer' => $this->get_wp_nutzer_liste(),
			)
		);
	}

	public function render_seite(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		?>
		<div class="wrap">
			<h1>AbsenzDash — Bereichsdefinition</h1>
			<div id="absenzdash-bereiche-fehler" style="color:#b32d2e;"></div>
			<p>
				<button type="button" id="absenzdash-vorbefuellen" class="button">Aus WebUntis-Abteilungen vorbefüllen</button>
				<button type="button" id="absenzdash-bereich-hinzufuegen" class="button">Bereich hinzufügen</button>
			</p>
			<div id="absenzdash-bereiche-liste"></div>
			<p><button type="button" id="absenzdash-bereiche-speichern" class="button button-primary">Speichern</button></p>
		</div>
		<?php
	}
}
