from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NutzerKlasse(Base, TimestampMixin):
    __tablename__ = "nutzer_klasse"
    __table_args__ = (
        UniqueConstraint("nutzer_id", "klasse_id", "quelle", name="uq_nutzer_klasse_quelle"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nutzer_id: Mapped[int] = mapped_column(ForeignKey("nutzer.id", ondelete="CASCADE"))
    klasse_id: Mapped[int] = mapped_column(ForeignKey("klasse.id", ondelete="CASCADE"))
    quelle: Mapped[str] = mapped_column(String(20))  # "webuntis_seed" | "manuell"
