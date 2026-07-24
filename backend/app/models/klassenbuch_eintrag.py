from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KlassenbuchEintrag(Base, TimestampMixin):
    __tablename__ = "klassenbuch_eintrag"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    kategorie_id: Mapped[int] = mapped_column(ForeignKey("classreg_category.id"))
    datum: Mapped[date] = mapped_column(Date)
    text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    lesson_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erstellt_von_teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geaendert_von_teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
