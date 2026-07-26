from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchuelerZaehlerstand(Base, TimestampMixin):
    __tablename__ = "schueler_zaehlerstand"
    __table_args__ = (UniqueConstraint("schueler_id", "regel_id", name="uq_schueler_zaehlerstand_paar"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    regel_id: Mapped[int] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="CASCADE"))
    aktueller_stand: Mapped[int] = mapped_column(Integer, default=0)
    erreichte_stufe_nr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    letzter_reset_am: Mapped[date | None] = mapped_column(Date, nullable=True)
