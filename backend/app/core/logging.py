"""Logging configuration for the CodeSage API service.

Call ``configure_logging()`` once at application startup. The log level is
driven by ``settings.LOG_LEVEL``; the output format by ``settings.LOG_FORMAT``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import RequestIDLogFilter

_TEXT_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | [%(request_id)s] | %(message)s"
)
_TEXT_DATEFMT = "%Y-%m-%dT%H:%M:%S"

# Attributes already covered explicitly below, or internal to LogRecord --
# excluded from the JSON formatter's catch-all "extra fields" pass.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """Renders one JSON object per log line.

    Structured logs are what let a hosting platform's log search actually
    filter by field (level, logger, request_id) instead of grepping free
    text -- the payoff only shows up once logs leave a local terminal for
    a real log-aggregation view, which is exactly the point of adding this
    for M8 rather than earlier.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Any caller-supplied `extra={...}` fields ride along too.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key not in payload:
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO", log_format: str = "text") -> None:
    """Set up the root logger.

    Parameters
    ----------
    log_level:
        One of DEBUG, INFO, WARNING, ERROR, CRITICAL. Defaults to INFO.
    log_format:
        ``"text"`` (human-readable, for local development) or ``"json"``
        (one structured object per line, for any real deployment).
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(stream=sys.stdout)
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT, datefmt=_TEXT_DATEFMT))
    handler.addFilter(RequestIDLogFilter())

    root = logging.getLogger()
    root.handlers.clear()  # override any existing root-logger handlers
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Quieten noisy third-party loggers. uvicorn.access is silenced
    # entirely -- RequestContextMiddleware's own one-line-per-request log
    # (with a request ID and duration uvicorn's own access log lacks)
    # replaces it rather than duplicating it.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logging.getLogger(__name__).debug(
        "Logging initialised at level=%s format=%s", log_level, log_format
    )
