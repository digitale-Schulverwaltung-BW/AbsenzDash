from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Benachrichtigung(Base, TimestampMixin):
    __tablename__ = "benachrichtigung"

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    regel_id: Mapped[int | None] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="SET NULL"), nullable=True)
    stufe_nr: Mapped[int] = mapped_column(Integer)
    gesendet_am: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    empfaenger: Mapped[list[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))  # "gesendet" | "kein_empfaenger" | "initial_import"
