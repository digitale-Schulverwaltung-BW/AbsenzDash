from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.webuntis_client import WebUntisError
from app.models.benachrichtigung import Benachrichtigung
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
from app.services import sync_orchestrator
from app.services.eskalations_pruefung import pruefe_schwellwerte as real_pruefe_schwellwerte
from app.services.webuntis_klassen_sync import sync_klassen as real_sync_klassen
from app.services.webuntis_klassendienst_sync import KlassendienstSyncErgebnis


class _FakeWebUntisClient:
    def __init__(self, _settings):
        async def _call(method, _params):
            if method == "getSchoolyears":
                return [{"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}]
            return {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}

        self.call = AsyncMock(side_effect=_call)
        self.http = None
        self.session_id = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture(autouse=True)
def _patch_phases(monkeypatch):
    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClient)
    monkeypatch.setattr(sync_orchestrator, "sync_abteilungen", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_klassen", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_bereiche", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_kategorien", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_stundenraster", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "import_schueler", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_fehlzeiten", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_klassenbuch", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "pruefe_schwellwerte", AsyncMock())
    monkeypatch.setattr(
        sync_orchestrator, "sync_klassendienste", AsyncMock(return_value=KlassendienstSyncErgebnis())
    )


@pytest.mark.asyncio
async def test_run_full_sync_sets_letzter_sync_am_and_initial_import_flag(db_session):
    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalar_one()
    assert einstellung.letzter_sync_am is not None
    assert einstellung.initialer_import_abgeschlossen is True
    assert einstellung.schuljahr_start_cache is not None


@pytest.mark.asyncio
async def test_run_full_sync_calls_phases_in_order(db_session):
    calls = []
    sync_orchestrator.sync_abteilungen.side_effect = lambda *a: calls.append("abteilungen")
    sync_orchestrator.sync_klassen.side_effect = lambda *a, **kw: calls.append("klassen")
    sync_orchestrator.sync_bereiche.side_effect = lambda *a, **kw: calls.append("bereiche")
    sync_orchestrator.sync_kategorien.side_effect = lambda *a: calls.append("kategorien")
    sync_orchestrator.sync_stundenraster.side_effect = lambda *a: calls.append("stundenraster")
    sync_orchestrator.import_schueler.side_effect = lambda *a: calls.append("schueler")
    sync_orchestrator.sync_fehlzeiten.side_effect = lambda *a: calls.append("fehlzeiten")
    sync_orchestrator.sync_klassenbuch.side_effect = lambda *a: calls.append("klassenbuch")
    sync_orchestrator.pruefe_schwellwerte.side_effect = lambda *a: calls.append("schwellwerte")

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert calls == [
        "abteilungen", "klassen", "bereiche", "kategorien", "stundenraster",
        "schueler", "fehlzeiten", "klassenbuch", "schwellwerte",
    ]


@pytest.mark.asyncio
async def test_run_full_sync_retries_on_failure_and_succeeds(db_session, monkeypatch):
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 3)
    sync_orchestrator.sync_fehlzeiten.side_effect = [WebUntisError("boom"), None]

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert sync_orchestrator.sync_fehlzeiten.await_count == 2
    result = await db_session.execute(select(Einstellung))
    assert result.scalar_one().letzter_sync_am is not None


@pytest.mark.asyncio
async def test_run_full_sync_gives_up_after_max_attempts(db_session, monkeypatch):
    sleep_mock = AsyncMock()
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 2)
    sync_orchestrator.sync_fehlzeiten.side_effect = WebUntisError("boom")

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert sync_orchestrator.sync_fehlzeiten.await_count == 2
    assert sleep_mock.await_count == 1
    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalars().first()
    assert einstellung is None or einstellung.letzter_sync_am is None


