from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.nutzer import ROLLEN
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
from app.schemas.admin import SchwellwertStufeIn, SchwellwertStufeOut, ThresholdRuleIn, ThresholdRuleOut

TYPEN = ("fehlzeiten", "klassenbuch")
GELTUNGSBEREICHE = ("schulweit", "abteilung", "klasse")
EINHEITEN = ("fehltage", "fehlstunden")
FEHLZEITEN_FILTER = ("nur_unentschuldigt", "alle")


def _stufe_out(stufe: SchwellwertStufe) -> SchwellwertStufeOut:
    return SchwellwertStufeOut(
        id=stufe.id,
        stufe_nr=stufe.stufe_nr,
        einheit=stufe.einheit,
        schwellenwert=stufe.schwellenwert,
        fehlzeiten_filter=stufe.fehlzeiten_filter,
        empfaenger_rollen=list(stufe.empfaenger_rollen),
    )


async def _regel_out(db: AsyncSession, regel: SchwellwertRegel) -> ThresholdRuleOut:
    stufen_result = await db.execute(
        select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id).order_by(SchwellwertStufe.stufe_nr)
    )
    return ThresholdRuleOut(
        id=regel.id,
        typ=regel.typ,
        geltungsbereich=regel.geltungsbereich,
        abteilung_id=regel.abteilung_id,
        klasse_id=regel.klasse_id,
        stufen=[_stufe_out(s) for s in stufen_result.scalars().all()],
    )


async def list_rules(db: AsyncSession) -> list[ThresholdRuleOut]:
    result = await db.execute(select(SchwellwertRegel).order_by(SchwellwertRegel.id))
    return [await _regel_out(db, r) for r in result.scalars().all()]


def _validate_no_duplicate_ids(payload: list[ThresholdRuleIn]) -> None:
    """Zwei Payload-Einträge mit derselben id würden sich sonst still gegenseitig überschreiben."""
    seen_regel_ids: set[int] = set()
    seen_stufe_ids: set[int] = set()
    for regel in payload:
        if regel.id is not None:
            if regel.id in seen_regel_ids:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate id in payload: {regel.id}")
            seen_regel_ids.add(regel.id)
        for stufe in regel.stufen:
            if stufe.id is None:
                continue
            if stufe.id in seen_stufe_ids:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate stufe id in payload: {stufe.id}")
            seen_stufe_ids.add(stufe.id)


def _validate_payload_shape(payload: list[ThresholdRuleIn]) -> None:
    _validate_no_duplicate_ids(payload)
    seen_schulweit: set[str] = set()
    seen_abteilung: set[tuple[str, int]] = set()
    seen_klasse: set[tuple[str, int]] = set()

    for regel in payload:
        if regel.typ not in TYPEN:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown typ: {regel.typ}")
        if regel.geltungsbereich not in GELTUNGSBEREICHE:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown geltungsbereich: {regel.geltungsbereich}")

        if regel.geltungsbereich == "schulweit":
            if regel.abteilung_id is not None or regel.klasse_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "schulweit rule must not set abteilung_id/klasse_id")
            if regel.typ in seen_schulweit:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate schulweit rule for typ={regel.typ}")
            seen_schulweit.add(regel.typ)
        elif regel.geltungsbereich == "abteilung":
            if regel.abteilung_id is None or regel.klasse_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "abteilung rule needs abteilung_id and no klasse_id")
            key = (regel.typ, regel.abteilung_id)
            if key in seen_abteilung:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate rule for typ={regel.typ}, abteilung_id={regel.abteilung_id}")
            seen_abteilung.add(key)
        else:
            if regel.klasse_id is None or regel.abteilung_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "klasse rule needs klasse_id and no abteilung_id")
            key = (regel.typ, regel.klasse_id)
            if key in seen_klasse:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate rule for typ={regel.typ}, klasse_id={regel.klasse_id}")
            seen_klasse.add(key)

        if not regel.stufen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Rule needs at least one Stufe")

        seen_stufe_nr: set[int] = set()
        for stufe in regel.stufen:
            if stufe.stufe_nr in seen_stufe_nr:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate stufe_nr {stufe.stufe_nr} in rule")
            seen_stufe_nr.add(stufe.stufe_nr)
            if regel.typ == "fehlzeiten" and stufe.einheit not in EINHEITEN:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid einheit for fehlzeiten-Regel: {stufe.einheit}")
            if regel.typ == "klassenbuch" and stufe.einheit is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "klassenbuch-Regel must not set einheit")
            if stufe.fehlzeiten_filter is not None and stufe.fehlzeiten_filter not in FEHLZEITEN_FILTER:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid fehlzeiten_filter: {stufe.fehlzeiten_filter}")
            if not stufe.empfaenger_rollen:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empfaenger_rollen must not be empty")
            for rolle in stufe.empfaenger_rollen:
                if rolle not in ROLLEN:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown rolle: {rolle}")


async def _validate_references_exist(db: AsyncSession, payload: list[ThresholdRuleIn]) -> None:
    abteilung_ids = {r.abteilung_id for r in payload if r.abteilung_id is not None}
    if abteilung_ids:
        result = await db.execute(select(Abteilung.id).where(Abteilung.id.in_(abteilung_ids)))
        missing = abteilung_ids - set(result.scalars().all())
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown abteilung_id(s): {sorted(missing)}")

    klasse_ids = {r.klasse_id for r in payload if r.klasse_id is not None}
    if klasse_ids:
        result = await db.execute(select(Klasse.id).where(Klasse.id.in_(klasse_ids)))
        missing = klasse_ids - set(result.scalars().all())
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown klasse_id(s): {sorted(missing)}")


