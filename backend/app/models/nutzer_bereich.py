from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Table

from app.models.base import Base

nutzer_bereich = Table(
    "nutzer_bereich",
    Base.metadata,
    Column("nutzer_id", ForeignKey("nutzer.id", ondelete="CASCADE"), primary_key=True),
    Column("bereich_id", ForeignKey("bereich.id", ondelete="CASCADE"), primary_key=True),
)
