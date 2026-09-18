from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchuelerKlasseHistorie(Base, TimestampMixin):
    """Ein Snapshot pro Schueler und Schuljahr (wie ein Zeugnis-Eintrag) - keine unterjaehrige
    Wechsel-Historie. Geschrieben/aktualisiert vom ASV-CSV-Import (fuer das jeweils aktuelle
    Schuljahr, bei jedem Import) und einmalig fuer ALLE Schueler beim Erkennen eines echten
    Schuljahreswechsels in sync_orchestrator.py. Fehlende Zeilen (Schuljahre vor Einfuehrung
    dieses Features) bedeuten explizit 'unbekannt', nicht 'aktuelle Klasse', siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md."""

    __tablename__ = "schueler_klasse_historie"
    __table_args__ = (
        UniqueConstraint("schueler_id", "schuljahr_id", name="uq_schueler_klasse_historie_schueler_schuljahr"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    schuljahr_id: Mapped[int] = mapped_column(ForeignKey("schuljahr.id", ondelete="CASCADE"))
    klasse_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("klasse.id", ondelete="SET NULL"), nullable=True
    )
