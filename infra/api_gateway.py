"""
API Gateway with circuit breaker, key rotation, and fallback.

Wraps all external API calls with:
  - Rate limiting (token bucket)
  - Circuit breaking (stop calling failing services)
  - API key rotation (spread load across keys)
  - Cache-first reads
  - Exponential backoff retries
  - Fallback to cached/stale data on failure
"""

import time
import random
import asyncio
import logging
from enum import Enum
from typing import Any, Callable

from infra.rate_limiter import TokenBucket, SlidingWindowCounter

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"        # Normal — requests flow through
    OPEN = "open"            # Failing — reject immediately
    HALF_OPEN = "half_open"  # Testing — allow one probe request


class CircuitBreaker:
    """Stops calling a service after repeated failures.

    After `failure_threshold` failures, opens the circuit.
    After `recovery_timeout` seconds, allows one probe request.
    If it succeeds, closes the circuit. If it fails, re-opens.
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self._last_failure_time = 0.0

    def record_failure(self):
        self.failure_count += 1
        self._last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit OPENED after {self.failure_count} failures")

    def record_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def can_proceed(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit HALF_OPEN — sending probe request")
                return True
            return False
        # HALF_OPEN: allow one request
        return True


class APIKeyPool:
    """Rotate through multiple API keys to spread rate-limit pressure.

    Picks the key with the most remaining quota in the current window.
    """

    def __init__(self, keys: list[str], window_seconds: int = 60,
                 max_requests_per_key: int = 100):
        self.keys = keys
        self._counters: dict[str, SlidingWindowCounter] = {
            key: SlidingWindowCounter(window_seconds, max_requests_per_key)
            for key in keys
        }

    def get_key(self) -> str | None:
        """Return the key with the most remaining quota, or None if all exhausted."""
        available = [
            (key, counter.remaining())
            for key, counter in self._counters.items()
            if counter.can_proceed()
        ]
        if not available:
            return None
        available.sort(key=lambda x: x[1], reverse=True)
        return available[0][0]

    def record_use(self, key: str):
        if key in self._counters:
            self._counters[key].record()


class APIGateway:
    """Unified gateway for all external API calls.

    Call order:
      1. Return from cache if fresh
      2. Check circuit breaker
      3. Acquire rate-limit token
      4. Pick API key
      5. Execute with retry + exponential backoff
      6. Cache result
      7. On failure, return fallback
    """

    def __init__(self, cache_manager=None, fallback_store=None):
        self.cache = cache_manager
        self.fallback = fallback_store
        self._providers: dict[str, dict] = {}

    def register_provider(self, name: str, *,
                          rate_limit: int = 10,
                          per_seconds: int = 60,
                          api_keys: list[str] | None = None,
                          failure_threshold: int = 3,
                          recovery_timeout: float = 30.0):
        """Register an external API provider with its limits."""
        self._providers[name] = {
            "limiter": TokenBucket(capacity=rate_limit,
                                   refill_rate=rate_limit / per_seconds),
            "breaker": CircuitBreaker(failure_threshold, recovery_timeout),
            "key_pool": APIKeyPool(api_keys) if api_keys else None,
        }

    async def call(self, provider: str, cache_key: str,
                   fetch_fn: Callable, *args,
                   cache_category: str = "default",
                   **kwargs) -> Any:
        """Make a protected API call.

        Args:
            provider: Name of the provider (must be registered).
            cache_key: Unique key for caching.
            fetch_fn: Async or sync function to call on cache miss.
            cache_category: TTL category for cache.
            *args, **kwargs: Passed to fetch_fn.
        """
        # 1. Cache check
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        # 2. Provider config
        prov = self._providers.get(provider)
        if prov is None:
            # No protection configured — call directly
            return await self._exec(fetch_fn, args, kwargs)

        # 3. Circuit breaker
        breaker = prov["breaker"]
        if not breaker.can_proceed():
            logger.warning(f"{provider}: circuit open, using fallback")
            if self.fallback:
                return self.fallback.get(cache_key)
            return None

        # 4. Rate limit
        await prov["limiter"].wait()

        # 5. API key rotation
        key_pool = prov["key_pool"]
        api_key = key_pool.get_key() if key_pool else None
        if key_pool and api_key is None:
            logger.warning(f"{provider}: all API keys exhausted")
            if self.fallback:
                return self.fallback.get(cache_key)
            return None

        # 6. Execute with retry
        result = await self._execute_with_retry(
            fetch_fn, args, kwargs, api_key, breaker
        )

        if result is not None:
            # 7. Cache + record
            if self.cache:
                self.cache.set(cache_key, result, cache_category)
            if key_pool and api_key:
                key_pool.record_use(api_key)
            return result

        # 8. Fallback
        if self.fallback:
            return self.fallback.get(cache_key)
        return None

    async def _execute_with_retry(self, fn, args, kwargs,
                                   api_key, breaker,
                                   max_retries: int = 3) -> Any:
        """Execute with exponential backoff + jitter."""
        for attempt in range(max_retries):
            try:
                if api_key:
                    kwargs["api_key"] = api_key
                result = await self._exec(fn, args, kwargs)
                breaker.record_success()
                return result
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    breaker.record_failure()
                # Exponential backoff: 1s, 2s, 4s + random jitter
                delay = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
        return None

    @staticmethod
    async def _exec(fn, args, kwargs) -> Any:
        """Call fn — works for both sync and async functions."""
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
