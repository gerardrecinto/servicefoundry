# Parking Garage

## Problem
A garage operator wants to charge for parking without staffed booths — ticket on entry, pay before exit, gate opens on a valid payment, and different rates for different vehicle types and durations.

## Requirements

### Functional
- Issue a ticket on entry recording time and lane.
- Compute a fee at exit based on duration, vehicle class, and any active rate promotion.
- Accept payment (card/mobile) and open the exit gate only after payment clears.
- Support a "lost ticket" flow with a fallback fee.
- Track live occupancy per level for a "Full" sign.

### Non-functional
- Gate must respond in under 2 seconds from a valid payment to avoid a line backing up.
- Occupancy counts must survive a sensor miscount without permanently drifting.

### Out of scope
- Physical gate hardware protocol.
- Monthly permit billing (separate system).

## Domain Model
- **Garage** — has **Levels**, each with a capacity and a live count.
- **Ticket** — created on entry; references entry time, lane, vehicle class; transitions `open → paid → exited` or `open → lost`.
- **RateSchedule** — versioned rules mapping (vehicle class, duration, time-of-day) to a fee; a Ticket is priced against the RateSchedule active at entry time, not exit time, so a mid-stay price change doesn't retroactively change what's owed.
- **Payment** — external reference to a payment processor result, linked to a Ticket.

## API Design
- `POST /tickets` (entry) — idempotent on `(lane_id, entry_sensor_event_id)` so a sensor bounce doesn't create two tickets for one car.
- `GET /tickets/{id}/quote` — pure calculation, no side effects, safe to call repeatedly as the driver waits.
- `POST /tickets/{id}/pay` — idempotent on the payment processor's idempotency key; only transitions to `paid` once regardless of retries.
- `POST /tickets/{id}/exit` — only succeeds if `paid` (or `lost` fee settled); opens the gate.

## Class / Module Design
- `Pricer` — pure function of (RateSchedule, entry_time, exit_time, vehicle_class); no I/O, easy to unit test exhaustively.
- `TicketLifecycle` — the only module that moves a Ticket between states.
- `OccupancyTracker` — increments/decrements per-level counts from entry/exit events; deliberately decoupled from `TicketLifecycle` so a ticketing bug can't also corrupt occupancy, and vice versa.
- `PaymentGateway` — adapter over the external processor; `TicketLifecycle` depends on its interface, not its implementation.

## Edge Cases & Failure Modes
- Entry sensor fires twice for one car — idempotency key collapses it to one Ticket.
- Driver pays, then the gate fails to open — `exit` is safe to retry; it checks `paid` state rather than re-charging.
- Lost ticket — flat fallback fee, and the flow explicitly creates a new synthetic Ticket record for audit rather than mutating a nonexistent one.
- Occupancy sensor undercounts — a nightly reconciliation job recomputes counts from ticket records, since ticket state is the source of truth and sensors are a fast-path optimization.

## Tradeoffs
- **Chose**: price locked at entry-time RateSchedule. **Rejected**: pricing at exit time. Reason — a driver shouldn't be charged more because a rate changed while their car was already parked.
- **Chose**: occupancy as a derived, reconcilable counter. **Rejected**: occupancy as the authoritative gate for "is this car allowed to park." Reason — a miscounted sensor shouldn't be able to block a paying customer from entering; capacity enforcement degrades gracefully to advisory rather than hard-blocking.

## Testing Strategy
- Unit: `Pricer` against a matrix of durations/vehicle classes/time-of-day, including exact rate-schedule boundaries.
- Integration: `TicketLifecycle` + `PaymentGateway` fake, covering retried payments and failed-then-retried gate opens.
- Not covered by automation: physical gate response time — measured in staging with real hardware.

## Operations
- Alert if `paid` tickets fail to reach `exited` within a few minutes — likely a gate hardware fault.
- Track quote-to-pay conversion time; a spike suggests a confusing price display, not a system fault, but it's this service's data that would surface it.
- Reconciliation job discrepancy count is a health metric in its own right — consistently nonzero means a sensor is degrading, not just noisy.
