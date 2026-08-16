"""Structured logging and request correlation.

v2 logged free-form text with no way to tie a failed generation back to the
request that caused it. Every line now carries a request id, and in production
they are emitted as JSON so a log platform can index them.

The id is stored in a ContextVar, so it follows the request across await
points without being threaded through every function signature.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

request_id: ContextVar[str] = ContextVar("request_id", default="-")

_BUILTIN = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # Anything passed via `extra=` rides along as a first-class field.
        payload.update(
            {k: v for k, v in record.__dict__.items()
             if k not in _BUILTIN and k != "request_id"}
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Readable local format - JSON is noise at a dev terminal."""

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_logs else TextFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True

    logging.getLogger("httpx").setLevel(logging.WARNING)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, log the outcome, and echo the id to the client."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._log = logging.getLogger("harmonybot.access")

    async def dispatch(self, request, call_next):
        # Honour an upstream id so traces survive a proxy hop.
        incoming = request.headers.get("x-request-id")
        rid = incoming or uuid.uuid4().hex[:12]
        token = request_id.set(rid)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            self._log.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            raise
        finally:
            request_id.reset(token)

        duration = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = rid

        # Static assets would drown out everything useful.
        if not request.url.path.startswith("/static"):
            self._log.info(
                "%s %s -> %d",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration,
                },
            )
        return response
