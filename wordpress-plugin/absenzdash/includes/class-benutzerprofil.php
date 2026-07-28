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
		if ( ! current_user_can( 'edit_users' ) ) {
			return;
		}
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
					<input type="number" name="absenzdash_webuntis_code" id="absenzdash_webuntis_code"
						value="<?php echo esc_attr( $webuntis_code ); ?>" class="regular-text" />
				</td>
			</tr>
		</table>
		<?php
	}

	public function speichere_felder( int $user_id ): void {
		if ( ! current_user_can( 'edit_users' ) ) {
			return;
		}
		$rolle = isset( $_POST['absenzdash_role'] ) ? sanitize_text_field( wp_unslash( $_POST['absenzdash_role'] ) ) : '';
		if ( in_array( $rolle, self::ROLLEN, true ) ) {
			update_user_meta( $user_id, 'absenzdash_role', $rolle );
		} else {
			delete_user_meta( $user_id, 'absenzdash_role' );
		}

		$webuntis_code = isset( $_POST['absenzdash_webuntis_code'] ) ? sanitize_text_field( wp_unslash( $_POST['absenzdash_webuntis_code'] ) ) : '';
		if ( '' !== $webuntis_code && ctype_digit( $webuntis_code ) ) {
			update_user_meta( $user_id, 'absenzdash_webuntis_code', $webuntis_code );
		} else {
			delete_user_meta( $user_id, 'absenzdash_webuntis_code' );
		}
	}
}
