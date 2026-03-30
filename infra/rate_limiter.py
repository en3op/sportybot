"""
Token bucket + sliding window rate limiter.

Token Bucket: refills tokens at a steady rate. Good for smoothing bursts.
Sliding Window: counts requests in a rolling time window. Good for hard caps.
"""

import time
import asyncio
from collections import deque


class TokenBucket:
    """Smooths request bursts by refilling tokens at a constant rate.

    Usage:
        bucket = TokenBucket(capacity=10, refill_rate=2)  # 10 tokens, +2/sec
        await bucket.wait()   # blocks until a token is available
    """

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns False if not enough available."""
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def wait(self, tokens: int = 1):
        """Block until enough tokens are available."""
        while not await self.acquire(tokens):
            deficit = tokens - self.tokens
            wait_time = deficit / self.refill_rate
            await asyncio.sleep(max(0.1, wait_time))

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self._last_refill = now

    @property
    def available(self) -> int:
        self._refill()
        return int(self.tokens)


class SlidingWindowCounter:
    """Hard cap on requests within a rolling time window.

    Usage:
        counter = SlidingWindowCounter(window_seconds=60, max_requests=100)
        if counter.can_proceed():
            counter.record()
            # make request
    """

    def __init__(self, window_seconds: int, max_requests: int):
        self.window = window_seconds
        self.max_requests = max_requests
        self._timestamps: deque[float] = deque()

    def can_proceed(self) -> bool:
        self._prune()
        return len(self._timestamps) < self.max_requests

    def record(self):
        self._timestamps.append(time.time())

    def remaining(self) -> int:
        self._prune()
        return self.max_requests - len(self._timestamps)

    def _prune(self):
        cutoff = time.time() - self.window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
