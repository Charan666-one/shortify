"""Structured logging.

Production logs are JSON so a log aggregator can filter on fields rather than
regex a message, and every line carries the request id that produced it — the
difference between "an error happened" and "this user's request failed here".
Development keeps the readable one-line format.
"""

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar

# Set per request by RequestIdMiddleware; read by the formatter.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Anything passed as logger.info(..., extra={...}) becomes a field.
        for key, value in record.__dict__.items():
            if key not in RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id_var.get()
        return super().format(record)


def configure_logging(environment: str) -> None:
    """Install the formatter for this environment on the root logger."""
    fmt = os.getenv("LOG_FORMAT", "text" if environment == "development" else "json")

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter(
            "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
        ))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    # uvicorn installs its own handlers; let them fall through to ours so the
    # whole process logs in one format.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
