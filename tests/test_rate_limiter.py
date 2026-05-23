import time

import pytest

from src.clients.rate_limiter import TokenBucket


def test_first_acquire_is_immediate():
    bucket = TokenBucket(rate_per_sec=2, capacity=2)
    t0 = time.monotonic()
    bucket.acquire()
    assert time.monotonic() - t0 < 0.05


def test_blocks_after_capacity_exhausted():
    bucket = TokenBucket(rate_per_sec=10, capacity=2)
    bucket.acquire()
    bucket.acquire()
    t0 = time.monotonic()
    bucket.acquire()  # third call must wait ~100ms (1 token / 10 per sec)
    elapsed = time.monotonic() - t0
    assert 0.05 < elapsed < 0.3, f"expected ~0.1s wait, got {elapsed:.3f}s"


def test_rejects_invalid_rate():
    with pytest.raises(ValueError):
        TokenBucket(rate_per_sec=0)
