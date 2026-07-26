from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Abteilung(Base, TimestampMixin):
    __tablename__ = "abteilung"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    long_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
