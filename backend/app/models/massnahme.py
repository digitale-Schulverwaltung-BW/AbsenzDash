from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Massnahme(Base, TimestampMixin):
    __tablename__ = "massnahme"

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    massnahmen_typ_id: Mapped[int] = mapped_column(ForeignKey("massnahmen_typ.id"))
    datum: Mapped[date] = mapped_column(Date)
    notiz: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    erfasst_von_nutzer_id: Mapped[int] = mapped_column(ForeignKey("nutzer.id"))
