import datetime
from datetime import date

import pytest

from app.api.deps import resolve_bereich_scope, resolve_scope
from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schuljahr import Schuljahr
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.services import dashboard_query


@pytest.mark.asyncio
async def test_get_nav_options_for_schulleitung_returns_all_bereiche_and_klassen(db_session, schuljahr):
    bereich = Bereich(name="Ausbildung")
    klasse_a = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="BME12", schuljahr_id=schuljahr.id)
    db_session.add_all([bereich, klasse_a, klasse_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert {b.name for b in options.bereiche} == {"Ausbildung"}
    assert {k.name for k in options.klassen} == {"AME56", "BME12"}
    klasse_map = {k.id: k.bereich_id for k in options.klassen}
    assert klasse_map[klasse_a.id] == bereich.id
    assert klasse_map[klasse_b.id] is None


@pytest.mark.asyncio
async def test_get_nav_options_for_klassenlehrkraft_returns_only_own_klassen_and_no_bereiche(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="BME12", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert options.bereiche == []
    assert [k.id for k in options.klassen] == [klasse_a.id]


@pytest.mark.asyncio
async def test_get_nav_options_for_bereichsleiter_returns_own_bereiche_and_their_klassen(db_session, schuljahr):
    bereich = Bereich(name="Ausbildung")
    andere_bereich = Bereich(name="Berufsschule")
    klasse_a = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="BME12", schuljahr_id=schuljahr.id)
    db_session.add_all([bereich, andere_bereich, klasse_a, klasse_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=andere_bereich.id, klasse_id=klasse_b.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert [b.id for b in options.bereiche] == [bereich.id]
    assert [k.id for k in options.klassen] == [klasse_a.id]


@pytest.mark.asyncio
async def test_get_nav_options_includes_rolle(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert result.rolle == "schulleitung"


@pytest.mark.asyncio
async def test_get_nav_options_includes_schuljahre_newest_first(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([nutzer, schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id),
            SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_neu.id, klasse_id=klasse_neu.id),
        ]
    )
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert [s.id for s in result.schuljahre] == [28, 27]
    assert result.schuljahre[0].name == "2025/2026"


@pytest.mark.asyncio
async def test_get_nav_options_includes_aktuelles_schuljahr_id_when_set(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add_all(
        [
            nutzer,
            Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30)),
            Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29)),
        ]
    )
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=28))
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert result.aktuelles_schuljahr_id == 28


@pytest.mark.asyncio
async def test_get_nav_options_aktuelles_schuljahr_id_is_none_when_not_set(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert result.aktuelles_schuljahr_id is None


@pytest.mark.asyncio
async def test_get_nav_options_klassen_scoped_to_aktuelles_schuljahr_by_default(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add_all([schuljahr_alt, schuljahr_neu, nutzer])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert [k.id for k in result.klassen] == [klasse_neu.id]


@pytest.mark.asyncio
async def test_get_nav_options_klassen_scoped_to_requested_historical_schuljahr(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add_all([schuljahr_alt, schuljahr_neu, nutzer])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer, schuljahr_id=schuljahr_alt.id)

    assert [k.id for k in result.klassen] == [klasse_alt.id]


@pytest.mark.asyncio
async def test_get_nav_options_excludes_schuljahr_without_historie_rows(db_session):
    schuljahr_ohne_daten = Schuljahr(id=20, name="2017/2018", start_datum=date(2017, 9, 11), end_datum=date(2018, 7, 27))
    db_session.add(schuljahr_ohne_daten)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert schuljahr_ohne_daten.id not in {s.id for s in result.schuljahre}


@pytest.mark.asyncio
async def test_get_nav_options_includes_schuljahr_with_at_least_one_historie_row(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse.id)
    )
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert schuljahr_alt.id in {s.id for s in result.schuljahre}


@pytest.mark.asyncio
async def test_get_nav_options_always_includes_aktuelles_schuljahr_even_without_historie_rows(db_session):
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add(schuljahr_neu)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()
    # keine schueler_klasse_historie-Zeile fuer schuljahr_neu -- z.B. direkt nach einem Rollover.

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert schuljahr_neu.id in {s.id for s in result.schuljahre}


async def _seed_schueler_mit_fehlzeit(db_session, klasse, schuljahr_start):
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=schuljahr_start + datetime.timedelta(days=1),
            start_zeit=0,
            end_zeit=2359,
        )
    )
    await db_session.commit()
    return schueler


