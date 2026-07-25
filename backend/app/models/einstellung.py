from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Einstellung(Base, TimestampMixin):
    __tablename__ = "einstellung"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_interval_cron: Mapped[str] = mapped_column(String(50), default="*/30 * * * *")
    schuljahr_start_cache: Mapped[date | None] = mapped_column(Date, nullable=True)
    initialer_import_abgeschlossen: Mapped[bool] = mapped_column(Boolean, default=False)
    asv_csv_zuletzt_importiert_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    letzter_sync_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
