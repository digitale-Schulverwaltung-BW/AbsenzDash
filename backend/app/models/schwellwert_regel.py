from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchwellwertRegel(Base, TimestampMixin):
    __tablename__ = "schwellwert_regel"
    __table_args__ = (
        Index(
            "uq_schwellwert_regel_abteilung",
            "typ",
            "abteilung_id",
            unique=True,
            postgresql_where=text("abteilung_id IS NOT NULL"),
        ),
        Index(
            "uq_schwellwert_regel_klasse",
            "typ",
            "klasse_id",
            unique=True,
            postgresql_where=text("klasse_id IS NOT NULL"),
        ),
        Index(
            "uq_schwellwert_regel_schulweit",
            "typ",
            unique=True,
            postgresql_where=text("geltungsbereich = 'schulweit'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    typ: Mapped[str] = mapped_column(String(20))  # "fehlzeiten" | "klassenbuch"
    geltungsbereich: Mapped[str] = mapped_column(String(20))  # "schulweit" | "abteilung" | "klasse"
    abteilung_id: Mapped[int | None] = mapped_column(ForeignKey("abteilung.id"), nullable=True)
    klasse_id: Mapped[int | None] = mapped_column(ForeignKey("klasse.id"), nullable=True)
