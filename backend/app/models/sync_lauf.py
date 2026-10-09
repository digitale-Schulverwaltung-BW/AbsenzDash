from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SYNC_LAUF_STATUS = ("laufend", "ok", "fehler", "abgebrochen")
SYNC_AUSGELOEST_VON = ("zeitplan", "manuell")


class SyncLauf(Base):
    """Verlauf der Sync-Laeufe (zeitgesteuert und manuell). Die Zeile wird in einer eigenen
    Session geschrieben, damit Fortschritt und Fehler auch bei einem Rollback des Sync-Laufs
    sichtbar bleiben. fehler_kurz enthaelt nur Fehlerklasse + bereinigte, gekuerzte Meldung."""

    __tablename__ = "sync_lauf"

    id: Mapped[int] = mapped_column(primary_key=True)
    gestartet_am: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    beendet_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    ausgeloest_von: Mapped[str] = mapped_column(String(20))
    nutzer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("nutzer.id", ondelete="SET NULL"), nullable=True
    )
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fehler_kurz: Mapped[str | None] = mapped_column(String(300), nullable=True)
