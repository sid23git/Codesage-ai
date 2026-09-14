"""Per-request context: request-ID propagation and one-line access logging.

`RequestContextMiddleware` is the single place that:

- reads an inbound ``X-Request-ID`` header (so a reverse proxy's or load
  balancer's own correlation ID survives end-to-end) or generates one,
- makes that ID available to every log line emitted anywhere during the
  request via a `ContextVar` + logging `Filter` (so a failing request's
  GitHub/RAG/LLM sub-call log lines can all be grepped by one ID), and
- emits exactly one summary line per request (method, path, status,
  duration) -- this is the minimum viable "did this request happen, how
  long did it take, did it succeed" signal; it is not a metrics/tracing
  system, and is not meant to become one.

Implemented as plain ASGI middleware (``__call__(scope, receive, send)``),
deliberately NOT a ``starlette.middleware.base.BaseHTTPMiddleware``
subclass. An earlier version used ``BaseHTTPMiddleware``, which wraps each
request in its own internal anyio task group; combined with a real asyncpg
connection, that produced intermittent
``RuntimeError: ... got Future ... attached to a different loop`` failures
-- a known, documented category of BaseHTTPMiddleware issue. It never
surfaced against the test suite's SQLite/aiosqlite path and was only
caught by the M8 Phase 1 Postgres verification pass
(``TEST_DATABASE_URL`` against a real Postgres exercising a full
``TestClient`` request, not just a direct service-level call). Pure ASGI
middleware has no such task-group boundary and is Starlette's own
recommended approach for anything beyond simple prototyping.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.request")

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_HEADER_BYTES = REQUEST_ID_HEADER.lower().encode("latin-1")


def get_request_id() -> str:
    """Return the current request's ID, or ``"-"`` outside a request context."""
    return _request_id_ctx.get()


class RequestIDLogFilter(logging.Filter):
    """Attach the current request's ID to every log record as ``.request_id``.

    Installed on the root logger so it applies uniformly, regardless of
    which module emits the log line.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class RequestContextMiddleware:
    """Assigns a request ID and logs one summary line per HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Websocket/lifespan events pass straight through -- this app
            # has neither today, but a middleware should never assume.
            await self.app(scope, receive, send)
            return

        inbound = next(
            (
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name == _REQUEST_ID_HEADER_BYTES
            ),
            None,
        )
        request_id = inbound or uuid.uuid4().hex[:16]
        token = _request_id_ctx.set(request_id)
        start = time.perf_counter()
        status_code = 500
        method = scope.get("method", "?")
        path = scope.get("path", "?")

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "%s %s -> unhandled error (%.1fms)", method, path, duration_ms
            )
            raise
        finally:
            _request_id_ctx.reset(token)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s -> %d (%.1fms)", method, path, status_code, duration_ms)
