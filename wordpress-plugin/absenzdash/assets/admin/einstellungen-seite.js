(function () {
	function ergebnisAnzeigen(text, istFehler) {
		var element = document.getElementById('absenzdash-test-email-ergebnis');
		element.textContent = ' ' + text;
		element.style.color = istFehler ? '#b32d2e' : '#2a7a2a';
	}

	function testEmailSenden() {
		var button = document.getElementById('absenzdash-test-email-senden');
		button.disabled = true;
		ergebnisAnzeigen('Wird gesendet …', false);

		fetch(absenzdashEinstellungenConfig.restUrl + '/admin/test-email', {
			method: 'POST',
			headers: { 'X-WP-Nonce': absenzdashEinstellungenConfig.nonce }
		})
			.then(function (r) {
				return r.json().then(function (body) { return { ok: r.ok, body: body }; });
			})
			.then(function (ergebnis) {
				if (!ergebnis.ok) {
					throw new Error(ergebnis.body.detail || 'Versand fehlgeschlagen');
				}
				ergebnisAnzeigen('Gesendet an ' + ergebnis.body.empfaenger, false);
			})
			.catch(function (fehler) {
				ergebnisAnzeigen(fehler.message, true);
			})
			.finally(function () {
				button.disabled = false;
			});
	}

	document.addEventListener('DOMContentLoaded', function () {
		var button = document.getElementById('absenzdash-test-email-senden');
		if (button) {
			button.addEventListener('click', testEmailSenden);
		}
	});
})();
