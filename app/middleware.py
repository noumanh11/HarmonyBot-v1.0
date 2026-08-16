"""Security headers and rate limiting.

Both were absent in v2: any visitor could drain the Hugging Face quota, and the
page shipped without a CSP even though it renders model-generated HTML.
"""

from __future__ import annotations

import logging
import time
from collections import deque

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Everything the page needs is same-origin and self-contained, so the policy
# can stay strict. 'unsafe-inline' covers the pre-paint theme script in
# index.html; give that a nonce if you tighten this further.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for key, value in _HEADERS.items():
            response.headers.setdefault(key, value)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limit on the generation endpoints.

    In-process, so it protects a single worker; put a shared limiter at the
    edge (or back this with Redis) before running multiple replicas.
    """

    PROTECTED = ("/chat", "/chat/stream")

    def __init__(self, app, limit: int, window: float) -> None:
        super().__init__(app)
        self._limit = limit
        self._window = window
        self._hits: dict[str, deque[float]] = {}

    def _client_key(self, request) -> str:
        # X-Forwarded-For is only trustworthy behind a proxy that sets it;
        # uvicorn is started with --proxy-headers in the container.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request, call_next):
        if request.url.path not in self.PROTECTED:
            return await call_next(request)

        key = self._client_key(request)
        now = time.monotonic()
        window = self._hits.setdefault(key, deque())

        while window and window[0] <= now - self._window:
            window.popleft()

        if len(window) >= self._limit:
            retry_after = int(self._window - (now - window[0])) + 1
            logger.warning("rate limit hit", extra={"client": key})
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)

        # Opportunistic cleanup so idle clients do not accumulate forever.
        if len(self._hits) > 4096:
            for stale in [k for k, v in self._hits.items() if not v]:
                del self._hits[stale]

        return await call_next(request)
