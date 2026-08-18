"""API v1 root router.

Register all sub-routers for v1 here.  ``main.py`` mounts this router
under the ``/api/v1`` prefix.

Adding a new feature
--------------------
1. Create ``app/api/v1/<feature>.py`` with its own ``APIRouter``.
2. Import and include it below.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health

router = APIRouter()

router.include_router(health.router)
