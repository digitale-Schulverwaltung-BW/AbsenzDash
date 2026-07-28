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
