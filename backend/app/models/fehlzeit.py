from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Fehlzeit(Base, TimestampMixin):
    __tablename__ = "fehlzeit"
    __table_args__ = (
        UniqueConstraint(
            "schueler_id", "datum", "start_zeit", "end_zeit", "typ", name="uq_fehlzeit_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    typ: Mapped[str] = mapped_column(String(10))  # "tag" | "stunde"
    datum: Mapped[date] = mapped_column(Date)
    start_zeit: Mapped[int] = mapped_column(Integer)
    end_zeit: Mapped[int] = mapped_column(Integer)
    fach: Mapped[str | None] = mapped_column(String(50), nullable=True)
    excuse_status_id: Mapped[int | None] = mapped_column(ForeignKey("excuse_status.id"), nullable=True)
    grund_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invalid: Mapped[bool] = mapped_column(Boolean, default=False)
