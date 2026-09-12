"""API v1 root router.

Registers all sub-routers for API version 1 (health, auth, repositories,
assistant).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import assistant, auth, health, repositories

router = APIRouter()

router.include_router(health.router)
router.include_router(auth.router)
router.include_router(repositories.router)
router.include_router(assistant.router)
