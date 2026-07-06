# Rate Limiter

## Problem
An API platform needs to cap how many requests a client can make in a given window, enforced consistently across many stateless API servers, without adding noticeable latency to every request.

## Requirements

### Functional
- Enforce a limit per client per time window (e.g., 100 requests/minute).
- Support different limits per client tier.
- Reject over-limit requests with enough information for the client to back off correctly.

### Non-functional
- Limiting logic must add negligible latency (single-digit milliseconds) to the request path.
- Must work correctly across many API server instances sharing one logical limit per client, not one limit per instance.

### Out of scope
- Client-side retry/backoff implementation.
- Billing based on usage.

## Domain Model
- **Client** — identified by API key or account id; has a **Tier** determining its limit.
- **Tier** — defines a (limit, window) pair.
- **LimitCounter** — the current count for a (Client, window) pair; the only piece of mutable state in this service.

## API Design
- `check(client_id) -> Allowed | Denied(retry_after)` — the only operation; called synchronously in the request path of every protected API, so it has to be cheap. Not an HTTP endpoint in most deployments — usually a library/sidecar call.
- Denied responses always include `retry_after`, computed from the window's reset time, not a hardcoded value.

## Class / Module Design
- `LimitAlgorithm` — pluggable strategy (token bucket, sliding window log, fixed window counter); isolated behind one interface so the algorithm can change without touching callers.
- `CounterStore` — the storage backend (e.g., a shared cache) for LimitCounter state; the only module aware it's distributed.
- `TierResolver` — maps Client to Tier; cached aggressively since tier changes are rare compared to request volume.

## Edge Cases & Failure Modes
- CounterStore is briefly unreachable — the algorithm fails open (allow) or closed (deny) based on an explicit, documented per-tier policy, not an accidental default; failing open silently for every client would defeat the limiter's purpose during exactly the incident it exists to contain.
- Clock skew across servers under a fixed-window algorithm causes boundary bursts — addressed by preferring a sliding-window or token-bucket algorithm where correctness doesn't depend on all servers agreeing on wall-clock window edges.
- A client's tier changes mid-window — the new tier applies to the next window, not retroactively, so a client already tracked against the old limit doesn't get double-counted against two limits.

## Tradeoffs
- **Chose**: token bucket as the default `LimitAlgorithm`. **Rejected**: fixed window counter. Reason — fixed windows allow a client to burst 2x the limit at a window boundary; token bucket smooths that out at a modest memory cost.
- **Chose**: explicit fail-open/fail-closed policy per tier. **Rejected**: a single global fallback behavior. Reason — a free tier failing open under a CounterStore outage is a cost risk; a paid tier failing closed under the same outage is an availability risk for a paying customer. One-size-fits-all fails one of them.

## Testing Strategy
- Unit: `LimitAlgorithm` implementations against a simulated clock, verifying exact boundary behavior (request at t=59.999s vs t=60.001s).
- Load test: `check()` latency under concurrent load against the real `CounterStore`, since latency is a functional requirement here, not just a nice-to-have.
- Not covered by automation: real network partition behavior of the shared cache — validated in a chaos-testing environment.

## Operations
- Track denied-request rate per client; a client consistently at the ceiling may need a tier conversation, not just more denials.
- Track `CounterStore` latency separately from `check()` latency, so a slow store is diagnosable instead of just "the rate limiter is slow."
- Fail-open/fail-closed policy is a runtime config, not a code deploy, so it can be flipped during an active incident.
