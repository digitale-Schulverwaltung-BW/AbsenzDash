from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class SchwellwertStufeIn(BaseModel):
    id: int | None = None
    stufe_nr: int
    einheit: str | None = None
    schwellenwert: float
    fehlzeiten_filter: str | None = None
    empfaenger_rollen: list[str]


class SchwellwertStufeOut(BaseModel):
    id: int
    stufe_nr: int
    einheit: str | None
    schwellenwert: float
    fehlzeiten_filter: str | None
    empfaenger_rollen: list[str]


class ThresholdRuleIn(BaseModel):
    id: int | None = None
    typ: str
    geltungsbereich: str
    abteilung_id: int | None = None
    klasse_id: int | None = None
    stufen: list[SchwellwertStufeIn]


class ThresholdRuleOut(BaseModel):
    id: int
    typ: str
    geltungsbereich: str
    abteilung_id: int | None
    klasse_id: int | None
    stufen: list[SchwellwertStufeOut]


class MeasureTypeIn(BaseModel):
    id: int | None = None
    name: str
    setzt_zaehler_zurueck: bool
    aktiv: bool = True


class MeasureTypeOut(BaseModel):
    id: int
    name: str
    setzt_zaehler_zurueck: bool
    aktiv: bool = True


class ExcuseStatusIn(BaseModel):
    id: int | None = None
    name: str
    long_name: str | None = None
    zaehlt_als_entschuldigt: bool
    aktiv: bool = True


class ExcuseStatusOut(BaseModel):
    id: int
    name: str
    long_name: str | None
    zaehlt_als_entschuldigt: bool
    aktiv: bool


class SyncSchuljahrOut(BaseModel):
    id: int
    name: str


class SyncSettingsOut(BaseModel):
    sync_interval_cron: str
    schuljahr_start_cache: date | None
    letzter_sync_am: datetime | None
    aktuelles_schuljahr: SyncSchuljahrOut | None


class SyncSettingsIn(BaseModel):
    sync_interval_cron: str


class SyncNowOut(BaseModel):
    status: str
    abgeschlossen_am: datetime


class TestEmailOut(BaseModel):
    status: str
    empfaenger: str


class WebUntisTeacherOut(BaseModel):
    id: int
    kuerzel: str


class AbteilungOut(BaseModel):
    id: int
    name: str


class BereichLeiterIn(BaseModel):
    wp_user_id: str
    email: str
    name: str
    rolle: str


class BereichLeiterOut(BaseModel):
    nutzer_id: int
    wp_user_id: str
    email: str
    name: str


class BereichIn(BaseModel):
    id: int
    ausgeblendet: bool
    leiter: list[BereichLeiterIn] = []


class BereichOut(BaseModel):
    id: int
    name: str
    klasse_namen: list[str]
    ausgeblendet: bool
    leiter: list[BereichLeiterOut]


class HistorieImportPreviewOut(BaseModel):
    zeilen_gesamt: int
    schueler_bekannt: int
    schueler_neu: int
    unbekannte_klassen: list[str]
    uebersprungene_zeilen: int


class HistorieImportResultOut(BaseModel):
    zeilen_verarbeitet: int
    neu_angelegte_schueler: int
    uebersprungene_zeilen: int
