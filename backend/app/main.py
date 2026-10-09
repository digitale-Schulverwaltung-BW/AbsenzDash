import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.students import router as students_router
from app.api.routes.admin import router as admin_router
from app.api.routes.dashboard import router as dashboard_router
from app.core.config import settings
from app.core.database import engine
from app.core.migration_check import warn_if_migrations_pending
from app.services import sync_lauf_service
from app.services import sync_orchestrator
from app.core.scheduler import create_scheduler, start_scheduler
from app.core import scheduler as scheduler_module


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    await warn_if_migrations_pending(engine)

    try:
        abgebrochen = await sync_lauf_service.verwaiste_laeufe_abbrechen()
        if abgebrochen:
            logging.getLogger(__name__).warning(
                "%d beim letzten Beenden noch laufende Sync-Laeufe wurden als abgebrochen markiert", abgebrochen
            )
    except Exception:  # noqa: BLE001 - z.B. Migration steht noch aus; darf den Start nicht verhindern
        logging.getLogger(__name__).warning(
            "Verwaiste Sync-Laeufe konnten nicht aufgeraeumt werden", exc_info=True
        )

    scheduler = create_scheduler()
    await start_scheduler(scheduler)
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        # Reihenfolge wichtig: shutdown() muss zuerst laufen, damit APScheduler
        # keine neuen Job-Laeufe mehr anstoesst, bevor wir die noch laufenden
        # Sync-Tasks einsammeln.
        scheduler.shutdown(wait=False)
        pending = list(scheduler_module._background_sync_tasks) + list(sync_orchestrator._manuelle_sync_tasks)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(
    title="AbsenzDash Backend",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.include_router(students_router)
app.include_router(admin_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
