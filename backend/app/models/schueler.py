from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Schueler(Base, TimestampMixin):
    __tablename__ = "schueler"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    webuntis_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vorname: Mapped[str] = mapped_column(String(100))
    nachname: Mapped[str] = mapped_column(String(100))
    klasse_id: Mapped[int | None] = mapped_column(ForeignKey("klasse.id"), nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=False)
    klassenzuordnung_aktualisiert_am: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
