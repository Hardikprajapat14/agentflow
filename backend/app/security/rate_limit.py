"""Small in-memory sliding-window limiter for auth endpoints (per client IP)."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    def dep(request: Request) -> None:
        key = f"{request.url.path}:{request.client.host if request.client else 'unknown'}"
        now = time.monotonic()
        q = _hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= max_requests:
            raise HTTPException(429, "Too many attempts. Please wait a minute and try again.")
        q.append(now)

    return dep
