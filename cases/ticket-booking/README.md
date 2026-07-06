# Ticket Booking

## Problem
An events platform sells seats for a show. Many customers may try to book the same seat at once, and a customer needs a brief hold on a seat while they enter payment details, without overselling.

## Requirements

### Functional
- Show live seat availability for an event.
- Hold a seat for a customer for a short window while they check out.
- Convert a hold to a confirmed booking on successful payment.
- Release a hold automatically if checkout isn't completed in time.

### Non-functional
- Must never sell the same seat twice, even under concurrent requests for a popular event.
- Hold/release must be fast enough to feel instant in the seat map UI.

### Out of scope
- Seating chart rendering.
- Refunds/cancellations after the event.

## Domain Model
- **Event** — has a fixed set of **Seats**.
- **Seat** — belongs to one Event; state is `available → held → booked`, or back to `available` on hold expiry/cancellation.
- **Hold** — links a Customer to a Seat with an expiry; a Seat has at most one active Hold at a time.
- **Booking** — created from a successfully-paid Hold; immutable once created.

## API Design
- `POST /seats/{id}/hold` — succeeds only if the seat is `available`; idempotent on `(customer_id, seat_id)` so a UI double-click doesn't create two competing holds from the same customer.
- `POST /holds/{id}/confirm` — requires a valid, unexpired hold and successful payment; transitions Seat to `booked`.
- Holds carry a server-set expiry; there's no client-supplied hold duration, to prevent a client from holding a seat indefinitely.

## Class / Module Design
- `SeatAvailability` — the only module that transitions Seat state; uses a compare-and-set style update (expected current state → new state) so two concurrent hold requests for the same seat can't both succeed.
- `HoldExpiry` — a background sweep that releases expired holds; deliberately separate from the request path so checkout latency doesn't depend on expiry-scanning work.
- `BookingConfirmer` — the only module allowed to create a Booking, and only from a Hold it can verify is still valid at confirmation time.

## Edge Cases & Failure Modes
- Two customers click the same seat within milliseconds — the compare-and-set in `SeatAvailability` guarantees exactly one hold succeeds; the other gets an immediate "seat no longer available," not a queued retry that might succeed later and confuse the UI.
- Customer completes payment just as their hold expires — `BookingConfirmer` re-checks hold validity at confirmation, not just at hold creation, and fails the booking rather than let the seat double-sell against a hold that already lapsed.
- Payment succeeds but the confirm call times out on the client side — `confirm` is idempotent on the hold id, so a client retry after a timeout doesn't create a duplicate booking or double-charge.

## Tradeoffs
- **Chose**: compare-and-set on Seat state as the concurrency control. **Rejected**: a global lock per event during booking. Reason — a per-event lock serializes all seat holds for a popular event into one queue, which is the exact bottleneck this design needs to avoid.
- **Chose**: server-controlled hold expiry. **Rejected**: client-specified duration. Reason — a malicious or buggy client could hold inventory indefinitely and block other customers.

## Testing Strategy
- Concurrency test: many simulated customers hitting `hold` on the same seat simultaneously, asserting exactly one success.
- Unit: `HoldExpiry` sweep against holds at various points relative to their expiry, including one expiring mid-confirm.
- Not covered by automation: real payment processor timing — tested against a sandbox, not the automated suite.

## Operations
- Track hold-to-confirm conversion rate and time; a rising abandonment rate close to expiry suggests the hold window itself is too short for the checkout flow.
- Alert if `HoldExpiry` sweep lag grows, since a stuck sweep means seats stay artificially unavailable.
- Seat contention rate (holds attempted on an already-held seat) is a leading indicator of demand for a specific event, useful beyond just system health.
