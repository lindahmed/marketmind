from contextlib import asynccontextmanager

import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import router
from app.callback_api import router as callback_router
from app.growth_api import router as growth_router
from app.jobs_api import router as jobs_router
from app.data_sources_api import router as data_sources_router
from app.auth import Db, enforce_origin
from app.config import get_settings
from app.db import engine
from app.deployment import check_database, configure_logging
from app.workflow_jobs import start_worker


@asynccontextmanager
async def lifespan(app):
    configure_logging()
    settings = get_settings()
    try:
        check_database(engine, "api", production=settings.environment == "production")
    except Exception as error:
        logging.getLogger("marketmind.deployment").error("api_startup_failed error_type=%s", type(error).__name__)
        raise RuntimeError("Database startup checks failed; run the migration job and check restricted credentials") from None
    logging.getLogger("marketmind.deployment").info("api_started environment=%s inline_worker=%s",
                                                  settings.environment, settings.workflow_worker_enabled)
    shutdown_worker = start_worker(app)
    try:
        yield
    finally:
        shutdown_worker()


def health(db: Db):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ok"}


def live():
    return {"status": "ok"}


def create_app() -> FastAPI:
    application = FastAPI(title="MarketMind AI", version="0.1.0",
                          dependencies=[Depends(enforce_origin)], lifespan=lifespan)
    application.add_middleware(CORSMiddleware, allow_origins=get_settings().allowed_origins,
                              allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE"],
                              allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"])
    for api_router in (router, growth_router, callback_router, jobs_router, data_sources_router):
        application.include_router(api_router)
    application.add_api_route("/health", health, methods=["GET"])
    application.add_api_route("/live", live, methods=["GET"])
    return application


app = create_app()
