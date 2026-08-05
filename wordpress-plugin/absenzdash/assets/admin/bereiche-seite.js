(function () {
	var zustand = { bereiche: [] };

	function element(tag, attrs, kinder) {
		var el = document.createElement(tag);
		Object.keys(attrs || {}).forEach(function (key) {
			if (key === 'text') {
				el.textContent = attrs[key];
			} else {
				el.setAttribute(key, attrs[key]);
			}
		});
		(kinder || []).forEach(function (kind) { el.appendChild(kind); });
		return el;
	}

	function mehrfachauswahl(eintraege, wertFeld, labelFn, ausgewaehlteWerte, cssKlasse) {
		var select = element('select', { multiple: 'multiple', class: cssKlasse, size: '6' });
		eintraege.forEach(function (eintrag) {
			var wert = String(eintrag[wertFeld]);
			var option = element('option', { value: wert, text: labelFn(eintrag) });
			if (ausgewaehlteWerte.indexOf(wert) !== -1) {
				option.selected = true;
			}
			select.appendChild(option);
		});
		return select;
	}

	function ausgewaehlteWerte(select) {
		return Array.prototype.slice.call(select.selectedOptions).map(function (option) { return option.value; });
	}

	function bereichZeileRendern(bereich) {
		var leiterAuswahl = mehrfachauswahl(
			absenzdashBereicheConfig.wpNutzer, 'wp_user_id',
			function (n) { return n.name + ' (' + (n.rolle || 'keine Rolle') + ')'; },
			(bereich.leiter || []).map(function (l) { return l.wp_user_id; }),
			'absenzdash-bereich-leiter'
		);
		var ausblendenCheckbox = element('input', { type: 'checkbox', class: 'absenzdash-bereich-ausblenden' });
		ausblendenCheckbox.checked = !!bereich.ausgeblendet;

		var zeile = element('div', { class: 'absenzdash-bereich-zeile', style: 'border:1px solid #ccd0d4; padding:10px; margin-bottom:10px;' }, [
			element('strong', { text: bereich.name || '' }),
			element('br', {}),
			element('span', { text: 'Klassen: ' + ((bereich.klasse_namen || []).join(', ') || '(keine)') }),
			element('br', {}),
			element('label', { text: 'Bereichsleiter: ' }), leiterAuswahl,
			element('br', {}),
			element('label', {}, [ausblendenCheckbox, document.createTextNode(' Ausblenden (aus Dashboard/Diagrammen)')])
		]);
		zeile.dataset.bereichId = String(bereich.id);

		return zeile;
	}

	function bereicheNeuRendern() {
		var liste = document.getElementById('absenzdash-bereiche-liste');
		liste.innerHTML = '';
		zustand.bereiche.forEach(function (bereich) {
			liste.appendChild(bereichZeileRendern(bereich));
		});
	}

	function fehlerAnzeigen(nachricht) {
		var element = document.getElementById('absenzdash-bereiche-fehler');
		element.textContent = nachricht;
		if (nachricht) {
			element.style.background = '#fbeaea';
			element.style.border = '1px solid #b32d2e';
			element.style.padding = '8px 12px';
			element.scrollIntoView({ behavior: 'smooth', block: 'start' });
		} else {
			element.style.background = '';
			element.style.border = '';
			element.style.padding = '';
		}
	}

	function laden() {
		fetch(absenzdashBereicheConfig.restUrl + '/admin/bereiche', {
			headers: { 'X-WP-Nonce': absenzdashBereicheConfig.nonce }
		}).then(function (r) {
			if (!r.ok) { throw new Error('Bereiche laden fehlgeschlagen (HTTP ' + r.status + ')'); }
			return r.json();
		}).then(function (bereiche) {
			zustand.bereiche = bereiche;
			bereicheNeuRendern();
		}).catch(function (fehler) {
			fehlerAnzeigen(fehler.message);
		});
	}

	function ausZeilenLesen() {
		var zeilen = document.querySelectorAll('.absenzdash-bereich-zeile');
		return Array.prototype.map.call(zeilen, function (zeile) {
			var leiterIds = ausgewaehlteWerte(zeile.querySelector('.absenzdash-bereich-leiter'));
			var leiter = leiterIds.map(function (wpUserId) {
				var nutzer = absenzdashBereicheConfig.wpNutzer.filter(function (n) { return n.wp_user_id === wpUserId; })[0];
				return {
					wp_user_id: nutzer.wp_user_id,
					email: nutzer.email,
					name: nutzer.name,
					rolle: nutzer.rolle || 'bereichsleiter'
				};
			});
			return {
				id: Number(zeile.dataset.bereichId),
				ausgeblendet: zeile.querySelector('.absenzdash-bereich-ausblenden').checked,
				leiter: leiter
			};
		});
	}

	function speichern() {
		fetch(absenzdashBereicheConfig.restUrl + '/admin/bereiche', {
			method: 'PUT',
			headers: { 'X-WP-Nonce': absenzdashBereicheConfig.nonce, 'Content-Type': 'application/json' },
			body: JSON.stringify(ausZeilenLesen())
		})
			.then(function (r) {
				return r.json().then(function (body) { return { ok: r.ok, body: body }; });
			})
			.then(function (ergebnis) {
				if (!ergebnis.ok) {
					throw new Error(ergebnis.body.detail || 'Speichern fehlgeschlagen');
				}
				zustand.bereiche = ergebnis.body;
				bereicheNeuRendern();
				fehlerAnzeigen('');
			})
			.catch(function (fehler) {
				fehlerAnzeigen(fehler.message);
			});
	}

	document.addEventListener('DOMContentLoaded', function () {
		laden();
		document.getElementById('absenzdash-bereiche-speichern').addEventListener('click', speichern);
	});
})();
