from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class SchwellwertStufeIn(BaseModel):
    id: int | None = None
    stufe_nr: int
    einheit: str | None = None
    schwellenwert: int
    fehlzeiten_filter: str | None = None
    empfaenger_rollen: list[str]


class SchwellwertStufeOut(BaseModel):
    id: int
    stufe_nr: int
    einheit: str | None
    schwellenwert: int
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
    betroffene_regel_ids: list[int] = []


class MeasureTypeOut(BaseModel):
    id: int
    name: str
    setzt_zaehler_zurueck: bool
    aktiv: bool
    betroffene_regel_ids: list[int]


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


class SyncSettingsOut(BaseModel):
    sync_interval_cron: str
    schuljahr_start_cache: date | None
    letzter_sync_am: datetime | None


class SyncSettingsIn(BaseModel):
    sync_interval_cron: str


class SyncNowOut(BaseModel):
    status: str
    abgeschlossen_am: datetime


class WebUntisTeacherOut(BaseModel):
    id: int
    kuerzel: str
