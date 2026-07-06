# Package Delivery Service

## Problem
A logistics company needs to get packages from a depot to a customer's address, assigning them to drivers, tracking status, and handling failed delivery attempts, without a human dispatcher manually routing every package.

## Requirements

### Functional
- Group packages into routes for a driver's shift.
- Track each package through `at_depot → out_for_delivery → delivered / delivery_failed → returned_to_depot`.
- Retry failed deliveries a bounded number of times before returning to sender.
- Notify the customer on dispatch, on failure, and on delivery.

### Non-functional
- Route assignment for a depot's morning batch (thousands of packages) must complete before drivers start their shift.
- Status updates from drivers' handheld devices may arrive out of order or duplicated over spotty connectivity.

### Out of scope
- Turn-by-turn navigation.
- Driver payroll.

## Domain Model
- **Package** — has a delivery address and a status; belongs to at most one active **Route** at a time.
- **Route** — an ordered list of Packages assigned to a **Driver** for a shift.
- **DeliveryAttempt** — one try at delivering a Package; a Package can have several across its lifetime, each with an outcome and reason code.
- **Driver** — has shift capacity (max packages/route length) used by route assignment, not by the Package itself.

## API Design
- `POST /routes` — batch-assigns unassigned Packages to Drivers for a depot; not idempotent in the retry sense (it's a planning operation), but safe to re-run since it only touches `at_depot` packages.
- `POST /packages/{id}/attempts` — driver device reports an attempt outcome; idempotent on `(package_id, device_event_id)` to absorb duplicate reports from unreliable connectivity.
- `GET /packages/{id}` — status lookup for customer-facing tracking.

## Class / Module Design
- `RoutePlanner` — pure allocation logic (packages → routes given driver capacity and geography); no knowledge of delivery outcomes.
- `PackageLifecycle` — the only module that transitions Package status, driven by DeliveryAttempt events.
- `AttemptDeduper` — sits in front of `PackageLifecycle`, collapsing duplicate/out-of-order device events using event timestamps and ids before they reach the state machine.
- `NotificationTrigger` — subscribes to Package state changes; decoupled from `PackageLifecycle` so a notification outage never blocks a delivery from being recorded.

## Edge Cases & Failure Modes
- Device reports "delivered" twice — deduped, second report is a no-op.
- Two attempt events for the same package arrive out of order (failure then, late, an earlier success) — ordered by event timestamp, not arrival time, before applying to the state machine.
- Package fails all retry attempts — moves to `returned_to_depot`, which re-enters `RoutePlanner`'s pool for a return route, not a delivery route.
- Driver's device goes offline mid-route — packages stay `out_for_delivery`; a stale-route job after a shift-length timeout flags them for manual reconciliation rather than guessing an outcome.

## Tradeoffs
- **Chose**: order attempt events by device timestamp for state transitions. **Rejected**: order by server arrival time. Reason — spotty connectivity means arrival order doesn't reflect what actually happened at the doorstep.
- **Chose**: decouple notifications from the state machine. **Rejected**: send notifications synchronously as part of the status-transition transaction. Reason — a third-party SMS/email outage shouldn't be able to block package status from updating.

## Testing Strategy
- Unit: `PackageLifecycle` transition table, including illegal transitions (e.g., `delivered → out_for_delivery`).
- Property-based: `AttemptDeduper` against randomly reordered/duplicated event streams, asserting the final state matches the true chronological outcome.
- Not covered by automation: real GPS/geography quality of `RoutePlanner`'s output — evaluated offline against historical routes.

## Operations
- Alert on packages stuck `out_for_delivery` past shift end.
- Track dedup-collision rate as a proxy for device connectivity quality in the field.
- `RoutePlanner` runs as a batch job with a hard deadline before shift start; a slow run is paged as urgent, not queued as low-priority, because a late batch delays every driver.