@pytest.mark.asyncio
async def test_get_dashboard_stats_historie_mode_uses_schueler_klasse_historie_not_live_klasse_id(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_live = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_alt, klasse_live])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    # Schueler ist heute (live) in klasse_live, war im betrachteten Schuljahr aber in klasse_alt.
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_live.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id)
    )
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359
        )
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(
        db_session, nutzer, None, klasse_alt.id, schuljahr_alt.id
    )
    assert stats.own.anzahl_schueler == 1
    assert stats.own.avg_fehltage == 1.0

    # klasse_live ist nur die LIVE-Klasse, nicht die historische fuer schuljahr_alt -> kein Treffer.
    stats_live_klasse = await dashboard_query.get_dashboard_stats(
        db_session, nutzer, None, klasse_live.id, schuljahr_alt.id
    )
    assert stats_live_klasse.own.anzahl_schueler == 0


@pytest.mark.asyncio
async def test_get_dashboard_stats_historie_mode_includes_inactive_students(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    db_session.add(klasse)
    await db_session.flush()
    # inzwischen abgemeldeter Schueler (aktiv=False) -- war im betrachteten Schuljahr eingeschrieben.
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=False)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse.id)
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id, schuljahr_alt.id)

    assert stats.own.anzahl_schueler == 1


@pytest.mark.asyncio
async def test_get_dashboard_stats_historie_mode_excludes_fehlzeiten_after_schuljahr_end(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse.id)
    )
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            # liegt NACH schuljahr_alt.end_datum (2025-07-30) -- gehoert zum Folgejahr, muss ausgeschlossen werden.
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 9, 20), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id, schuljahr_alt.id)

    assert stats.own.avg_fehltage == 1.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_current_schuljahr_still_has_no_upper_date_bound(db_session, schuljahr):
    # Regressionstest fuer die Design-Dok-Vorgabe "aktuelles Schuljahr weiterhin (schuljahr_start_cache,
    # None) -- keine Obergrenze noetig". Eine (theoretisch verfrueht importierte) Fehlzeit weit in der
    # Zukunft darf im Normalmodus nicht durch eine neu eingefuehrte Obergrenze verschwinden.
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2099, 1, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.own.avg_fehltage == 1.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_historie_mode_groups_by_abteilung_not_bereich_klasse(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    abteilung = Abteilung(webuntis_id=1, name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik", abteilung_id=abteilung.id)
    db_session.add(bereich)
    await db_session.flush()
    # historische Klasse ist NICHT in bereich_klasse eingetragen (die Tabelle spiegelt nur die
    # aktuelle Struktur) -- die Zuordnung muss ausschliesslich ueber abteilung_id funktionieren.
    klasse_historisch = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id, abteilung_id=abteilung.id)
    db_session.add(klasse_historisch)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_historisch.id)
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None, schuljahr_alt.id)

    vergleich_by_name = {v.name: v for v in stats.vergleich}
    assert vergleich_by_name["Mechatronik"].anzahl_schueler == 1
    assert vergleich_by_name["Mechatronik"].avg_fehltage == 1.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_historie_mode_bereich_without_abteilung_id_is_empty(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    bereich_ohne_abteilung = Bereich(name="Ohne Abteilung", abteilung_id=None)
    db_session.add(bereich_ohne_abteilung)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None, schuljahr_alt.id)

    vergleich_by_name = {v.name: v for v in stats.vergleich}
    assert vergleich_by_name["Ohne Abteilung"].anzahl_schueler == 0


@pytest.mark.asyncio
async def test_stats_for_bereich_historie_mode_uses_klasse_abteilung_id(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    abteilung = Abteilung(webuntis_id=1, name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik", abteilung_id=abteilung.id)
    db_session.add(bereich)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id, abteilung_id=abteilung.id)
    db_session.add(klasse)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, bereich.id, None, schuljahr_alt.id)

    assert stats.level == "bereich"
    assert [v.name for v in stats.vergleich] == ["10a"]


