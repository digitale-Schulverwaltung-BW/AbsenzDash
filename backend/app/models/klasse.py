from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Klasse(Base, TimestampMixin):
    __tablename__ = "klasse"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    stufe: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schulart: Mapped[str | None] = mapped_column(String(50), nullable=True)
    webuntis_teacher1_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    webuntis_teacher2_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
