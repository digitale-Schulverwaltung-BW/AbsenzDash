from __future__ import annotations

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

bereich_klasse = Table(
    "bereich_klasse",
    Base.metadata,
    Column("bereich_id", ForeignKey("bereich.id", ondelete="CASCADE"), primary_key=True),
    Column("klasse_id", ForeignKey("klasse.id", ondelete="CASCADE"), primary_key=True),
)


class Bereich(Base, TimestampMixin):
    __tablename__ = "bereich"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