@pytest.mark.asyncio
async def test_run_full_sync_runs_import_schueler_even_when_webuntis_step_fails(db_session, monkeypatch):
    """Regression Live-Fund 2026-09-28: import_schueler haengt nur an der lokalen ASV-CSV. Faellt ein
    WebUntis-Schritt (hier sync_klassen) aus, muss der Import trotzdem in JEDEM Versuch laufen,
    der Sync-Lauf aber weiterhin als fehlgeschlagen gelten (Retry, letzter_sync_am bleibt leer)."""
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 3)
    sync_orchestrator.sync_klassen.side_effect = WebUntisError("boom")

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert sync_orchestrator.sync_klassen.await_count == settings.webuntis_sync_retry_max_attempts
    assert sync_orchestrator.import_schueler.await_count == settings.webuntis_sync_retry_max_attempts
    sync_orchestrator.sync_fehlzeiten.assert_not_awaited()
    sync_orchestrator.pruefe_schwellwerte.assert_not_awaited()
    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalars().first()
    assert einstellung is None or einstellung.letzter_sync_am is None


@pytest.mark.asyncio
async def test_run_full_sync_runs_import_schueler_even_when_webuntis_login_fails(db_session, monkeypatch):
    """Wie oben, aber schon der Verbindungsaufbau/Login (__aenter__) schlaegt fehl."""

    class _FakeWebUntisClientLoginFehler:
        def __init__(self, _settings):
            pass

        async def __aenter__(self):
            raise WebUntisError("login boom")

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClientLoginFehler)
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 2)

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert sync_orchestrator.import_schueler.await_count == 2
    sync_orchestrator.sync_abteilungen.assert_not_awaited()
    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalars().first()
    assert einstellung is None or einstellung.letzter_sync_am is None


def test_fehlzeiten_zeitraum_with_letzter_sync_am():
    """Branch 1: letzter_sync_am is set, von = letzter_sync_am - 1 day."""
    sync_date = datetime(2024, 7, 15, 10, 30, tzinfo=timezone.utc)
    einstellung = Einstellung(letzter_sync_am=sync_date)
    heute = date(2024, 7, 20)
    schuljahr_ende = date(2025, 7, 31)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert von == date(2024, 7, 14)
    assert bis == heute


def test_fehlzeiten_zeitraum_with_schuljahr_start_cache():
    """Branch 2: schuljahr_start_cache is set, von = schuljahr_start_cache."""
    schuljahr_start = date(2024, 9, 1)
    einstellung = Einstellung(schuljahr_start_cache=schuljahr_start)
    heute = date(2024, 7, 20)
    schuljahr_ende = date(2025, 7, 31)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert von == schuljahr_start
    assert bis == heute


def test_fehlzeiten_zeitraum_fallback():
    """Branch 3: Both letzter_sync_am and schuljahr_start_cache are None, von = heute."""
    einstellung = Einstellung()
    heute = date(2024, 7, 20)
    schuljahr_ende = date(2025, 7, 31)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert von == heute
    assert bis == heute


def test_fehlzeiten_zeitraum_clamps_bis_to_schuljahr_ende_in_uebergangsluecke():
    """Regression Live-Fund 2026-07-30: Schuljahr 2025/2026 endete am 2026-07-29,
    2026/2027 ist in WebUntis noch nicht als aktuell konfiguriert - wir befinden uns
    in der Uebergangsluecke. Ohne Clamping waere bis=heute (2026-07-30), was aus dem
    Schuljahr herausfaellt und getTimetableWithAbsences mit 'startDate and endDate are
    not within a single school year' fehlschlagen laesst. bis muss stattdessen auf
    schuljahr_ende gekappt werden."""
    einstellung = Einstellung(schuljahr_start_cache=date(2025, 9, 15))
    heute = date(2026, 7, 30)
    schuljahr_ende = date(2026, 7, 29)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert bis == schuljahr_ende
    assert von <= bis


