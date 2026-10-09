import logging
from datetime import date

import pytest
from sqlalchemy import select

from app.integrations.webuntis_duty_client import DutyServiceError
from app.models.klasse import Klasse
from app.models.klassendienst_typ import KlassendienstTyp
from app.models.schueler import Schueler
from app.models.schueler_klassendienst import SchuelerKlassendienst
from app.services.webuntis_klassendienst_sync import (
    MAX_AUFEINANDERFOLGENDE_FEHLER,
    sync_klassendienste,
    wochen_zu_zeitraeume,
)

HEUTE = date(2026, 10, 8)


# --- Wochen -> Zeitraeume ---


def _ends(week_ids):
    from datetime import datetime, timedelta

    return {
        w: int((datetime.strptime(str(w), "%Y%m%d") + timedelta(days=6)).strftime("%Y%m%d")) for w in week_ids
    }


def test_wochen_zusammenhaengend_ergeben_ein_zeitraum():
    wochen = [20260928, 20261005, 20261012]
    assert wochen_zu_zeitraeume(wochen, _ends(wochen)) == [(date(2026, 9, 28), date(2026, 10, 18))]


def test_wochen_mit_luecke_ergeben_zwei_zeitraeume():
    wochen = [20260928, 20261005, 20261026]
    assert wochen_zu_zeitraeume(wochen, _ends(wochen)) == [
        (date(2026, 9, 28), date(2026, 10, 11)),
        (date(2026, 10, 26), date(2026, 11, 1)),
    ]


def test_wochen_jahreswechsel_bleibt_zusammenhaengend():
    wochen = [20261221, 20261228, 20270104]
    assert wochen_zu_zeitraeume(wochen, _ends(wochen)) == [(date(2026, 12, 21), date(2027, 1, 10))]


def test_einzelwoche():
    assert wochen_zu_zeitraeume([20260928], {20260928: 20261004}) == [(date(2026, 9, 28), date(2026, 10, 4))]


def test_unsortierte_eingabe_und_duplikate():
    wochen = [20261012, 20260928, 20261005, 20260928]
    assert wochen_zu_zeitraeume(wochen, _ends(wochen)) == [(date(2026, 9, 28), date(2026, 10, 18))]


def test_leere_eingabe_und_ungueltige_werte():
    assert wochen_zu_zeitraeume([]) == []
    assert wochen_zu_zeitraeume(["abc", None, 20261399]) == []


def test_bis_nutzt_end_date_der_letzten_woche_sonst_sonntag():
    assert wochen_zu_zeitraeume([20260928, 20261005], {20261005: 20261010}) == [(date(2026, 9, 28), date(2026, 10, 10))]
    assert wochen_zu_zeitraeume([20260928, 20261005]) == [(date(2026, 9, 28), date(2026, 10, 11))]


def test_string_wochen_ids_werden_akzeptiert():
    assert wochen_zu_zeitraeume(["20260928"], {20260928: "20261004"}) == [(date(2026, 9, 28), date(2026, 10, 4))]


# --- Sync ---


class FakeDutyClient:
    def __init__(self, students=None, matrices=None, fail_for=None):
        self.students = students or []
        self.matrices = matrices or {}  # (klassen_id, dienst_id) -> matrix
        self.fail_for = fail_for or set()
        self.calls = []
        self.students_calls = 0

    async def get_students(self):
        self.students_calls += 1
        return self.students

    async def get_scheduler_data(self, klassen_id, dienst_id):
        self.calls.append((klassen_id, dienst_id))
        if (klassen_id, dienst_id) in self.fail_for:
            raise DutyServiceError("http_error", "HTTP 500")
        return {"matrix": self.matrices.get((klassen_id, dienst_id), {"rows": [], "columns": []})}


def _matrix(rows, weeks=(20260928, 20261005)):
    from datetime import datetime, timedelta

    return {
        "columns": [
            {"id": w, "endDate": int((datetime.strptime(str(w), "%Y%m%d") + timedelta(days=6)).strftime("%Y%m%d"))}
            for w in weeks
        ],
        "rows": rows,
    }


def _row(wu_id, relations, name="Geheim"):
    return {"studentDTO": {"id": wu_id, "name": name, "foreName": "Vorname" + name}, "relations": relations, "absences": []}


