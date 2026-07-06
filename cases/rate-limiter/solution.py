"""Reference implementation for the Rate Limiter design in README.md.

Implements the token bucket LimitAlgorithm chosen in Tradeoffs, with a
pluggable interface so a sliding-window or fixed-window variant could be
swapped in without touching CounterStore or the public check() surface.
"""
from __future__ import annotations  # lets type hints like dict[str, Tier] work on older Python 3 minor versions

import time                                   # time.monotonic() is the default clock for check() when the caller doesn't supply one
import threading                              # guards bucket state since check() can be called concurrently from many request threads
from dataclasses import dataclass             # Tier and other value objects are plain immutable data holders
from typing import Optional                   # used for parameters that may legitimately be omitted


@dataclass(frozen=True)                       # frozen: a Tier is a value, never mutated after creation
class Tier:
    name: str                                 # human-readable label, e.g. "free" or "paid"
    limit: int                                # max requests allowed per window
    window_seconds: float                     # length of that window, in seconds


class TierResolver:
    """Maps a client to its Tier. Backed by a dict here; in production this
    is a cached read-through to the identity/billing system of record."""

    def __init__(self, assignments: dict[str, Tier], default: Tier):
        self._assignments = dict(assignments)  # copy so caller's dict can't be mutated out from under us
        self._default = default                # tier used for any client not explicitly assigned

    def resolve(self, client_id: str) -> Tier:
        return self._assignments.get(client_id, self._default)  # explicit assignment wins, else default tier

    def set_tier(self, client_id: str, tier: Tier) -> None:
        self._assignments[client_id] = tier    # simulates a tier change landing (e.g. an upgrade/downgrade)


class LimitAlgorithm:
    def check(self, client_id: str, tier: Tier, now: float) -> tuple[bool, float]:
        raise NotImplementedError              # interface only; concrete algorithms subclass this


class TokenBucketAlgorithm(LimitAlgorithm):
    """Chosen over fixed-window in Tradeoffs: smooths bursts at a window
    boundary instead of allowing up to 2x the limit across two windows."""

    def __init__(self):
        self._lock = threading.Lock()          # protects _buckets from concurrent check() calls
        self._buckets: dict[str, tuple[float, float]] = {}  # client -> (tokens remaining, timestamp of last refill)

    def check(self, client_id: str, tier: Tier, now: float) -> tuple[bool, float]:
        refill_rate = tier.limit / tier.window_seconds       # tokens regenerated per second for this tier
        with self._lock:                                     # serialize read-modify-write of one client's bucket
            tokens, last_refill = self._buckets.get(client_id, (float(tier.limit), now))  # start full on first sight
            tokens = min(tier.limit, tokens + (now - last_refill) * refill_rate)          # lazy refill since last check
            if tokens >= 1:                                  # enough in the bucket to spend one token
                self._buckets[client_id] = (tokens - 1, now)  # spend it, and remember this as the new refill baseline
                return True, 0.0                              # allowed, no retry_after needed
            self._buckets[client_id] = (tokens, now)          # not enough tokens; still record the refill baseline
            missing = 1 - tokens                              # fraction of a token still needed
            retry_after = missing / refill_rate               # time until that fraction refills
            return False, retry_after                         # denied, with a real (not hardcoded) retry hint


class RateLimiter:
    """The check() operation from API Design. Synchronous, in the request
    path of every protected API."""

    def __init__(self, tier_resolver: TierResolver, algorithm: Optional[LimitAlgorithm] = None):
        self._tiers = tier_resolver                                   # resolves client_id -> Tier
        self._algorithm = algorithm or TokenBucketAlgorithm()         # default to the chosen algorithm

    def check(self, client_id: str, now: Optional[float] = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now  # real clock by default, injectable for deterministic tests
        tier = self._tiers.resolve(client_id)            # look up this client's limit/window
        return self._algorithm.check(client_id, tier, now)  # delegate to the pluggable algorithm


if __name__ == "__main__":
    free = Tier("free", limit=3, window_seconds=1.0)                              # 3 requests/second
    paid = Tier("paid", limit=10, window_seconds=1.0)                             # 10 requests/second
    resolver = TierResolver(assignments={"acme-paid": paid}, default=free)        # only acme-paid is on the paid tier
    limiter = RateLimiter(resolver)                                               # wire tiers + default algorithm together

    print("-- free-tier client bursts past its limit --")
    t0 = 0.0                                            # fixed instant in time, so the demo is deterministic
    for i in range(5):                                  # 5 requests against a limit of 3
        allowed, retry_after = limiter.check("acme-free", now=t0)
        print(f"request {i}: allowed={allowed} retry_after={retry_after:.3f}s")

    print("\n-- paid-tier client has a higher ceiling at the same instant --")
    for i in range(5):                                  # same 5 requests, but this client's tier allows all of them
        allowed, retry_after = limiter.check("acme-paid", now=t0)
        print(f"request {i}: allowed={allowed} retry_after={retry_after:.3f}s")

    print("\n-- free-tier client retries after the suggested retry_after --")
    allowed, retry_after = limiter.check("acme-free", now=t0)  # still exhausted from the burst above
    assert not allowed                                          # confirms the bucket is actually empty at t0
    allowed, _ = limiter.check("acme-free", now=t0 + retry_after)  # advance the clock by exactly retry_after
    print(f"after waiting {retry_after:.3f}s: allowed={allowed}")  # proves retry_after is a real, honored promise
