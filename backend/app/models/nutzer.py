from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

ROLLEN = ("klassenlehrkraft", "bereichsleiter", "schulleitung")


class Nutzer(Base, TimestampMixin):
    __tablename__ = "nutzer"

    id: Mapped[int] = mapped_column(primary_key=True)
    wp_user_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    rolle: Mapped[str] = mapped_column(String(20))
    webuntis_teacher_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
