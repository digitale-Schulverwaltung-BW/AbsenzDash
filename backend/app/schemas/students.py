from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class KlasseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ZaehlerstandOut(BaseModel):
    aktueller_stand: int
    erreichte_stufe_nr: int | None


class BenachrichtigungOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    regel_id: int | None
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
    zaehlerstand: dict[str, ZaehlerstandOut]
    letzte_benachrichtigung: BenachrichtigungOut | None
    ohne_massnahme_seit_benachrichtigung: bool


class StudentListOut(BaseModel):
    items: list[StudentOverviewOut]
    total: int
    limit: int
    offset: int
