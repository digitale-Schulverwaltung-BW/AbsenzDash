from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

massnahmen_typ_regel = Table(
    "massnahmen_typ_regel",
    Base.metadata,
    Column("massnahmen_typ_id", ForeignKey("massnahmen_typ.id", ondelete="CASCADE"), primary_key=True),
    Column("regel_id", ForeignKey("schwellwert_regel.id", ondelete="CASCADE"), primary_key=True),
)


class MassnahmenTyp(Base, TimestampMixin):
    __tablename__ = "massnahmen_typ"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    setzt_zaehler_zurueck: Mapped[bool] = mapped_column(Boolean, default=False)
