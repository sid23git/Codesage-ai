"""Tests for structured logging and request-ID propagation."""

from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, configure_logging
from app.core.request_context import (
    RequestIDLogFilter,
    _request_id_ctx,
    get_request_id,
)


def _make_record(message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


class TestJsonFormatter:
    """Test suite for the structured JSON log formatter."""

    def test_produces_valid_json(self) -> None:
        record = _make_record("something happened")
        record.request_id = "abc123"
        line = JsonFormatter().format(record)
        parsed = json.loads(line)  # raises if not valid JSON
        assert parsed["message"] == "something happened"

    def test_includes_expected_fields(self) -> None:
        record = _make_record()
        record.request_id = "req-1"
        parsed = json.loads(JsonFormatter().format(record))
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "app.test"
        assert parsed["request_id"] == "req-1"
        assert "timestamp" in parsed

    def test_defaults_request_id_to_dash_when_absent(self) -> None:
        """A record never passed through RequestIDLogFilter still formats cleanly."""
        record = _make_record()
        parsed = json.loads(JsonFormatter().format(record))
        assert parsed["request_id"] == "-"

    def test_includes_exception_traceback_when_present(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _make_record("failed")
            record.exc_info = sys.exc_info()
        parsed = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in parsed["exception"]

    def test_includes_caller_supplied_extra_fields(self) -> None:
        record = _make_record()
        record.duration_ms = 42.5
        parsed = json.loads(JsonFormatter().format(record))
        assert parsed["duration_ms"] == 42.5


class TestConfigureLogging:
    """Test suite for configure_logging()'s format selection."""

    def test_json_format_installs_json_formatter(self) -> None:
        configure_logging("INFO", "json")
        handler = logging.getLogger().handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_text_format_installs_text_formatter(self) -> None:
        configure_logging("INFO", "text")
        handler = logging.getLogger().handlers[0]
        assert not isinstance(handler.formatter, JsonFormatter)

    def test_unknown_level_falls_back_to_info(self) -> None:
        configure_logging("NOT-A-LEVEL", "text")
        assert logging.getLogger().level == logging.INFO


class TestRequestIDPropagation:
    """Test suite for the request-ID ContextVar and logging filter."""

    def test_get_request_id_defaults_to_dash(self) -> None:
        token = _request_id_ctx.set("-")
        try:
            assert get_request_id() == "-"
        finally:
            _request_id_ctx.reset(token)

    def test_filter_attaches_current_request_id_to_record(self) -> None:
        token = _request_id_ctx.set("the-current-id")
        try:
            record = _make_record()
            keep = RequestIDLogFilter().filter(record)
            assert keep is True
            assert record.request_id == "the-current-id"  # type: ignore[attr-defined]
        finally:
            _request_id_ctx.reset(token)
