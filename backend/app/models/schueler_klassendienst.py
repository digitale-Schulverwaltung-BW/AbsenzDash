from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchuelerKlassendienst(Base, TimestampMixin):
    """Zeitraum, in dem ein Schueler einen Klassendienst hat (aus WebUntis importiert, nur Anzeige).
    `von` = Montag der ersten Woche, `bis` = Sonntag der letzten Woche des zusammenhaengenden
    Blocks. Gespeichert werden nur Zuordnung, Typ und Zeitraum, keine Namen."""

    __tablename__ = "schueler_klassendienst"
    __table_args__ = (
        UniqueConstraint("schueler_id", "klassendienst_typ_id", "von", name="uq_schueler_klassendienst_schueler_typ_von"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    klassendienst_typ_id: Mapped[int] = mapped_column(ForeignKey("klassendienst_typ.id", ondelete="CASCADE"))
    von: Mapped[date] = mapped_column(Date)
    bis: Mapped[date] = mapped_column(Date)
