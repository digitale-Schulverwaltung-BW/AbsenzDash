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

		$pfad = '/' . ltrim( $request->get_param( 'pfad' ), '/' );

		// Admins duerfen sich nie aus den eigenen Einstellungsseiten aussperren.
		if ( $user->has_cap( 'manage_options' ) && 0 === strpos( $pfad, '/admin/' ) ) {
			$rolle = 'schulleitung';
		}

		if ( empty( $rolle ) ) {
			return new WP_Error( 'absenzdash_keine_rolle', 'Keine Rolle zugewiesen.', array( 'status' => 400 ) );
		}

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
