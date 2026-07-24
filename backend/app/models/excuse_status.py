from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ExcuseStatus(Base, TimestampMixin):
    __tablename__ = "excuse_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20), unique=True)
    long_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zaehlt_als_entschuldigt: Mapped[bool] = mapped_column(Boolean)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
