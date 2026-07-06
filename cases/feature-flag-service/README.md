# Feature Flag Service

## Problem
Multiple product teams need to turn features on/off and roll them out gradually to subsets of users, without redeploying, and without one team's flag evaluation being slow enough to affect page load.

## Requirements

### Functional
- Define a flag with a set of targeting rules (user attributes, percentage rollout, explicit allow/deny lists).
- Evaluate a flag for a given user/context and return on/off (or a variant).
- Update a flag's rules and have it take effect without a redeploy.
- Support instant kill-switch rollback of a flag.

### Non-functional
- Evaluation must be fast enough to happen on every page load / API request without noticeable latency — effectively a local, not networked, operation from the caller's perspective.
- Rule changes should propagate to all evaluating services within a short, bounded time.

### Out of scope
- A/B test statistical analysis.
- Flag-authoring UI.

## Domain Model
- **Flag** — has an ordered set of **TargetingRules** and a default value; identified by a stable key services reference in code.
- **TargetingRule** — a condition (attribute match, percentage bucket, explicit list) plus the value to return if it matches; evaluated in order, first match wins.
- **EvaluationContext** — the caller-supplied user/request attributes a Flag's rules are evaluated against; not persisted, exists only for the duration of one evaluation.

## API Design
- `evaluate(flag_key, context) -> value` — the hot-path operation; implemented as a local library reading a periodically-refreshed local snapshot of flag definitions, not a network call per evaluation.
- `PUT /flags/{key}` — updates a Flag's rules; the write path is intentionally separate from the read/evaluate path, which never talks to this API directly.
- `POST /flags/{key}/kill` — sets the flag to its safe default immediately, bypassing the normal rule set entirely, for use during an incident.

## Class / Module Design
- `RuleEvaluator` — pure function of (Flag, EvaluationContext) → value; no I/O, so it's trivially fast and trivially testable.
- `FlagSnapshotStore` — holds the local, periodically-refreshed copy of flag definitions that `RuleEvaluator` reads; isolates evaluation latency from whatever the actual flag-definition storage/propagation mechanism is.
- `SnapshotPublisher` — pushes updated flag definitions out to `FlagSnapshotStore` instances; the only module aware of how propagation actually happens (poll, push, pub/sub).
- `KillSwitch` — a narrow, separate path that can override a Flag's evaluation to its safe default, deliberately not routed through the normal rule-update flow so it isn't slowed down by anything rule-related during an incident.

## Edge Cases & Failure Modes
- `SnapshotPublisher` fails to reach a given service instance — that instance keeps evaluating against its last-known-good snapshot rather than failing evaluation entirely; a stale-but-valid flag state is preferred over no flag state.
- A percentage-rollout rule needs to give the same user a consistent result across repeated evaluations — bucketing is a deterministic hash of (flag_key, user_id), not random per call, so the same user doesn't flip in and out of a rollout on every page load.
- Kill-switch is triggered while a normal rule update is also in flight — kill-switch state is checked first and short-circuits `RuleEvaluator` entirely, so an in-progress rule update can't race past what the kill-switch is meant to definitively suppress.
- A flag is evaluated before its definition has ever reached a given service instance (cold start) — `FlagSnapshotStore` returns the flag's documented default rather than an error, since callers shouldn't have to handle "flag doesn't exist yet" as a distinct case from "flag is off."

## Tradeoffs
- **Chose**: local snapshot with periodic refresh for evaluation. **Rejected**: a network call to a central service per evaluation. Reason — evaluation happens on every request in the calling services; a network round-trip there would add latency and a new failure mode to every request path in the company.
- **Chose**: deterministic hash-based bucketing for percentage rollouts. **Rejected**: random assignment per evaluation. Reason — random assignment means a user could be in a rollout on one request and out on the next, which is confusing for the user and makes bug reports about "the new feature" impossible to reproduce.

## Testing Strategy
- Unit: `RuleEvaluator` against rule-ordering edge cases (first-match-wins with overlapping conditions) and bucketing determinism across repeated calls with the same context.
- Integration: `SnapshotPublisher` → `FlagSnapshotStore` propagation delay under simulated network issues, verifying stale-snapshot fallback rather than evaluation failure.
- Not covered by automation: how flag changes interact with each specific calling service's own caching layers — that's the calling service's responsibility to test.

## Operations
- Track snapshot staleness per service instance; an instance stuck on an old snapshot is running with outdated flag behavior without anyone necessarily noticing.
- Kill-switch activations are logged and alerted on unconditionally, since they only fire during an incident by design.
- Evaluation latency is monitored as a p99, not an average, since the whole point of the local-snapshot design is to make even the worst case fast.
