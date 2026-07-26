from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchuelerZaehlerstand(Base, TimestampMixin):
    __tablename__ = "schueler_zaehlerstand"
    __table_args__ = (UniqueConstraint("schueler_id", "typ", name="uq_schueler_zaehlerstand_schueler_typ"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    typ: Mapped[str] = mapped_column(String(20))  # "fehlzeiten" | "klassenbuch"
    regel_id: Mapped[int] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="CASCADE"))
    aktueller_stand: Mapped[int] = mapped_column(Integer, default=0)
    erreichte_stufe_nr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    letzter_reset_am: Mapped[date | None] = mapped_column(Date, nullable=True)
