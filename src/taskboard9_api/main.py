"""FastAPI entry point for taskboard9-api."""

from __future__ import annotations

import os

from fastapi import APIRouter, FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks.routes import router as tasks_router
from .tasks.store import InMemoryTaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
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


def create_app() -> FastAPI:
    """Build an app with its own empty task store."""
    application = FastAPI(title="taskboard9-api", version=__version__)
    application.add_middleware(MetricsMiddleware)
    application.state.task_store = InMemoryTaskStore()
    application.include_router(core_router)
    application.include_router(tasks_router)
    return application


app = create_app()