def test_fehlzeiten_zeitraum_clamps_von_to_schuljahr_start_beim_schuljahreswechsel():
    """Regression Live-Fund 2026-09-18: der letzte erfolgreiche Sync liegt noch im vorherigen
    Schuljahr (2025/2026, endete 2026-07-29), das neue Schuljahr (2026/2027, Start 2026-09-14) ist
    inzwischen aktuell. Ohne Clamping waere von=2026-07-14 (letzter_sync_am - 1 Tag) im ALTEN
    Schuljahr, waehrend bis bereits im neuen liegt -- getTimetableWithAbsences schlaegt dann mit
    'startDate and endDate are not within a single school year' fehl (WebUntis -8507). von muss
    stattdessen auf den Start des aktuellen Schuljahres (schuljahr_start_cache) gekappt werden."""
    einstellung = Einstellung(
        letzter_sync_am=datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc),
        schuljahr_start_cache=date(2026, 9, 14),
    )
    heute = date(2026, 9, 18)
    schuljahr_ende = date(2027, 7, 30)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert von == date(2026, 9, 14)
    assert bis == heute


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_uses_current_schoolyear(db_session, monkeypatch):
    client = AsyncMock()
    client.call = AsyncMock(
        side_effect=lambda method, _params: (
            [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
            if method == "getSchoolyears"
            else {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}
        )
    )

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"
    assert schuljahr.start_datum == date(2025, 9, 15)
    assert schuljahr.end_datum == date(2026, 7, 29)

    result = await db_session.execute(select(Schuljahr).order_by(Schuljahr.id))
    cached = result.scalars().all()
    assert [s.id for s in cached] == [27, 28]


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_falls_back_to_newest_cached_when_webuntis_has_none(db_session):
    """WebUntis meldet kein aktives Schuljahr (Uebergangszeitraum, siehe Live-Fund
    2026-07-30) - getCurrentSchoolyear wirft einen Fehler, getSchoolyears liefert aber
    weiterhin die volle Liste. Der Resolver faellt auf das juengste bekannte Schuljahr
    (hoechstes end_datum) zurueck, statt den ganzen Sync-Lauf abzubrechen."""
    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
        if method == "getCurrentSchoolyear":
            raise WebUntisError(
                'Cannot invoke "com.grupet.web.basic.Schoolyear.getEndDate()" because "schoolyear" is null'
            )
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_fallback_ignores_future_not_yet_started_schuljahr(db_session):
    """Regression: WebUntis meldet kein aktives Schuljahr, aber ein Admin hat bereits
    das naechste Schuljahr (2026/2027, startet erst naechsten Monat) in WebUntis
    angelegt. Der Fallback darf dieses zukuenftige Schuljahr NICHT waehlen (hoechstes
    end_datum), sonst wird schuljahr_start_cache auf ein Datum in der Zukunft gesetzt
    und jedes Eskalations-Zaehlfenster laeuft leer. Er muss stattdessen das juengste
    bereits gestartete Schuljahr (2025/2026, gestern beendet) waehlen."""
    heute = datetime.now(timezone.utc).date()
    gestern = heute - timedelta(days=1)
    naechster_monat = heute + timedelta(days=30)
    ende_naechstes_jahr = naechster_monat + timedelta(days=300)

    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {
                    "id": 27,
                    "name": "2024/2025",
                    "startDate": (heute - timedelta(days=400)).strftime("%Y%m%d"),
                    "endDate": (heute - timedelta(days=35)).strftime("%Y%m%d"),
                },
                {
                    "id": 28,
                    "name": "2025/2026",
                    "startDate": (heute - timedelta(days=34)).strftime("%Y%m%d"),
                    "endDate": gestern.strftime("%Y%m%d"),
                },
                {
                    "id": 29,
                    "name": "2026/2027",
                    "startDate": naechster_monat.strftime("%Y%m%d"),
                    "endDate": ende_naechstes_jahr.strftime("%Y%m%d"),
                },
            ]
        if method == "getCurrentSchoolyear":
            raise WebUntisError(
                'Cannot invoke "com.grupet.web.basic.Schoolyear.getEndDate()" because "schoolyear" is null'
            )
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"
    assert schuljahr.start_datum <= heute


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_falls_back_when_current_id_not_in_cache(db_session):
    """Regression: getCurrentSchoolyear liefert eine schoolyearId, die im gerade aus
    getSchoolyears aktualisierten Cache nicht enthalten ist (inkonsistente WebUntis-
    Antworten zwischen zwei Aufrufen). db.get(Schuljahr, ...) liefert dann None - der
    Resolver darf NICHT None zurueckgeben (das wuerde run_sync_once mit einem
    AttributeError ausserhalb der Retry-Behandlung abstuerzen lassen), sondern muss
    auf das juengste bereits gestartete Schuljahr zurueckfallen."""
    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
        if method == "getCurrentSchoolyear":
            return {"id": 999, "name": "unbekannt", "startDate": 20260101, "endDate": 20261231}
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr is not None
    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_prefers_date_covering_cached_row_over_stale_getcurrentschoolyear(db_session):
    """Reproduziert den Live-Fund vom 2026-09-18 (Root Cause Eskalationsstufe, siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md): WebUntis hat intern
    noch nicht auf das neue Schuljahr umgeschaltet (getCurrentSchoolyear meldet weiterhin das
    alte), obwohl getSchoolyears das neue Schuljahr laengst listet und dessen start_datum
    laut Kalenderdatum bereits begonnen hat. Der Resolver muss das per Datum passende gecachte
    Schuljahr VORZIEHEN statt sich auf die (in dieser Uebergangsphase falsche) Antwort von
    getCurrentSchoolyear zu verlassen - sonst kippt schuljahr_start_cache nicht rechtzeitig um
    und das Eskalations-Zaehlfenster zaehlt faelschlich weiter Fehlzeiten aus dem Vorjahr mit."""
    heute = datetime.now(timezone.utc).date()

    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {
                    "id": 28,
                    "name": "2025/2026",
                    "startDate": (heute - timedelta(days=365)).strftime("%Y%m%d"),
                    "endDate": (heute - timedelta(days=5)).strftime("%Y%m%d"),
                },
                {
                    "id": 29,
                    "name": "2026/2027",
                    "startDate": (heute - timedelta(days=4)).strftime("%Y%m%d"),
                    "endDate": (heute + timedelta(days=300)).strftime("%Y%m%d"),
                },
            ]
        if method == "getCurrentSchoolyear":
            # WebUntis meldet in der Uebergangsluecke noch das ALTE Schuljahr, obwohl das neue
            # laut Kalenderdatum und getSchoolyears bereits laeuft.
            return {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 29
    assert schuljahr.name == "2026/2027"


@pytest.mark.asyncio
async def test_snapshot_klassenzugehoerigkeit_bei_rollover_covers_all_schueler_including_inactive(db_session):
    schuljahr_neu = Schuljahr(id=29, name="2026/2027", start_datum=date(2026, 9, 14), end_datum=date(2027, 7, 30))
    schuljahr_alt = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=28)
    db_session.add(klasse)
    await db_session.flush()
    schueler_aktiv = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    schueler_inaktiv = Schueler(externe_id="ext-2", vorname="B", nachname="B", klasse_id=klasse.id, aktiv=False)
    schueler_ohne_klasse = Schueler(externe_id="ext-3", vorname="C", nachname="C", klasse_id=None, aktiv=True)
    db_session.add_all([schueler_aktiv, schueler_inaktiv, schueler_ohne_klasse])
    await db_session.commit()

    await sync_orchestrator._snapshot_klassenzugehoerigkeit_bei_rollover(db_session, neues_schuljahr_id=29)

    result = await db_session.execute(
        select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schuljahr_id == 29)
    )
    by_schueler_id = {h.schueler_id: h for h in result.scalars().all()}
    assert by_schueler_id[schueler_aktiv.id].klasse_id == klasse.id
    assert by_schueler_id[schueler_inaktiv.id].klasse_id == klasse.id  # auch inaktive Schueler
    assert by_schueler_id[schueler_ohne_klasse.id].klasse_id is None


