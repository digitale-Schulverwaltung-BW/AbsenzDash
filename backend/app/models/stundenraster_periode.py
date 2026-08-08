from __future__ import annotations

from sqlalchemy import Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class StundenrasterPeriode(Base, TimestampMixin):
    __tablename__ = "stundenraster_periode"
    __table_args__ = (
        UniqueConstraint("wochentag", "stunde_nr", name="uq_stundenraster_periode_wochentag_stunde_nr"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    wochentag: Mapped[int] = mapped_column(Integer)  # ISO-Wochentag: 1=Montag ... 7=Sonntag
    stunde_nr: Mapped[int] = mapped_column(Integer)
    start_zeit: Mapped[int] = mapped_column(Integer)  # HHMM, z.B. 730 fuer 7:30
    end_zeit: Mapped[int] = mapped_column(Integer)
