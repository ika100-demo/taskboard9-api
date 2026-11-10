"""FastAPI entry point for taskboard9-api."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .db import Database, DatabaseUnavailable
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks.routes import router as tasks_router
from .tasks.store import PostgresTaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
log = structlog.get_logger()
if tracing_enabled():
    configure_tracing()

core_router = APIRouter()


class HealthResponse(BaseModel):
    status: str


@core_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


@core_router.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    """Readiness probe — returns 200 when the service is ready to accept traffic."""
    return HealthResponse(status="ready")


@core_router.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "taskboard9-api"}


@core_router.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    log.warning(
        "database_unavailable",
        error=type(exc.__cause__ or exc).__name__,
        path=request.url.path,
    )
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


def create_app() -> FastAPI:
    """Build an app with its own database pool and Postgres task store."""
    db = Database.from_env()
    store = PostgresTaskStore(db)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        threading.Thread(target=store.warm_up, daemon=True, name="db-warmup").start()
        try:
            yield
        finally:
            db.close()

    application = FastAPI(title="taskboard9-api", version=__version__, lifespan=lifespan)
    application.add_middleware(MetricsMiddleware)
    application.state.db = db
    application.state.task_store = store
    application.add_exception_handler(DatabaseUnavailable, _database_unavailable)
    application.include_router(core_router)
    application.include_router(tasks_router)
    return application


app = create_app()
