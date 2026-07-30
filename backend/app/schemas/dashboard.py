from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class NavBereichOut(BaseModel):
    id: int
    name: str


class NavKlasseOut(BaseModel):
    id: int
    name: str
    bereich_id: int | None


class NavSchuljahrOut(BaseModel):
    id: int
    name: str
    start_datum: date
    end_datum: date


class NavOptionsOut(BaseModel):
    bereiche: list[NavBereichOut]
    klassen: list[NavKlasseOut]
    rolle: str
    schuljahre: list[NavSchuljahrOut]


class StatsOwn(BaseModel):
    anzahl_schueler: int
    avg_fehltage: float
    avg_fehlstunden: float
    avg_klassenbuch: float
    anzahl_klassenbuch: int
    anzahl_massnahmen: int


class StatsVergleichEintrag(StatsOwn):
    id: int
    name: str


class StatsContext(BaseModel):
    bereich_id: int | None
    bereich_name: str | None
    klasse_id: int | None
    klasse_name: str | None


StatsLevel = Literal["schule", "eigene_bereiche", "bereich", "eigene_klassen", "klasse"]


class StatsOut(BaseModel):
    level: StatsLevel
    context: StatsContext
    own: StatsOwn
    vergleich: list[StatsVergleichEintrag]
