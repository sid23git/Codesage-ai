"""Health-check endpoints.

GET /health — liveness only. No database interaction; intentionally
lightweight so a platform's liveness probe can call it cheaply and
frequently without ever false-failing on a transient DB blip.

GET /health/ready — readiness, including a real database round-trip. This
is deliberately NOT meant to be wired up as a platform's liveness/restart
check -- doing so would restart a perfectly healthy API process every time
the database has a momentary hiccup. It exists for humans, uptime monitors,
and dashboards that want to distinguish "the process is up" from "the
process can actually serve real requests."
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response model for the liveness health-check endpoint."""

    status: str
    service: str


class ReadinessResponse(BaseModel):
    """Response model for the readiness endpoint."""

    status: str
    service: str
    database: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service liveness check",
    description=(
        "Returns HTTP 200 and a JSON body indicating the service process is "
        "running. Performs no database interaction. Suitable for use as a "
        "liveness probe."
    ),
)
async def health_check() -> HealthResponse:
    """Return liveness status of the service."""
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.APP_NAME)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Service readiness check",
    description=(
        "Returns HTTP 200 if the service can reach its database, 503 "
        "otherwise. Intended for monitors/dashboards, not as a platform "
        "liveness/restart probe -- see this module's docstring."
    ),
)
async def readiness_check(response: Response) -> ReadinessResponse:
    """Return readiness status, including a live database round-trip."""
    settings = get_settings()
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Readiness check failed: database unreachable: %s", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="degraded", service=settings.APP_NAME, database="unreachable"
        )

    return ReadinessResponse(status="ok", service=settings.APP_NAME, database="ok")
