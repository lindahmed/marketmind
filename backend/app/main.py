from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import router
from app.callback_api import router as callback_router
from app.growth_api import router as growth_router
from app.jobs_api import router as jobs_router
from app.data_sources_api import router as data_sources_router
from app.auth import Db, enforce_origin
from app.config import get_settings
from app.workflow_jobs import start_worker


@asynccontextmanager
async def lifespan(app):
    shutdown_worker = start_worker(app)
    try:
        yield
    finally:
        shutdown_worker()


app = FastAPI(title="MarketMind AI", version="0.1.0", dependencies=[Depends(enforce_origin)], lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().allowed_origins,
                   allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"])
app.include_router(router)
app.include_router(growth_router)
app.include_router(callback_router)
app.include_router(jobs_router)
app.include_router(data_sources_router)


@app.get("/health")
def health(db: Db):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
