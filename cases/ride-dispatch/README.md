# Ride Dispatch

## Problem
A ride-hailing app needs to match a rider's request to a nearby available driver, track the ride through pickup and drop-off, and handle drivers who go offline or riders who cancel mid-match.

## Requirements

### Functional
- Match a ride request to the best available nearby driver.
- Track ride status from `requested → matched → driver_en_route → in_progress → completed`, or `cancelled` at various points.
- Handle a driver declining or timing out on a match by offering the next-best driver.
- Handle rider cancellation before and after a match.

### Non-functional
- Matching should complete within a couple of seconds of the request in dense areas.
- Driver location updates arrive frequently and shouldn't overwhelm the matching path.

### Out of scope
- Pricing/surge calculation.
- Payment.

## Domain Model
- **RideRequest** — a rider's ask, with pickup location; owns the overall ride state.
- **Driver** — has a live location and an availability state (`available, offered, on_trip, offline`).
- **Match** — a proposed pairing of RideRequest to Driver with a response deadline; a RideRequest can go through several Matches if drivers decline.
- **Trip** — created once a Match is accepted; tracks the actual pickup/drop-off events.

## API Design
- `POST /ride-requests` — creates a RideRequest and triggers matching; idempotent on `(rider_id, client_request_id)`.
- `POST /matches/{id}/respond` — driver accepts or declines; only the currently-offered driver for that Match can respond, and only before the deadline.
- `POST /ride-requests/{id}/cancel` — rider cancels; behavior differs depending on current state (no driver yet vs. already matched vs. already en route), but the endpoint itself is uniform.

## Class / Module Design
- `Matcher` — finds candidate drivers by proximity and availability, and ranks them; reads Driver location but never mutates Driver or RideRequest state itself.
- `MatchOffer` — owns the offer/response/timeout state machine for a single Match; on decline or timeout, tells `Matcher` to produce the next candidate rather than looping back through the full ride-request flow.
- `RideLifecycle` — the only module that transitions RideRequest/Trip state; consumes events from `MatchOffer` and driver/rider actions.
- `LocationIngest` — high-frequency driver location updates land here and update a fast-read location index; deliberately isolated from `Matcher`'s ranking logic so location volume can scale independently of matching logic changes.

## Edge Cases & Failure Modes
- Driver doesn't respond to a Match before the deadline — treated the same as an explicit decline; `MatchOffer` expires it and `Matcher` offers the next candidate, without the rider seeing a gap.
- Rider cancels exactly as a driver accepts — the accept and the cancel race; `RideLifecycle` resolves this by treating a cancel as valid up until `driver_en_route` is durably recorded, after which cancellation still succeeds but is flagged as a late cancellation, since a driver has already committed.
- Driver goes offline (app killed, network loss) mid-match without explicitly declining — a location-staleness timeout in `LocationIngest` marks the driver unavailable, which `MatchOffer` treats as an implicit decline rather than waiting out the full response deadline.
- No drivers available within matching radius — `Matcher` returns no-candidates rather than blocking; `RideLifecycle` surfaces this to the rider immediately instead of holding the request open indefinitely.

## Tradeoffs
- **Chose**: sequential single-driver offers with fast timeout/fallback. **Rejected**: broadcasting to multiple drivers simultaneously and taking the first accept. Reason — broadcast matching creates driver-side frustration (bidding on rides they won't get) and requires more complex reconciliation when two accept near-simultaneously; sequential offers trade a little latency for a much simpler state machine.
- **Chose**: isolating high-frequency location updates from the matching/ranking path. **Rejected**: one unified service. Reason — location update volume scales with active drivers regardless of ride demand, and coupling it to matching logic would make matching changes riskier to deploy.

## Testing Strategy
- Unit: `MatchOffer` state machine, including timeout-as-implicit-decline and the late-cancellation branch.
- Simulation: `Matcher` against synthetic driver distributions, checking candidate ranking quality and no-candidate handling.
- Not covered by automation: real-world GPS accuracy/noise — validated against recorded field data, not synthetic tests.

## Operations
- Track match-to-accept latency and decline/timeout rate per area; a rising decline rate in one area suggests a ranking problem, not just driver behavior.
- Alert on `LocationIngest` lag, since stale locations degrade every downstream matching decision silently.
- Late-cancellation rate (post-en-route) is tracked separately from early cancellation, since it has different implications for driver trust in the matching system.
