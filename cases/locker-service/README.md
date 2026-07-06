# Locker Pickup System

## Problem
A retailer wants customers to pick up online orders from self-service lockers at physical store locations, without a staff member present, and without the customer needing an account beyond their order.

## Requirements

### Functional
- Assign a package to an available locker sized to fit it, at the pickup location the customer chose.
- Generate a one-time access code (or QR) delivered to the customer once the package is placed.
- Let the customer open the assigned locker with that code within a pickup window.
- Release the locker automatically if the window expires, and notify the customer.
- Support couriers loading multiple packages into multiple lockers as a batch.

### Non-functional
- A locker bank at a busy location may serve 500+ pickups/day; assignment must be fast enough not to hold up a courier's loading run.
- Access codes must not be guessable or reusable after pickup or expiration.
- Locker state must be consistent even if the network to a given locker bank is briefly unreachable (lockers are physical devices, not always online).

### Out of scope
- Payment processing (assumed already settled before drop-off).
- Locker manufacturing/firmware.

## Domain Model
- **Location** — a physical site with a fixed set of **Lockers**.
- **Locker** — belongs to exactly one Location; has a size class and a state (`empty`, `reserved`, `occupied`, `out_of_service`).
- **Reservation** — links an **Order** to a **Locker** for a pickup window; owns the access code and its expiry.
- **Order** — external reference (from the retailer's order system); ServiceFoundry only tracks the subset needed for pickup (id, size class, customer contact).

A Locker's physical state (door open/closed, weight sensor) is reported by the device and reconciled against the Reservation's logical state — the two are allowed to disagree briefly, but not indefinitely.

## API Design
- `POST /reservations` — courier requests a locker of a given size class at a location; idempotent on `order_id` (retrying with the same order returns the same reservation, not a second locker).
- `POST /reservations/{id}/confirm-drop-off` — courier confirms the package is physically in the locker; triggers code generation and the customer notification. Idempotent.
- `POST /reservations/{id}/unlock` — customer submits their code; succeeds once, then the reservation moves to `picked_up`. Not idempotent by design — a second identical unlock attempt after pickup should fail with a domain error, not silently succeed, since that would mask a locker left open.
- `POST /lockers/{id}/heartbeat` — device reports physical state; used for reconciliation, not for customer-facing decisions.

## Class / Module Design
- `LockerAllocator` — picks a locker for a reservation; the only module that reads and writes Locker state. Deliberately not aware of access codes.
- `AccessCodeIssuer` — generates and validates codes; has no knowledge of locker hardware.
- `ReservationLifecycle` — owns the state machine (`pending → occupied → picked_up` / `expired`); the only module allowed to transition a Reservation.
- `DeviceReconciler` — consumes heartbeats and flags mismatches for a human/ops queue; never auto-corrects a Reservation's state from a heartbeat alone, since sensors can be wrong.

## Edge Cases & Failure Modes
- Courier retries `confirm-drop-off` after a timeout — idempotency key prevents a second code from being issued for the same reservation.
- Customer's code expires while they're standing at the locker — `unlock` returns a specific expired-code error (not a generic failure), and the door stays locked; a new reservation/code requires re-authorization, not a silent extension.
- Locker reports `door open` with no matching `unlock` call — flagged by `DeviceReconciler` as a possible forced-open, routed to ops, not auto-resolved.
- Locker bank loses network mid-batch load — reservations already confirmed stay valid; new `POST /reservations` calls for that location fail closed (no allocation against a locker bank we can't currently verify).

## Tradeoffs
- **Chose**: locker state and device heartbeats as separate signals reconciled asynchronously. **Rejected**: treating heartbeats as the source of truth. Reason — a flaky sensor would then be able to silently invalidate a valid reservation.
- **Chose**: `unlock` as non-idempotent past first success. **Rejected**: making every endpoint idempotent for consistency. Reason — silently allowing repeat unlocks after pickup hides a security-relevant event.

## Testing Strategy
- Unit: `ReservationLifecycle` state transitions, especially illegal transitions (e.g., `unlock` on an already-`picked_up` reservation).
- Contract: `LockerAllocator` against a fake device layer, verifying it never double-allocates a locker under concurrent requests.
- Not covered by automation: physical door-latch behavior — verified by hardware QA, not this service's test suite.

## Operations
- Alert on reservations stuck in `occupied` past window + grace period without an `unlock` — usually a device or notification failure.
- Track allocation latency per location; a location trending upward is running out of available lockers before it's fully full (fragmentation by size class).
- Rollback path for a bad `LockerAllocator` deploy: feature-flag the allocation algorithm so a previous version can be reinstated without a full redeploy.
