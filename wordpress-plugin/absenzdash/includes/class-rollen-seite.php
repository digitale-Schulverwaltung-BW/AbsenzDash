<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Rollen_Seite {

	const ROLLEN = array( 'klassenlehrkraft', 'bereichsleiter', 'schulleitung' );

	public function __construct() {
		add_action( 'admin_menu', array( $this, 'registriere_seite' ) );
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_assets' ) );
		add_action( 'admin_post_absenzdash_rollen_speichern', array( $this, 'speichere_rollen' ) );
	}

	public function registriere_seite(): void {
		add_options_page(
			'AbsenzDash-Rollen',
			'AbsenzDash-Rollen',
			'manage_options',
			'absenzdash-rollen',
			array( $this, 'render_seite' )
		);
	}

	public function enqueue_assets( string $hook_suffix ): void {
		if ( 'settings_page_absenzdash-rollen' !== $hook_suffix ) {
			return;
		}
		wp_enqueue_script(
			'absenzdash-rollen-seite',
			ABSENZDASH_PLUGIN_URL . 'assets/admin/rollen-seite.js',
			array(),
			ABSENZDASH_VERSION,
			true
		);
		wp_localize_script(
			'absenzdash-rollen-seite',
			'absenzdashRollenConfig',
			array(
				'restUrl' => esc_url_raw( rest_url( 'absenzdash/v1/api' ) ),
				'nonce'   => wp_create_nonce( 'wp_rest' ),
			)
		);
	}

	private function get_nutzer_zeilen(): array {
		$zeilen = array();
		foreach ( get_users() as $user ) {
			$zeilen[] = array(
				'id'                   => $user->ID,
				'name'                 => $user->display_name,
				'email'                => $user->user_email,
				'rolle'                => get_user_meta( $user->ID, 'absenzdash_role', true ),
				'webuntis_code'        => get_user_meta( $user->ID, 'absenzdash_webuntis_code', true ),
				'absenzflow_vorschlag' => get_user_meta( $user->ID, 'absenzflow_webuntis_code', true ),
			);
		}
		return $zeilen;
	}

	public function render_seite(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		?>
		<div class="wrap">
			<h1>AbsenzDash — Rollen-Zuweisung</h1>
			<p>Rolle und WebUntis-Kürzel je Nutzer. Die Kürzel-Auswahl wird live aus WebUntis geladen; ein
				bereits bei VertretungsFlow hinterlegtes Kürzel wird als Vorschlag vorausgewählt, muss aber
				hier bestätigt werden.</p>
			<div id="absenzdash-fehler" style="color:#b32d2e;"></div>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
				<?php wp_nonce_field( 'absenzdash_rollen_speichern' ); ?>
				<input type="hidden" name="action" value="absenzdash_rollen_speichern" />
				<table class="widefat">
					<thead>
						<tr>
							<th>Nutzer</th>
							<th>E-Mail</th>
							<th>Rolle</th>
							<th>WebUntis-Kürzel</th>
						</tr>
					</thead>
					<tbody>
						<?php foreach ( $this->get_nutzer_zeilen() as $zeile ) : ?>
							<tr>
								<td><?php echo esc_html( $zeile['name'] ); ?></td>
								<td><?php echo esc_html( $zeile['email'] ); ?></td>
								<td>
									<select name="rolle[<?php echo esc_attr( $zeile['id'] ); ?>]">
										<option value="">(keine)</option>
										<?php foreach ( self::ROLLEN as $moegliche_rolle ) : ?>
											<option value="<?php echo esc_attr( $moegliche_rolle ); ?>" <?php selected( $zeile['rolle'], $moegliche_rolle ); ?>>
												<?php echo esc_html( $moegliche_rolle ); ?>
											</option>
										<?php endforeach; ?>
									</select>
								</td>
								<td>
									<select name="webuntis_code[<?php echo esc_attr( $zeile['id'] ); ?>]"
										class="absenzdash-kuerzel-auswahl"
										data-vorschlag="<?php echo esc_attr( $zeile['absenzflow_vorschlag'] ); ?>"
										data-aktuell="<?php echo esc_attr( $zeile['webuntis_code'] ); ?>">
										<option value="">(keins)</option>
									</select>
								</td>
							</tr>
						<?php endforeach; ?>
					</tbody>
				</table>
				<?php submit_button( 'Speichern' ); ?>
			</form>
		</div>
		<?php
	}

	public function speichere_rollen(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( 'Keine Berechtigung.' );
		}
		check_admin_referer( 'absenzdash_rollen_speichern' );

		$rollen  = isset( $_POST['rolle'] ) ? wp_unslash( $_POST['rolle'] ) : array();
		$kuerzel = isset( $_POST['webuntis_code'] ) ? wp_unslash( $_POST['webuntis_code'] ) : array();

		foreach ( get_users() as $user ) {
			$user_id = $user->ID;

			$rolle = isset( $rollen[ $user_id ] ) ? sanitize_text_field( $rollen[ $user_id ] ) : '';
			if ( in_array( $rolle, self::ROLLEN, true ) ) {
				update_user_meta( $user_id, 'absenzdash_role', $rolle );
			} else {
				delete_user_meta( $user_id, 'absenzdash_role' );
			}

			$code = isset( $kuerzel[ $user_id ] ) ? sanitize_text_field( $kuerzel[ $user_id ] ) : '';
			if ( '' !== $code && ctype_digit( $code ) ) {
				update_user_meta( $user_id, 'absenzdash_webuntis_code', $code );
			} else {
				delete_user_meta( $user_id, 'absenzdash_webuntis_code' );
			}
		}

		wp_safe_redirect( add_query_arg( 'absenzdash_gespeichert', '1', wp_get_referer() ) );
		exit;
	}
}
