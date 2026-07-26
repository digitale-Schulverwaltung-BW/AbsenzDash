from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Ausnahme(Base, TimestampMixin):
    __tablename__ = "ausnahme"

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    kategorie: Mapped[str] = mapped_column(String(20))  # "fehlzeiten" | "klassenbuch"
    grund: Mapped[str] = mapped_column(String(500))
    gueltig_bis: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
