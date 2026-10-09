from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KlassendienstTyp(Base, TimestampMixin):
    """Ein in AbsenzDash konfigurierter WebUntis-"Klassendienst" (z. B. Entschuldigungspflicht),
    der schreibgeschuetzt angezeigt wird. Wird von der Schulleitung gepflegt, kein Seeding, siehe
    docs/superpowers/plans/2026-10-08-klassendienste-anzeige.md."""

    __tablename__ = "klassendienst_typ"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_dienst_id: Mapped[int] = mapped_column(Integer, unique=True)
    bezeichnung: Mapped[str] = mapped_column(String(100))
    kuerzel: Mapped[str] = mapped_column(String(10))
    beschreibung: Mapped[str | None] = mapped_column(String(300), nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
