from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchwellwertStufe(Base, TimestampMixin):
    __tablename__ = "schwellwert_stufe"
    __table_args__ = (UniqueConstraint("regel_id", "stufe_nr", name="uq_schwellwert_stufe_regel_stufe_nr"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    regel_id: Mapped[int] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="CASCADE"))
    stufe_nr: Mapped[int] = mapped_column(Integer)
    einheit: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "fehltage" | "fehlstunden"
    schwellenwert: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    fehlzeiten_filter: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "nur_unentschuldigt" | "alle"
    empfaenger_rollen: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
