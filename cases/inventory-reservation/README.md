# Inventory Reservation Service

## Problem
An e-commerce checkout needs to hold stock for items in a cart during checkout, release the hold if checkout is abandoned, and never confirm an order against stock that isn't actually there, across many warehouses.

## Requirements

### Functional
- Reserve a quantity of a SKU at a specific warehouse for a cart during checkout.
- Confirm reservations into a firm deduction on order completion.
- Release reservations automatically on checkout timeout or explicit cart abandonment.
- Support partial fulfillment across warehouses when one warehouse can't cover the full quantity.

### Non-functional
- Must prevent overselling under concurrent checkouts for the same popular SKU.
- Reservation/release must be fast enough not to slow down checkout.

### Out of scope
- Physical warehouse pick/pack workflow.
- Supplier restocking.

## Domain Model
- **StockRecord** — (SKU, warehouse) pair with an `on_hand` quantity and a `reserved` quantity; `available = on_hand - reserved`.
- **Reservation** — links a Cart to one or more StockRecords with quantities; expires unless confirmed.
- **Order** — created from confirmed Reservations; deducts `on_hand` and clears `reserved` together, atomically per StockRecord.

## API Design
- `POST /reservations` — given (SKU, quantity, preferred warehouse or region), returns a Reservation possibly split across warehouses; idempotent on `cart_id` so retrying checkout doesn't double-reserve.
- `POST /reservations/{id}/confirm` — only succeeds if the reservation hasn't expired; converts reserved quantity to a firm deduction.
- `DELETE /reservations/{id}` — explicit release, used on cart abandonment.

## Class / Module Design
- `StockLedger` — the only module allowed to mutate `on_hand`/`reserved` on a StockRecord, using an atomic conditional update so two concurrent reservations for the last unit can't both succeed.
- `ReservationSplitter` — decides how to split a requested quantity across warehouses when no single one can cover it; operates only on `available` quantities read from `StockLedger`, never mutates directly.
- `ReservationExpiry` — background sweep releasing expired reservations back to `available`; separate from the checkout request path.

## Data Model
- `StockRecords`: composite key `(sku, warehouse_id)` → `on_hand`, `reserved`; updated only via atomic conditional writes, indexed by `sku` alone as well so `ReservationSplitter` can pull cross-warehouse availability in one query.
- `Reservations`: `id`, `cart_id` (unique — the idempotency key), `expires_at`, `status`.
- `ReservationLines`: `reservation_id`, `sku`, `warehouse_id`, `quantity` — split out from `Reservations` because one reservation can span multiple `StockRecords` across warehouses.
- `Orders` reference confirmed `Reservations` by id rather than copying quantities, so the two can never drift apart.

## Sequence Flows
- Reserve: `POST /reservations` reads `available` across candidate warehouses → `ReservationSplitter` decides the allocation → `StockLedger` applies an atomic conditional update per `StockRecord` in the split, each line tracked so a partial failure rolls back only its own line → `Reservation` + `ReservationLines` written with `expires_at` set. Synchronous end to end.
- Confirm: `POST /reservations/{id}/confirm` checks `expires_at` → each `StockRecord` line is confirmed independently and idempotently (reserved → deducted `on_hand`) → the `Order` is marked complete only once every line has confirmed, not on the first successful line.

## Edge Cases & Failure Modes
- Two checkouts race for the last unit of a SKU — `StockLedger`'s atomic conditional update guarantees only one reservation succeeds; the second gets an immediate out-of-stock response rather than a reservation that later fails to confirm.
- A reservation spans two warehouses and one warehouse's confirm succeeds while the other fails (e.g., a downstream outage) — confirmation is per-StockRecord and idempotent, so a retry only re-attempts the failed part, and the order isn't marked complete until every part confirms.
- Reservation expires right as the customer submits payment — `confirm` checks expiry at confirmation time; an expired reservation fails confirmation cleanly rather than deducting stock behind an already-lapsed hold.

## Tradeoffs
- **Chose**: atomic conditional update per StockRecord for concurrency control. **Rejected**: a lock service coordinating across all reservations for a SKU. Reason — a lock service becomes the bottleneck and single point of failure for exactly the SKUs under the most concurrent demand.
- **Chose**: per-StockRecord confirmation instead of one atomic multi-warehouse transaction. **Rejected**: distributed transaction across warehouses. Reason — warehouses are separate systems; a distributed transaction across them trades a rare partial-confirm edge case for a much larger blast radius when any one warehouse is slow.

## Testing Strategy
- Concurrency test: many simulated reservations against a StockRecord with exactly one unit available, asserting only one succeeds.
- Unit: `ReservationSplitter` against warehouse availability combinations, including cases with no valid split.
- Not covered by automation: actual physical stock accuracy (on_hand vs. what's really in the warehouse) — reconciled by a separate inventory-audit process.

## Operations
- Alert on reservation confirm failure rate per warehouse; a spike usually means that warehouse's downstream system is degraded.
- Track expired-without-confirm rate as a checkout funnel signal, not just a system metric.
- `ReservationExpiry` sweep lag is a direct driver of phantom "out of stock" — if the sweep falls behind, available inventory looks lower than it is.
