from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Klasse(Base, TimestampMixin):
    """Eine Klasse ist seit diesem Modell schuljahresgebunden - WebUntis selbst behandelt eine
    Klasse bereits als jahresgebundenes Konzept (getKlassen verlangt zwingend eine schoolyearId),
    siehe docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md. Pro (webuntis_id,
    schuljahr_id) existiert genau eine Zeile statt eines pro Jahr ueberschriebenen Datensatzes -
    alte Jahre werden nie geloescht."""

    __tablename__ = "klasse"
    __table_args__ = (
        UniqueConstraint("webuntis_id", "schuljahr_id", name="uq_klasse_webuntis_id_schuljahr_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(50))
    abteilung_id: Mapped[int | None] = mapped_column(ForeignKey("abteilung.id"), nullable=True)
    webuntis_teacher1_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    webuntis_teacher2_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schuljahr_id: Mapped[int] = mapped_column(ForeignKey("schuljahr.id"), nullable=False)
