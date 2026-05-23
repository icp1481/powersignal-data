"""Simple token-bucket rate limiter for outbound API calls.

Sized for data.go.kr dev quota (~100 calls/day). The point is not to throttle
under that quota, but to avoid bursting when backfilling or running multiple
collectors in parallel.
"""
from __future__ import annotations

import threading
import time


class TokenBucket:
    """Thread-safe token bucket. `acquire()` blocks until a token is available."""

    def __init__(self, rate_per_sec: float, capacity: int | None = None) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity if capacity is not None else max(1, int(rate_per_sec)))
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / self.rate
            time.sleep(wait)
