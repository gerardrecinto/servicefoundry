# Case to LLD / OOP Map

Use this as the quick interview-prep map for what each case is really testing.

## Fast Pattern Key

| Concept | Meaning in these cases |
|---|---|
| Domain model | The core nouns with identity, ownership, and relationships. |
| State machine | Explicit legal transitions for things like tickets, rides, packages, seats, and reservations. |
| Strategy | Swappable algorithm behind a stable interface. |
| Adapter | Wrapper around external systems like payment processors, providers, devices, or stores. |
| Repository / store | Module that owns persistence details and hides storage shape from domain logic. |
| Idempotency | Retry-safe command handling using a stable key. |
| Concurrency control | Compare-and-set, conditional update, deduping, or single-owner mutation to prevent races. |
| Event-driven design | Async reactions such as notifications, retries, reconciliation, or propagation. |
| Command-query separation | Reads/calculations with no side effects separated from writes/transitions. |

## Case Map

| Case | Main LLD Concepts | OOP / SOLID Principles | Clean Code Angle |
|---|---|---|---|
| [locker-service](../cases/locker-service) | Domain model, reservation state machine, device reconciliation, idempotent reservation/drop-off, non-idempotent unlock, async notification. | SRP: `LockerAllocator`, `AccessCodeIssuer`, `ReservationLifecycle`, and `DeviceReconciler` each own one reason to change. Encapsulation: only lifecycle code changes reservation state. DIP: hardware/device reports are isolated from customer-facing reservation logic. | Separate logical state from physical sensor state. Keep security-sensitive behavior explicit: repeat unlock fails instead of hiding a bad state. |
| [parking-garage](../cases/parking-garage) | Ticket lifecycle, pure pricing, payment adapter, occupancy reconciliation, idempotent entry/pay, command-query separation for quote vs pay. | SRP: `Pricer` only calculates, `TicketLifecycle` only transitions, `PaymentGateway` adapts the processor. DIP: lifecycle depends on a gateway interface, not a processor implementation. | Pure functions make pricing easy to test. Derived occupancy is reconcilable, so a sensor bug does not poison the source of truth. |
| [package-delivery](../cases/package-delivery) | Batch route planning, package state machine, ordered event processing, deduping, async notifications, retry/return flow. | SRP: `RoutePlanner` does allocation, `PackageLifecycle` does state transitions, `AttemptDeduper` protects the state machine. OCP: route-planning strategy can evolve without touching delivery status rules. | Do not mix planning, state transitions, and notifications. Order by event time, not arrival time, because the domain says devices can be offline. |
| [rate-limiter](../cases/rate-limiter) | Strategy pattern for algorithms, distributed counter store, token bucket, tier resolver cache, explicit fail-open/fail-closed policy. | OCP: `LimitAlgorithm` can change from fixed window to token bucket behind the same interface. DIP: algorithm depends on `CounterStore`, not a concrete cache. SRP: tier lookup, algorithm, and storage are separate. | Keep the hot path tiny. Put policy in named modules/config instead of burying fallback behavior in incidental code. |
| [ticket-booking](../cases/ticket-booking) | Seat/hold/booking domain model, seat state machine, compare-and-set concurrency, hold expiry worker, idempotent confirm. | Encapsulation: `SeatAvailability` is the only writer of seat state. SRP: `HoldExpiry` and `BookingConfirmer` do not share responsibilities. | Model the invariant directly: one seat has at most one active hold. Make expiry server-owned so clients cannot bend core rules. |
| [notification-platform](../cases/notification-platform) | Async acceptance/delivery, template rendering, provider routing/failover, retry scheduler, preference gate, delivery attempts. | SRP: renderer, preference gate, provider router, and retry scheduler are separate. DIP: provider-specific APIs sit behind `ProviderRouter`. OCP: add a provider/channel without rewriting callers. | Synchronous validation, asynchronous delivery. Re-check opt-out before each send because the world can change while work is queued. |
| [inventory-reservation](../cases/inventory-reservation) | Stock ledger, reservations with expiry, partial fulfillment, per-stock-record atomic updates, idempotent confirm/release. | Encapsulation: `StockLedger` is the only mutator of stock. SRP: `ReservationSplitter` decides allocation but does not mutate. DIP: checkout flow depends on stock operations, not warehouse internals. | Keep allocation decisions separate from mutation. Avoid distributed transactions where per-line idempotent confirmation handles the real failure shape better. |
| [ride-dispatch](../cases/ride-dispatch) | Matching workflow, match offer state machine, ride lifecycle, location ingest, timeout-as-decline, cancellation race handling. | SRP: `Matcher` ranks candidates but does not mutate lifecycle state. Encapsulation: `RideLifecycle` owns legal ride/trip transitions. OCP: ranking can change without rewriting match response handling. | Isolate high-volume location writes from matching logic. Bound retry loops so "try next driver" cannot run forever. |
| [file-sync](../cases/file-sync) | Version graph, immutable file versions, conflict detection, sync cursors, conflict resolution, idempotent device uploads. | SRP: `VersionStore` appends/query versions, `ConflictDetector` decides divergence, `SyncCursorTracker` tracks device progress. Encapsulation: conflict logic lives in one place instead of being scattered through upload code. | Prefer immutable history over in-place overwrite when debugging depends on ancestry. Keep per-device cursor state out of the version history. |
| [feature-flag-service](../cases/feature-flag-service) | Local snapshot reads, targeting-rule evaluation, kill switch path, async propagation, deterministic bucketing. | SRP: `RuleEvaluator` is pure, `FlagSnapshotStore` owns local data, `SnapshotPublisher` owns propagation, `KillSwitch` owns override behavior. OCP: new targeting rules can be added behind evaluator logic without changing callers. | Keep evaluation local and pure because it is on every request. Separate write path from read path to avoid coupling admin latency to user traffic. |

