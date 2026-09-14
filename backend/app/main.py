"""FastAPI application factory.

This module is intentionally thin — it wires together the application
components but contains no business logic.

Start the server
----------------
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import limiter
from app.core.request_context import RequestContextMiddleware

logger = logging.getLogger(__name__)


async def _rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Render a rate-limit rejection in the same `{"detail": ...}` shape
    every other error response in this API already uses, rather than
    slowapi's own default `{"error": ...}` shape -- so the frontend's
    existing typed-error handling (which reads `.detail`) picks this up
    for free, with no special-casing needed on that side."""
    return JSONResponse(
        {"detail": f"Rate limit exceeded ({exc.detail}). Please try again shortly."},
        status_code=429,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Runs startup logic before the application begins serving requests,
    and teardown logic when it shuts down.
    """
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL.value, settings.LOG_FORMAT)

    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.APP_ENV.value)

    # Validate database connectivity at startup so problems surface
    # immediately rather than on the first request.
    try:
        from sqlalchemy import text

        from app.db.session import get_engine

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connectivity verified.")

        # Recover any ingestion left mid-run by a prior process's restart
        # (deploy, OOM, platform reschedule) -- see
        # IngestionService.sweep_stale_ingestions's docstring. Only
        # attempted once connectivity is confirmed; a failure here is
        # logged the same non-fatal way as the connectivity check itself.
        from app.db.session import session_scope
        from app.services.ingestion_service import IngestionService

        async with session_scope() as db:
            await IngestionService.sweep_stale_ingestions(db)
    except Exception as exc:
        # Log clearly but do not crash — the health endpoint must still
        # respond so operators can diagnose the issue.
        logger.warning(
            "Database connectivity check failed at startup: %s.  "
            "The service will start but database-backed endpoints will fail.",
            exc,
        )

    yield  # ← application runs here

    logger.info("Shutting down %s.", settings.APP_NAME)
    from app.db.session import dispose_engine

    await dispose_engine()


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "CodeSage AI — an AI-powered software engineering assistant "
            "that understands, documents, reviews, and improves GitHub repositories."
        ),
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Rate limiting (app.core.rate_limit) -- per-IP limits on auth and
    # AI/ingestion endpoints, applied via @limiter.limit(...) decorators
    # on the individual routes themselves.
    # ------------------------------------------------------------------
    app.state.limiter = limiter
    # Starlette's own stubs type add_exception_handler's second argument
    # against the base `Exception`, not a specific subclass -- registering
    # a handler for one specific exception type (the standard pattern,
    # including in slowapi's own docs/source) is always a mypy mismatch
    # here, not a real type error.
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added after CORSMiddleware so it becomes the outermost layer (each
    # add_middleware() call wraps the ones already registered) -- it should
    # see and log every request, CORS preflights included, with the total
    # time actually spent handling the request.
    app.add_middleware(RequestContextMiddleware)

    # Mount routers at both root and /api/v1 prefix for flexibility.
    app.include_router(v1_router)
    app.include_router(v1_router, prefix="/api/v1")

    return app


app: FastAPI = create_app()
