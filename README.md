# ServiceFoundry

Design production-ready services from messy product requirements.

ServiceFoundry is a practical design workbench for turning ambiguous product requirements into production-ready service designs. It's built for engineers who want to practice real-world backend design: domain modeling, APIs, object responsibilities, data consistency, edge cases, testing, and operational readiness.

Each case in `cases/` starts from a vague one-paragraph product ask and works through to:

- a domain model (entities, relationships, ownership of state)
- an API contract (operations, idempotency, error semantics)
- class/module responsibilities and boundaries
- a data model
- edge cases and failure modes
- tradeoffs considered and rejected, with reasoning
- a testing strategy
- operational notes (observability, scaling, rollout)

## Structure

- `cases/` — worked design case studies, one per service
- `templates/` — the reusable section templates every case follows
- `docs/design-playbook.md` — the step-by-step method used across cases
- `docs/design-rubric.md` — a checklist for grading a design write-up
- `docs/case-lld-oop-map.md` — quick map from each case to LLD, OOP, SOLID, and clean-code concepts
- `docs/adr/` — architecture decision records for choices made in this repo itself

## Cases

| Case | Focus |
|---|---|
| [locker-service](cases/locker-service) | reservations, expiration, access codes, capacity |
| [parking-garage](cases/parking-garage) | pricing, ticketing, sensors, payments |
| [package-delivery](cases/package-delivery) | routing, driver assignment, package state, retries |
| [rate-limiter](cases/rate-limiter) | token bucket, distributed limits, backpressure |
| [ticket-booking](cases/ticket-booking) | seat holds, concurrency, overselling prevention |
| [notification-platform](cases/notification-platform) | multi-channel delivery, templates, retries, idempotency |
| [inventory-reservation](cases/inventory-reservation) | stock holds, checkout, cancellation, concurrency |
| [ride-dispatch](cases/ride-dispatch) | matching, driver state machine, location ingest |
| [file-sync](cases/file-sync) | conflict resolution, versioning, offline writes |
| [feature-flag-service](cases/feature-flag-service) | targeting rules, evaluation, caching, safe rollout |

## Using a template for a new case

Copy `templates/*.md` into a new folder under `cases/<name>/`, or write a single `README.md` following the same section order. Start from a one-paragraph, intentionally vague product ask and work outward — the value is in resolving the ambiguity, not in the diagram.

## License

MIT — see [LICENSE](LICENSE).