## What To Say Out Loud

If you need a compact interview answer:

> I start by finding the domain objects and the state machines. Then I isolate the modules that own mutation, make retries idempotent, and keep external systems behind adapters. For SOLID, most of these designs are about SRP, OCP, and DIP: one class owns one business rule, algorithms can change behind interfaces, and domain logic does not depend directly on providers, devices, or databases.

## Cross-Case Themes

| Theme | Cases | Why it matters |
|---|---|---|
| State machines | locker-service, parking-garage, package-delivery, ticket-booking, ride-dispatch | Prevents illegal transitions like `delivered -> out_for_delivery` or `picked_up -> occupied`. |
| Idempotency | locker-service, parking-garage, package-delivery, ticket-booking, notification-platform, inventory-reservation, ride-dispatch, file-sync | Makes client retries safe under timeouts and flaky networks. |
| Single writer / encapsulated mutation | ticket-booking, inventory-reservation, locker-service, ride-dispatch, file-sync | Prevents race conditions and keeps invariants in one place. |
| Pure calculation | parking-garage, package-delivery, notification-platform, feature-flag-service | Makes core decisions deterministic and easy to test. |
| Adapter boundaries | parking-garage, notification-platform, locker-service, rate-limiter | Keeps external systems from leaking into domain logic. |
| Async side effects | locker-service, package-delivery, notification-platform, ride-dispatch, feature-flag-service | Keeps user-facing writes fast while slower work continues safely. |
| Reconciliation | locker-service, parking-garage, file-sync | Accepts that physical devices/offline clients can be wrong or late, then corrects explicitly. |

## SOLID Cheat Sheet For This Repo

| Principle | How it shows up here |
|---|---|
| Single Responsibility Principle | Each module owns one business capability: pricing, lifecycle transitions, dedupe, provider routing, rule evaluation. |
| Open/Closed Principle | Algorithms and providers sit behind stable interfaces: rate-limit algorithms, route planning, provider routing, targeting rules. |
| Liskov Substitution Principle | Any implementation behind a strategy or adapter should preserve the same contract, such as `LimitAlgorithm.check()` returning allowed/denied with retry data. |
| Interface Segregation Principle | Callers get narrow APIs: evaluate a flag, check a limit, confirm a hold, quote a ticket. They do not depend on admin/write/provider APIs they never use. |
| Dependency Inversion Principle | Domain modules depend on abstractions like `PaymentGateway`, `CounterStore`, provider routing, or snapshot stores instead of concrete external systems. |

## DRY / KISS / Clean Code Notes

- DRY means centralizing business rules, not forcing every case into the same class names.
- KISS means choosing the simplest control point that protects the invariant: compare-and-set for seats, atomic stock update for inventory, deterministic hash for flag rollout.
- Prefer explicit domain errors over silent success when security or correctness matters, like repeat locker unlocks or expired holds.
- Keep hot paths small: rate-limit check, flag evaluation, seat hold, and locker allocation should avoid unnecessary network or background work.
- Put slow or failure-prone work behind queues or adapters: notifications, provider retries, snapshot propagation, and reconciliation.