@pytest.mark.asyncio
async def test_snapshot_klassenzugehoerigkeit_bei_rollover_does_not_overwrite_existing_row(db_session):
    """Falls fuer das neue Schuljahr bereits eine Zeile existiert (z.B. weil import_schueler im
    selben Sync-Lauf zufaellig vorher gelaufen ist), darf der Rollover-Snapshot sie nicht
    ueberschreiben."""
    schuljahr_neu = Schuljahr(id=29, name="2026/2027", start_datum=date(2026, 9, 14), end_datum=date(2027, 7, 30))
    schuljahr_alt = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=28)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=29)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_alt.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=29, klasse_id=klasse_neu.id))
    await db_session.commit()

    await sync_orchestrator._snapshot_klassenzugehoerigkeit_bei_rollover(db_session, neues_schuljahr_id=29)

    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(
                SchuelerKlasseHistorie.schueler_id == schueler.id, SchuelerKlasseHistorie.schuljahr_id == 29
            )
        )
    ).scalar_one()
    assert historie.klasse_id == klasse_neu.id  # unveraendert, nicht auf klasse_alt zurueckgesetzt


@pytest.mark.asyncio
async def test_run_full_sync_triggers_rollover_snapshot_only_on_real_change(db_session, monkeypatch):
    """End-to-End: beim allerersten Sync (aktuelles_schuljahr_id vorher None) und bei einem
    Sync-Lauf ohne Schuljahreswechsel darf kein Rollover-Snapshot geschrieben werden; nur wenn
    sich aktuelles_schuljahr_id tatsaechlich AENDERT."""
    aufgerufen_mit: list[int] = []
    monkeypatch.setattr(
        sync_orchestrator,
        "_snapshot_klassenzugehoerigkeit_bei_rollover",
        AsyncMock(side_effect=lambda db, neues_schuljahr_id: aufgerufen_mit.append(neues_schuljahr_id)),
    )

    # Erster Sync-Lauf: aktuelles_schuljahr_id vorher None -> kein Rollover.
    await sync_orchestrator.run_full_sync(async_session_factory)
    assert aufgerufen_mit == []

    # Zweiter Sync-Lauf mit demselben Schuljahr (id 28 laut _FakeWebUntisClient) -> weiterhin kein Rollover.
    await sync_orchestrator.run_full_sync(async_session_factory)
    assert aufgerufen_mit == []


