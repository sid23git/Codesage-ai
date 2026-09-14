"""Shared per-IP rate limiter for auth and AI/ingestion endpoints.

Uses slowapi's in-memory (no Redis) storage — a deliberate scope decision
for a single/few-worker deployment: it stops one client from hammering a
given worker process, which is the actual near-term risk (credential
stuffing against /auth/login, or running up LLM/embedding API cost against
/ask, /explain, /review, /ingest). It is NOT a globally-consistent limit
across multiple worker processes or hosts — each process keeps its own
counters. A Redis-backed store would fix that, at the cost of a new piece
of infrastructure this project's actual scale doesn't yet justify (see the
M8 architecture review).

``limiter.enabled`` is driven by ``Settings.RATE_LIMIT_ENABLED`` so the test
suite (which reuses the same TestClient host across hundreds of requests
within one process) can run with limiting off by default, while a small,
dedicated test module exercises it with limiting explicitly turned on.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=get_settings().RATE_LIMIT_ENABLED,
)
