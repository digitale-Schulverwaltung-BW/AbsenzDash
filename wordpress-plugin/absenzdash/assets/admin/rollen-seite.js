(function () {
	function ladeUndBefuelle() {
		var fehlerBox = document.getElementById('absenzdash-fehler');
		fetch(absenzdashRollenConfig.restUrl + '/admin/webuntis-teachers', {
			headers: { 'X-WP-Nonce': absenzdashRollenConfig.nonce }
		})
			.then(function (antwort) {
				if (!antwort.ok) {
					throw new Error('HTTP ' + antwort.status);
				}
				return antwort.json();
			})
			.then(function (lehrkraefte) {
				document.querySelectorAll('.absenzdash-kuerzel-auswahl').forEach(function (auswahl) {
					var aktuell = auswahl.dataset.aktuell || '';
					var vorschlagKuerzel = (auswahl.dataset.vorschlag || '').toUpperCase();
					var vorschlagId = '';

					lehrkraefte.forEach(function (lehrkraft) {
						var option = document.createElement('option');
						option.value = String(lehrkraft.id);
						option.textContent = lehrkraft.kuerzel;
						auswahl.appendChild(option);
						if (!vorschlagId && lehrkraft.kuerzel.toUpperCase() === vorschlagKuerzel) {
							vorschlagId = String(lehrkraft.id);
						}
					});

					if (aktuell) {
						auswahl.value = aktuell;
					} else if (vorschlagId) {
						auswahl.value = vorschlagId;
					}
				});
			})
			.catch(function (fehler) {
				fehlerBox.textContent = 'WebUntis-Kürzelliste konnte nicht geladen werden: ' + fehler.message;
			});
	}

	document.addEventListener('DOMContentLoaded', ladeUndBefuelle);
})();