@pytest.fixture
async def aufbau(db_session, schuljahr):
    klasse = Klasse(webuntis_id=3836, name="2BFE1", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    typ = KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="Entschuldigungspflicht", kuerzel="E", aktiv=True)
    db_session.add(typ)
    await db_session.flush()
    s1 = Schueler(externe_id="uuid-1", vorname="Anna", nachname="Alpha", klasse_id=klasse.id, aktiv=True)
    s2 = Schueler(externe_id="uuid-2", vorname="Ben", nachname="Beta", klasse_id=klasse.id, aktiv=True)
    s3 = Schueler(externe_id="uuid-3", vorname="Cem", nachname="Gamma", klasse_id=klasse.id, aktiv=True)
    db_session.add_all([s1, s2, s3])
    await db_session.commit()
    return {"klasse": klasse, "typ": typ, "s1": s1, "s2": s2, "s3": s3, "schuljahr": schuljahr}


async def _zeilen(db):
    return (
        await db.execute(
            select(SchuelerKlassendienst)
            .order_by(SchuelerKlassendienst.schueler_id, SchuelerKlassendienst.von)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()


async def test_ohne_aktive_typen_wird_komplett_uebersprungen(db_session, aufbau):
    aufbau["typ"].aktiv = False
    await db_session.commit()
    client = FakeDutyClient()
    ergebnis = await sync_klassendienste(client, db_session, HEUTE)
    assert ergebnis.uebersprungen is True
    assert client.calls == [] and client.students_calls == 0


async def test_ohne_konfigurierte_typen_wird_uebersprungen(db_session, schuljahr):
    client = FakeDutyClient()
    ergebnis = await sync_klassendienste(client, db_session, HEUTE)
    assert ergebnis.uebersprungen is True
    assert client.students_calls == 0


async def test_treffer_schreibt_zeitraum(db_session, aufbau):
    client = FakeDutyClient(
        students=[{"id": 101, "key": "uuid-1", "name": "Alpha"}, {"id": 102, "key": "uuid-2"}],
        matrices={(3836, 26): _matrix([_row(101, [20260928, 20261005]), _row(102, [])])},
    )
    ergebnis = await sync_klassendienste(client, db_session, HEUTE)
    await db_session.commit()
    zeilen = await _zeilen(db_session)
    assert [(z.schueler_id, z.klassendienst_typ_id, z.von, z.bis) for z in zeilen] == [
        (aufbau["s1"].id, aufbau["typ"].id, date(2026, 9, 28), date(2026, 10, 11))
    ]
    assert ergebnis.klassen_ok == 1 and ergebnis.nicht_zuordenbar == 0 and ergebnis.zeilen == 1


async def test_key_fehlt_oder_nicht_in_db_wird_uebersprungen_und_gezaehlt(db_session, aufbau, caplog):
    caplog.set_level(logging.DEBUG)
    client = FakeDutyClient(
        students=[
            {"id": 101, "key": "uuid-1", "name": "Alpha"},
            {"id": 102, "name": "OhneKey"},  # key fehlt
            {"id": 103, "key": "unbekannt-in-db", "name": "Fremd"},
        ],
        matrices={
            (3836, 26): _matrix(
                [
                    _row(101, [20260928], name="Alpha"),
                    _row(102, [20260928], name="OhneKey"),
                    _row(103, [20260928], name="Fremd"),
                    _row(999, [20260928], name="NichtInGetStudents"),
                    _row(104, [], name="OhnePflicht"),
                ]
            )
        },
    )
    ergebnis = await sync_klassendienste(client, db_session, HEUTE)
    await db_session.commit()
    assert ergebnis.nicht_zuordenbar == 3
    assert [z.schueler_id for z in await _zeilen(db_session)] == [aufbau["s1"].id]
    warnungen = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("3 Schueler" in r.getMessage() and "2BFE1" in r.getMessage() for r in warnungen)
    for name in ("Alpha", "OhneKey", "Fremd", "NichtInGetStudents", "Vorname", "Anna", "uuid-1"):
        assert name not in caplog.text


async def test_kein_namens_fallback(db_session, aufbau):
    # Schueler "Anna Alpha" existiert in der DB, aber der key passt nicht -> nicht zugeordnet.
    client = FakeDutyClient(
        students=[{"id": 101, "key": "anderer-key", "name": "Alpha", "foreName": "Anna"}],
        matrices={(3836, 26): _matrix([_row(101, [20260928])])},
    )
    ergebnis = await sync_klassendienste(client, db_session, HEUTE)
    await db_session.commit()
    assert ergebnis.nicht_zuordenbar == 1
    assert await _zeilen(db_session) == []


async def test_neuschreiben_ersetzt_und_entfernt_alte_zeilen(db_session, aufbau):
    db_session.add_all(
        [
            SchuelerKlassendienst(
                schueler_id=aufbau["s1"].id, klassendienst_typ_id=aufbau["typ"].id, von=date(2026, 1, 5), bis=date(2026, 1, 11)
            ),
            SchuelerKlassendienst(
                schueler_id=aufbau["s2"].id, klassendienst_typ_id=aufbau["typ"].id, von=date(2026, 9, 28), bis=date(2026, 10, 4)
            ),
        ]
    )
    await db_session.commit()
    client = FakeDutyClient(
        students=[{"id": 101, "key": "uuid-1"}, {"id": 102, "key": "uuid-2"}, {"id": 103, "key": "uuid-3"}],
        matrices={(3836, 26): _matrix([_row(101, [20261005]), _row(103, [20260928])])},
    )
    await sync_klassendienste(client, db_session, HEUTE)
    await db_session.commit()
    ergebnis = [(z.schueler_id, z.von) for z in await _zeilen(db_session)]
    assert ergebnis == [(aufbau["s1"].id, date(2026, 10, 5)), (aufbau["s3"].id, date(2026, 9, 28))]


async def test_zweimal_ausfuehren_ist_idempotent(db_session, aufbau):
    client = FakeDutyClient(
        students=[{"id": 101, "key": "uuid-1"}],
        matrices={(3836, 26): _matrix([_row(101, [20260928, 20261012])])},
    )
    await sync_klassendienste(client, db_session, HEUTE)
    await db_session.commit()
    await sync_klassendienste(client, db_session, HEUTE)
    await db_session.commit()
    assert len(await _zeilen(db_session)) == 2


async def test_klassenfehler_isoliert_alte_zeilen_bleiben(db_session, aufbau, caplog):
    klasse2 = Klasse(webuntis_id=4000, name="1ABC", schuljahr_id=aufbau["schuljahr"].id)
    db_session.add(klasse2)
    await db_session.flush()
    s4 = Schueler(externe_id="uuid-4", vorname="Dora", nachname="Delta", klasse_id=klasse2.id, aktiv=True)
    db_session.add_all(
        [
            s4,
            SchuelerKlassendienst(
                schueler_id=aufbau["s1"].id, klassendienst_typ_id=aufbau["typ"].id, von=date(2026, 1, 5), bis=date(2026, 1, 11)
            ),
        ]
    )
    await db_session.commit()
    client = FakeDutyClient(
        students=[{"id": 101, "key": "uuid-1"}, {"id": 104, "key": "uuid-4"}],
        matrices={(4000, 26): _matrix([_row(104, [20260928])])},
        fail_for={(3836, 26)},
    )
    with caplog.at_level(logging.WARNING):
        ergebnis = await sync_klassendienste(client, db_session, HEUTE)
    await db_session.commit()
    assert ergebnis.klassen_fehler == 1 and ergebnis.klassen_ok == 1
    paare = {(z.schueler_id, z.von) for z in await _zeilen(db_session)}
    assert paare == {(aufbau["s1"].id, date(2026, 1, 5)), (s4.id, date(2026, 9, 28))}
    assert "1 von 2" in caplog.text


async def test_viele_fehler_in_folge_brechen_lauf_ab(db_session, aufbau):
    for i in range(MAX_AUFEINANDERFOLGENDE_FEHLER + 2):
        db_session.add(Klasse(webuntis_id=5000 + i, name=f"K{i}", schuljahr_id=aufbau["schuljahr"].id))
    await db_session.commit()
    fail = {(3836, 26)} | {(5000 + i, 26) for i in range(MAX_AUFEINANDERFOLGENDE_FEHLER + 2)}
    client = FakeDutyClient(students=[], fail_for=fail)
    with pytest.raises(DutyServiceError):
        await sync_klassendienste(client, db_session, HEUTE)
    assert len(client.calls) == MAX_AUFEINANDERFOLGENDE_FEHLER


async def test_nur_klassen_des_angegebenen_schuljahres(db_session, aufbau):
    from app.models.schuljahr import Schuljahr

    altes = Schuljahr(id=2, name="2024/2025", start_datum=date(2024, 9, 1), end_datum=date(2025, 7, 31))
    db_session.add(altes)
    await db_session.flush()
    db_session.add(Klasse(webuntis_id=7777, name="ALT", schuljahr_id=altes.id))
    await db_session.commit()
    client = FakeDutyClient(students=[])
    await sync_klassendienste(client, db_session, HEUTE, schuljahr_id=aufbau["schuljahr"].id)
    assert client.calls == [(3836, 26)]


async def test_kein_logging_von_token_oder_cookies_bei_dienstfehler(db_session, aufbau, caplog):
    caplog.set_level(logging.DEBUG)
    client = FakeDutyClient(students=[{"id": 101, "key": "uuid-1", "name": "Alpha"}], fail_for={(3836, 26)})
    await sync_klassendienste(client, db_session, HEUTE)
    assert "Alpha" not in caplog.text