@pytest.mark.asyncio
async def test_run_full_sync_triggers_rollover_snapshot_when_schuljahr_changes(db_session, monkeypatch):
    aufgerufen_mit: list[int] = []
    monkeypatch.setattr(
        sync_orchestrator,
        "_snapshot_klassenzugehoerigkeit_bei_rollover",
        AsyncMock(side_effect=lambda db, neues_schuljahr_id: aufgerufen_mit.append(neues_schuljahr_id)),
    )
    schuljahr_vorherig = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_vorherig)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=27))  # simuliert vorherigen Sync mit anderem Schuljahr
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)  # _FakeWebUntisClient liefert id 28

    assert aufgerufen_mit == [28]


@pytest.mark.asyncio
async def test_run_full_sync_continues_when_getklassen_fails_without_active_schoolyear(db_session, monkeypatch):
    """Reproduziert den Live-Fund vom 2026-07-30: getKlassen wirft denselben NPE wie
    getCurrentSchoolyear, wenn kein schoolyearId explizit mitgegeben wird. Mit der
    Resolver-Loesung bekommt getKlassen jetzt IMMER eine explizite schoolyearId, auch
    wenn getCurrentSchoolyear selbst fehlschlaegt - der Sync darf deshalb nicht mehr
    abbrechen, und schuljahr_start_cache/aktuelles_schuljahr_id werden korrekt auf das
    Fallback-Schuljahr gesetzt."""

    class _FakeWebUntisClientKeinAktivesSchuljahr:
        def __init__(self, _settings):
            async def _call(method, params):
                if method == "getSchoolyears":
                    return [{"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}]
                if method == "getCurrentSchoolyear":
                    raise WebUntisError('... "schoolyear" is null')
                if method == "getKlassen":
                    assert params == {"schoolyearId": 28}
                    return []
                return {}

            self.call = AsyncMock(side_effect=_call)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClientKeinAktivesSchuljahr)
    monkeypatch.setattr(sync_orchestrator, "sync_klassen", real_sync_klassen)

    vorhandener_cache = date(2025, 9, 1)
    db_session.add(Einstellung(schuljahr_start_cache=vorhandener_cache))
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalar_one()
    assert einstellung.letzter_sync_am is not None
    assert einstellung.aktuelles_schuljahr_id == 28
    assert einstellung.schuljahr_start_cache == date(2025, 9, 15)


@pytest.mark.asyncio
async def test_run_full_sync_end_to_end_triggers_benachrichtigung(db_session, monkeypatch):
    """Einziger Test in dieser Datei, der pruefe_schwellwerte NICHT mockt - prueft die reale Verdrahtung."""
    monkeypatch.setattr(sync_orchestrator, "pruefe_schwellwerte", real_pruefe_schwellwerte)

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=1, fehlzeiten_filter="alle",
            empfaenger_rollen=["schulleitung"],
        )
    )
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=date(2025, 9, 1))
    db_session.add(einstellung)
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    assert result.scalar_one().status == "kein_empfaenger"


