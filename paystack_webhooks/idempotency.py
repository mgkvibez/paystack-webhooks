"""Deduplication, because both providers retry on any non-2xx.

The store is deliberately tiny and in-memory: it is correct for one process and
honest about it. A multi-instance deployment needs a shared store (Redis, a table
with a unique key), which is why the protocol exists rather than a hard-coded dict.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Protocol


class Store(Protocol):
    """Anything that can answer 'have I seen this key before?' atomically."""

    def seen(self, key: str) -> bool:
        """Record the key and return True if it was already present."""
        ...


class MemoryStore:
    """Thread-safe, TTL-bounded, capped. Single process only.

    ``seen`` both checks and records in one locked operation, so two concurrent
    deliveries of the same event cannot both be told it is new. A check-then-record
    API would race, and that race is a double charge.
    """

    def __init__(self, ttl_seconds: int = 86400, max_entries: int = 10_000,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: Dict[str, float] = {}

    def seen(self, key: str) -> bool:
        if not key:
            raise ValueError("an idempotency key is required")
        now = self._clock()
        with self._lock:
            self._evict(now)
            if key in self._seen:
                return True
            self._seen[key] = now
            return False

    def __len__(self) -> int:
        with self._lock:
            self._evict(self._clock())
            return len(self._seen)

    def _evict(self, now: float) -> None:
        expired = [k for k, at in self._seen.items() if now - at > self._ttl]
        for key in expired:
            del self._seen[key]
        if len(self._seen) > self._max:
            overflow = len(self._seen) - self._max
            for key in sorted(self._seen, key=lambda k: self._seen[k])[:overflow]:
                del self._seen[key]
