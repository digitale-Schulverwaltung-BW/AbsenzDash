from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ClassregCategory(Base, TimestampMixin):
    __tablename__ = "classreg_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    long_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