async def _einstellung(db_session):
    db_session.expire_all()
    return (await db_session.execute(select(Einstellung))).scalar_one()


@pytest.mark.asyncio
async def test_klassendienste_laufen_beim_ersten_sync_und_setzen_zeitstempel(db_session):
    await sync_orchestrator.run_full_sync(async_session_factory)

    sync_orchestrator.sync_klassendienste.assert_awaited_once()
    assert (await _einstellung(db_session)).klassendienste_letzter_sync_am is not None


@pytest.mark.asyncio
async def test_klassendienste_laufen_nicht_wenn_letzter_lauf_juenger_als_24h(db_session):
    juengst = datetime.now(timezone.utc) - timedelta(hours=23)
    db_session.add(Einstellung(klassendienste_letzter_sync_am=juengst))
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)

    sync_orchestrator.sync_klassendienste.assert_not_awaited()
    gespeichert = (await _einstellung(db_session)).klassendienste_letzter_sync_am
    assert abs((gespeichert - juengst).total_seconds()) < 1


@pytest.mark.asyncio
async def test_klassendienste_laufen_wieder_nach_24h(db_session):
    aelter = datetime.now(timezone.utc) - timedelta(hours=24, minutes=1)
    db_session.add(Einstellung(klassendienste_letzter_sync_am=aelter))
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)

    sync_orchestrator.sync_klassendienste.assert_awaited_once()
    assert (await _einstellung(db_session)).klassendienste_letzter_sync_am > aelter


@pytest.mark.asyncio
async def test_klassendienste_ohne_aktive_typen_setzen_zeitstempel_nicht(db_session):
    sync_orchestrator.sync_klassendienste.return_value = KlassendienstSyncErgebnis(uebersprungen=True)

    await sync_orchestrator.run_full_sync(async_session_factory)

    sync_orchestrator.sync_klassendienste.assert_awaited_once()
    einstellung = await _einstellung(db_session)
    assert einstellung.klassendienste_letzter_sync_am is None
    assert einstellung.letzter_sync_am is not None


@pytest.mark.asyncio
async def test_klassendienste_fehler_bricht_haupt_sync_nicht_ab(db_session):
    sync_orchestrator.sync_klassendienste.side_effect = RuntimeError("interner Dienst kaputt")

    await sync_orchestrator.run_full_sync(async_session_factory)

    einstellung = await _einstellung(db_session)
    assert einstellung.letzter_sync_am is not None
    assert einstellung.klassendienste_letzter_sync_am is None
    sync_orchestrator.pruefe_schwellwerte.assert_awaited_once()


@pytest.mark.asyncio
async def test_klassendienste_unerwarteter_fehler_bricht_haupt_sync_nicht_ab(db_session):
    sync_orchestrator.sync_klassendienste.side_effect = KeyError("matrix")

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert (await _einstellung(db_session)).letzter_sync_am is not None
