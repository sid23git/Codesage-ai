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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Runs startup logic before the application begins serving requests,
    and teardown logic when it shuts down.
    """
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL.value)

    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.APP_ENV.value)

    # Validate database connectivity at startup so problems surface
    # immediately rather than on the first request.
    try:
        from sqlalchemy import text

        from app.db.session import get_engine

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connectivity verified.")
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
    # Middleware
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routers at both root and /api/v1 prefix for flexibility.
    app.include_router(v1_router)
    app.include_router(v1_router, prefix="/api/v1")

    return app


app: FastAPI = create_app()
