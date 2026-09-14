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
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request")

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_ID_HEADER = "X-Request-ID"


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


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID and logs one summary line per request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        token = _request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "%s %s -> unhandled error (%.1fms)",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        finally:
            _request_id_ctx.reset(token)

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
