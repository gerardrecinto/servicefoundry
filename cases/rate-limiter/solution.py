"""Reference implementation for the Rate Limiter design in README.md.

Implements the token bucket LimitAlgorithm chosen in Tradeoffs, with a
pluggable interface so a sliding-window or fixed-window variant could be
swapped in without touching CounterStore or the public check() surface.
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Tier:
    name: str
    limit: int
    window_seconds: float


class TierResolver:
    """Maps a client to its Tier. Backed by a dict here; in production this
    is a cached read-through to the identity/billing system of record."""

    def __init__(self, assignments: dict[str, Tier], default: Tier):
        self._assignments = dict(assignments)
        self._default = default

    def resolve(self, client_id: str) -> Tier:
        return self._assignments.get(client_id, self._default)

    def set_tier(self, client_id: str, tier: Tier) -> None:
        self._assignments[client_id] = tier


class LimitAlgorithm:
    def check(self, client_id: str, tier: Tier, now: float) -> tuple[bool, float]:
        raise NotImplementedError


class TokenBucketAlgorithm(LimitAlgorithm):
    """Chosen over fixed-window in Tradeoffs: smooths bursts at a window
    boundary instead of allowing up to 2x the limit across two windows."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # client -> (tokens, last_refill)

    def check(self, client_id: str, tier: Tier, now: float) -> tuple[bool, float]:
        refill_rate = tier.limit / tier.window_seconds
        with self._lock:
            tokens, last_refill = self._buckets.get(client_id, (float(tier.limit), now))
            tokens = min(tier.limit, tokens + (now - last_refill) * refill_rate)
            if tokens >= 1:
                self._buckets[client_id] = (tokens - 1, now)
                return True, 0.0
            self._buckets[client_id] = (tokens, now)
            missing = 1 - tokens
            retry_after = missing / refill_rate
            return False, retry_after


class RateLimiter:
    """The check() operation from API Design. Synchronous, in the request
    path of every protected API."""

    def __init__(self, tier_resolver: TierResolver, algorithm: Optional[LimitAlgorithm] = None):
        self._tiers = tier_resolver
        self._algorithm = algorithm or TokenBucketAlgorithm()

    def check(self, client_id: str, now: Optional[float] = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now
        tier = self._tiers.resolve(client_id)
        return self._algorithm.check(client_id, tier, now)


if __name__ == "__main__":
    free = Tier("free", limit=3, window_seconds=1.0)
    paid = Tier("paid", limit=10, window_seconds=1.0)
    resolver = TierResolver(assignments={"acme-paid": paid}, default=free)
    limiter = RateLimiter(resolver)

    print("-- free-tier client bursts past its limit --")
    t0 = 0.0
    for i in range(5):
        allowed, retry_after = limiter.check("acme-free", now=t0)
        print(f"request {i}: allowed={allowed} retry_after={retry_after:.3f}s")

    print("\n-- paid-tier client has a higher ceiling at the same instant --")
    for i in range(5):
        allowed, retry_after = limiter.check("acme-paid", now=t0)
        print(f"request {i}: allowed={allowed} retry_after={retry_after:.3f}s")

    print("\n-- free-tier client retries after the suggested retry_after --")
    allowed, retry_after = limiter.check("acme-free", now=t0)
    assert not allowed
    allowed, _ = limiter.check("acme-free", now=t0 + retry_after)
    print(f"after waiting {retry_after:.3f}s: allowed={allowed}")