@pytest.mark.asyncio
async def test_get_dashboard_stats_for_single_klasse_averages_over_active_students_only(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    await _seed_schueler_mit_fehlzeit(db_session, klasse, schuljahr_start)
    inaktiver_schueler = Schueler(
        externe_id="ext-2", vorname="Erika", nachname="Beispiel", klasse_id=klasse.id, aktiv=False
    )
    db_session.add(inaktiver_schueler)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.level == "klasse"
    assert stats.context.klasse_id == klasse.id
    assert stats.context.klasse_name == "AME56"
    assert stats.own.anzahl_schueler == 1
    assert stats.own.avg_fehltage == 1.0
    assert stats.vergleich == []


@pytest.mark.asyncio
async def test_get_dashboard_stats_computes_avg_fehlstunden_from_minutes_not_row_count(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            # 07:30-08:15 (Stundengrenze!) = 45 Min., 09:00-09:20 = 20 Min. -> 65 Min. gesamt
            Fehlzeit(
                schueler_id=schueler.id, typ="stunde",
                datum=schuljahr_start + datetime.timedelta(days=1), start_zeit=730, end_zeit=815,
            ),
            Fehlzeit(
                schueler_id=schueler.id, typ="stunde",
                datum=schuljahr_start + datetime.timedelta(days=2), start_zeit=900, end_zeit=920,
            ),
        ]
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.own.avg_fehlstunden == 1.44  # 65 Min. / 45 = 1.4444... gerundet


@pytest.mark.asyncio
async def test_get_dashboard_stats_excludes_fehlzeiten_before_schuljahr_start(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=schuljahr_start - datetime.timedelta(days=1),
            start_zeit=0,
            end_zeit=2359,
        )
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.own.avg_fehltage == 0.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_counts_klassenbuch_and_massnahmen(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    kategorie = ClassregCategory(name="stören")
    massnahmen_typ = MassnahmenTyp(name="Gespräch")
    erfasser = Nutzer(wp_user_id="lehrer1", email="l@b.de", name="Lehrkraft", rolle="klassenlehrkraft")
    db_session.add_all([schueler, kategorie, massnahmen_typ, erfasser])
    await db_session.flush()
    db_session.add(
        KlassenbuchEintrag(
            webuntis_id=1,
            schueler_id=schueler.id,
            kategorie_id=kategorie.id,
            datum=schuljahr_start + datetime.timedelta(days=1),
        )
    )
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=massnahmen_typ.id,
            datum=schuljahr_start + datetime.timedelta(days=1),
            erfasst_von_nutzer_id=erfasser.id,
        )
    )
    await db_session.commit()
    schulleitung = Nutzer(wp_user_id="admin1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(schulleitung)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, schulleitung, None, klasse.id)

    assert stats.own.anzahl_klassenbuch == 1
    assert stats.own.avg_klassenbuch == 1.0
    assert stats.own.anzahl_massnahmen == 1


@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_compares_bereiche(db_session, schuljahr):
    bereich_a = Bereich(name="Ausbildung")
    bereich_b = Bereich(name="Berufsschule")
    klasse_a = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="BME12", schuljahr_id=schuljahr.id)
    db_session.add_all([bereich_a, bereich_b, klasse_a, klasse_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_a.id, klasse_id=klasse_a.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_b.id, klasse_id=klasse_b.id))
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    await _seed_schueler_mit_fehlzeit(db_session, klasse_a, schuljahr_start)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    assert stats.level == "schule"
    vergleich_by_name = {v.name: v for v in stats.vergleich}
    assert vergleich_by_name["Ausbildung"].avg_fehltage == 1.0
    assert vergleich_by_name["Berufsschule"].avg_fehltage == 0.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_defaults_bereichsleiter_with_single_bereich_to_that_bereich(db_session, schuljahr):
    bereich = Bereich(name="Ausbildung")
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add_all([bereich, klasse])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    assert stats.level == "bereich"
    assert stats.context.bereich_id == bereich.id


@pytest.mark.asyncio
async def test_get_dashboard_stats_klassenlehrkraft_with_multiple_klassen_compares_own_klassen(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="AME57", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add_all(
        [
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"),
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_b.id, quelle="webuntis_seed"),
        ]
    )
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    assert stats.level == "eigene_klassen"
    assert {v.name for v in stats.vergleich} == {"AME56", "AME57"}


@pytest.mark.asyncio
async def test_get_dashboard_stats_rejects_bereich_id_for_klassenlehrkraft(db_session):
    from fastapi import HTTPException

    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_query.get_dashboard_stats(db_session, nutzer, 1, None)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_dashboard_stats_404s_for_klasse_outside_scope(db_session, schuljahr):
    from fastapi import HTTPException

    klasse_a = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="AME57", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse_b.id)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_nav_options_excludes_ausgeblendete_bereiche(db_session):
    bereich_sichtbar = Bereich(name="Ausbildung")
    bereich_versteckt = Bereich(name="Historisch", ausgeblendet=True)
    db_session.add_all([bereich_sichtbar, bereich_versteckt])
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert {b.name for b in options.bereiche} == {"Ausbildung"}


@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_excludes_ausgeblendete_bereiche(db_session):
    bereich_sichtbar = Bereich(name="Ausbildung")
    bereich_versteckt = Bereich(name="Historisch", ausgeblendet=True)
    db_session.add_all([bereich_sichtbar, bereich_versteckt])
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    namen = {v.name for v in stats.vergleich}
    assert namen == {"Ausbildung"}


@pytest.mark.asyncio
async def test_get_dashboard_stats_eigene_bereiche_excludes_ausgeblendete_bereiche(db_session):
    bereich_sichtbar = Bereich(name="Ausbildung")
    bereich_versteckt = Bereich(name="Historisch", ausgeblendet=True)
    db_session.add_all([bereich_sichtbar, bereich_versteckt])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(
        nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich_sichtbar.id)
    )
    await db_session.execute(
        nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich_versteckt.id)
    )
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    assert stats.level == "eigene_bereiche"
    namen = {v.name for v in stats.vergleich}
    assert namen == {"Ausbildung"}
