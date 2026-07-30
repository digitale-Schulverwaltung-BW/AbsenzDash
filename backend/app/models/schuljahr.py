from __future__ import annotations

from datetime import date

from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Schuljahr(Base, TimestampMixin):
    """Cache der WebUntis-Schuljahre (getSchoolyears), bei jedem Sync-Lauf per Upsert
    aktualisiert. `id` ist die WebUntis-schoolyearId, kein eigener Autoincrement - alte
    Schuljahre werden nie geloescht, auch wenn WebUntis sie irgendwann nicht mehr liefert."""

    __tablename__ = "schuljahr"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(20))
    start_datum: Mapped[date] = mapped_column(Date)
    end_datum: Mapped[date] = mapped_column(Date)
