"""Health-check endpoint.

GET /health — returns the service liveness status.
No database interaction is performed; this endpoint is intentionally
lightweight so load-balancers and orchestrators can probe it cheaply.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response model for the health-check endpoint."""

    status: str
    service: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description=(
        "Returns HTTP 200 and a JSON body indicating the service is running. "
        "Suitable for use as a liveness probe."
    ),
)
async def health_check() -> HealthResponse:
    """Return liveness status of the service."""
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.APP_NAME)
