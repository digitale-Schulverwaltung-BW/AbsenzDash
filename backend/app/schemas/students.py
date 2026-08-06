from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class KlasseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ZaehlerstandOut(BaseModel):
    aktueller_stand: float
    erreichte_stufe_nr: int | None


class FehlzeitSplitOut(BaseModel):
    gesamt: float
    entschuldigt: float
    unentschuldigt: float


class BenachrichtigungOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    regel_id: int | None
    typ: str | None
    stufe_nr: int
    gesendet_am: datetime
    empfaenger: list[dict[str, Any]]
    status: str


class StudentOverviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vorname: str
    nachname: str
    klasse: KlasseOut | None
    zaehlerstand: dict[str, ZaehlerstandOut] | None = None
    letzte_benachrichtigung: BenachrichtigungOut | None = None
    ohne_massnahme_seit_benachrichtigung: bool | None = None
    fehltage: FehlzeitSplitOut | None = None
    fehlstunden: FehlzeitSplitOut | None = None
    klassenbuch_anzahl: int | None = None


class StudentListOut(BaseModel):
    items: list[StudentOverviewOut]
    total: int
    limit: int
    offset: int


class FehlzeitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    typ: str
    datum: date
    start_zeit: int
    end_zeit: int
    fach: str | None
    excuse_status_id: int | None
    grund_text: str | None


class KlassenbuchEintragOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kategorie_id: int
    datum: date
    text: str | None
    lesson_id: int | None


class MassnahmeOut(BaseModel):
    id: int
    massnahmen_typ_id: int
    massnahmen_typ_name: str
    datum: date
    notiz: str | None
    erfasst_von_nutzer_id: int
    erfasst_von_name: str


class AusnahmeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kategorie: str
    grund: str
    gueltig_bis: date | None
    aktiv: bool


class StudentDetailOut(BaseModel):
    id: int
    vorname: str
    nachname: str
    klasse: KlasseOut | None
    zaehlerstand: dict[str, ZaehlerstandOut]
    fehltage: FehlzeitSplitOut
    fehlstunden: FehlzeitSplitOut
    klassenbuch_anzahl: int
    fehlzeiten: list[FehlzeitOut]
    klassenbuch: list[KlassenbuchEintragOut]
    massnahmen: list[MassnahmeOut]
    ausnahmen: list[AusnahmeOut]
    benachrichtigungen: list[BenachrichtigungOut]


class MeasureCreateIn(BaseModel):
    massnahmen_typ_id: int
    datum: date
    notiz: str | None = None


class ExemptionCreateIn(BaseModel):
    kategorie: Literal["fehlzeiten", "klassenbuch"]
    grund: str
    gueltig_bis: date | None = None


class MassnahmenTypCatalogOut(BaseModel):
    id: int
    name: str


class ExcuseStatusCatalogOut(BaseModel):
    id: int
    name: str
    long_name: str | None


class ClassregCategoryCatalogOut(BaseModel):
    id: int
    name: str
    long_name: str | None


class StudentCatalogOut(BaseModel):
    massnahmen_typen: list[MassnahmenTypCatalogOut]
    excuse_statuses: list[ExcuseStatusCatalogOut]
    classreg_categories: list[ClassregCategoryCatalogOut]
