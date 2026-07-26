import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.scheduler import create_scheduler, start_scheduler
from app.core import scheduler as scheduler_module


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    scheduler = create_scheduler()
    await start_scheduler(scheduler)
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown(wait=False)
    pending = list(scheduler_module._background_sync_tasks)
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="AbsenzDash Backend", lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