async def replace_rules(db: AsyncSession, payload: list[ThresholdRuleIn], nutzer_id: int) -> list[ThresholdRuleOut]:
    _validate_payload_shape(payload)
    await _validate_references_exist(db, payload)

    existing_result = await db.execute(select(SchwellwertRegel))
    existing_by_id = {r.id: r for r in existing_result.scalars().all()}

    existing_stufen_by_regel: dict[int, dict[int, SchwellwertStufe]] = {}
    for regel_in in payload:
        if regel_in.id is None:
            for stufe_in in regel_in.stufen:
                if stufe_in.id is not None:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"Unknown stufe id {stufe_in.id}: rule is new and has no existing stufen",
                    )
            continue
        if regel_in.id not in existing_by_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown threshold rule id: {regel_in.id}")
        stufen_result = await db.execute(select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel_in.id))
        stufen_by_id = {s.id: s for s in stufen_result.scalars().all()}
        for stufe_in in regel_in.stufen:
            if stufe_in.id is not None and stufe_in.id not in stufen_by_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown stufe id {stufe_in.id} for rule {regel_in.id}")
        existing_stufen_by_regel[regel_in.id] = stufen_by_id

    payload_ids = {r.id for r in payload if r.id is not None}

    try:
        # Phase 0: Löschungen zuerst und sofort flushen. SQLAlchemys Unit of Work schreibt
        # INSERTs/UPDATEs innerhalb eines Flushes vor DELETEs — ohne dieses vorgezogene Flush
        # kollidiert eine neu angelegte Regel mit der im selben Request entfernten alten Regel
        # (partielle Unique-Indizes uq_schwellwert_regel_schulweit/_abteilung/_klasse).
        for regel_id, regel in list(existing_by_id.items()):
            if regel_id not in payload_ids:
                await db.delete(regel)
        await db.flush()

        # stufe_nr nimmt an uq_schwellwert_stufe_regel_stufe_nr teil: ein direktes Umnummerieren
        # bestehender Stufen (z.B. Vertauschen von 1 und 2) erzeugt zwischenzeitlich ein doppeltes
        # (regel_id, stufe_nr)-Paar. Deshalb zweiphasig: erst ein kollisionsfreier Sentinel
        # (-stufe.id, immer negativ und eindeutig), dann der echte Wert. Die Stufen-id bleibt dabei
        # stabil (kein Löschen/Neuanlegen).
        pending_stufe_finalize: list[tuple[SchwellwertStufe, int]] = []
        pending_stufe_create: list[tuple[SchwellwertRegel, SchwellwertStufeIn]] = []

        for regel_in in payload:
            if regel_in.id is not None:
                regel = existing_by_id[regel_in.id]
                regel.typ = regel_in.typ
                regel.geltungsbereich = regel_in.geltungsbereich
                regel.abteilung_id = regel_in.abteilung_id
                regel.klasse_id = regel_in.klasse_id
                existing_stufen_by_id = existing_stufen_by_regel[regel_in.id]
            else:
                regel = SchwellwertRegel(
                    typ=regel_in.typ,
                    geltungsbereich=regel_in.geltungsbereich,
                    abteilung_id=regel_in.abteilung_id,
                    klasse_id=regel_in.klasse_id,
                )
                db.add(regel)
                await db.flush()
                existing_stufen_by_id = {}

            stufen_payload_ids = {s.id for s in regel_in.stufen if s.id is not None}
            for stufe_id, stufe in existing_stufen_by_id.items():
                if stufe_id not in stufen_payload_ids:
                    await db.delete(stufe)

            for stufe_in in regel_in.stufen:
                if stufe_in.id is not None:
                    stufe = existing_stufen_by_id[stufe_in.id]
                    stufe.stufe_nr = -stufe.id  # Phase 1: temporärer, kollisionsfreier Platzhalter
                    stufe.einheit = stufe_in.einheit
                    stufe.schwellenwert = stufe_in.schwellenwert
                    stufe.fehlzeiten_filter = stufe_in.fehlzeiten_filter
                    stufe.empfaenger_rollen = stufe_in.empfaenger_rollen
                    pending_stufe_finalize.append((stufe, stufe_in.stufe_nr))
                else:
                    pending_stufe_create.append((regel, stufe_in))

        await db.flush()

        # Phase 2: echte stufe_nr setzen; erst danach neue Stufen anlegen (SQLAlchemy schreibt
        # UPDATEs vor INSERTs, die freigewordenen Nummern sind damit sicher belegbar).
        for stufe, finaler_stufe_nr in pending_stufe_finalize:
            stufe.stufe_nr = finaler_stufe_nr
        for regel, stufe_in in pending_stufe_create:
            db.add(
                SchwellwertStufe(
                    regel_id=regel.id,
                    stufe_nr=stufe_in.stufe_nr,
                    einheit=stufe_in.einheit,
                    schwellenwert=stufe_in.schwellenwert,
                    fehlzeiten_filter=stufe_in.fehlzeiten_filter,
                    empfaenger_rollen=stufe_in.empfaenger_rollen,
                )
            )

        db.add(
            AuditLog(
                user_id=nutzer_id,
                aktion="admin_threshold_rules_updated",
                resource_typ="schwellwert_regel",
                details={"anzahl_regeln": len(payload)},
            )
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Konflikt beim Speichern der Schwellwert-Regeln — vermutlich eine widersprüchliche "
            "Zuordnung (z.B. zwei aktive Regeln mit demselben Geltungsbereich). Bitte Eingabe prüfen.",
        )

    return await list_rules(db)
