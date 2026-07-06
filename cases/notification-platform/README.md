# Notification Platform

## Problem
Multiple internal services need to send email, SMS, and push notifications to users through a template, without each service reimplementing retries, provider failover, and rate limits against the same user.

## Requirements

### Functional
- Accept a notification request (template id, recipient, variables, channel preference).
- Render the template and send through the appropriate provider for the channel.
- Retry on transient provider failure; fail over to a backup provider per channel if the primary is down.
- Respect a user's opted-out channels.

### Non-functional
- A calling service should get an immediate accepted/rejected response; actual delivery is asynchronous.
- Must not double-send if the calling service retries its request.

### Out of scope
- Template authoring UI.
- Marketing campaign scheduling.

## Domain Model
- **NotificationRequest** — the inbound ask: template, recipient, variables, requested channel(s); has a client-supplied idempotency key.
- **Template** — versioned content per channel; a request references a template id, not raw content.
- **DeliveryAttempt** — one try through one provider for one channel; a NotificationRequest can spawn several across retries/failover.
- **RecipientPreference** — per-user opt-outs per channel, checked before any DeliveryAttempt is created.

## API Design
- `POST /notifications` — idempotent on the caller-supplied key; a retried request with the same key returns the original request's status rather than sending again.
- `GET /notifications/{id}` — status for the calling service to poll if needed, though most integrate via webhook/event instead.
- Rendering and provider selection are internal; callers never choose a provider directly, only a channel.

## Class / Module Design
- `TemplateRenderer` — pure function of (Template, variables) → content; no knowledge of providers or delivery.
- `ProviderRouter` — picks primary/backup provider per channel and handles failover; the only module that knows provider-specific APIs.
- `PreferenceGate` — checks RecipientPreference before a DeliveryAttempt is created; sits upstream of `ProviderRouter` so an opted-out user never reaches a provider call at all.
- `RetryScheduler` — owns backoff timing for transient failures; decoupled from `ProviderRouter` so retry policy can change without touching provider integration code.

## Data Model
- `NotificationRequests`: `id`, `idempotency_key` (unique), `template_id`, `recipient`, `variables` (JSON), `status`.
- `DeliveryAttempts`: `id`, `request_id`, `channel`, `provider`, `attempt_number`, `outcome`, `attempted_at` — one-to-many off `NotificationRequests`, indexed on `request_id` for status lookups.
- `RecipientPreferences`: `(user_id, channel)` → `opted_out` — read at acceptance and again immediately before each `DeliveryAttempt`.
- `Templates`: versioned rows keyed `(template_id, version)`; a request stores the resolved version it actually rendered with, which is what makes a bad render traceable to a specific version (see Operations).

## Sequence Flows
- Accept: `POST /notifications` checked against `idempotency_key` (returns the existing request if seen) → `TemplateRenderer` validates variables synchronously, failing fast on a mismatch → `NotificationRequest` persisted and an accepted response returned immediately, before any send happens.
- Deliver (async): `PreferenceGate` checked → `ProviderRouter` selects a provider → `DeliveryAttempt` created and sent → on transient failure, `RetryScheduler` schedules a retry with backoff, re-checking `PreferenceGate` again before each re-attempt.

## Edge Cases & Failure Modes
- Calling service retries `POST /notifications` after a network timeout — idempotency key ensures one send, not one per retry.
- Primary provider for a channel is degraded but not fully down (elevated latency, some failures) — `ProviderRouter` fails over based on an error-rate threshold over a rolling window, not on a single failure, to avoid flapping between providers on one bad response.
- Template variables don't match what the template expects — `TemplateRenderer` fails the request synchronously at acceptance time, before any DeliveryAttempt exists, since a rendering failure is a caller bug, not a delivery problem.
- User opts out between request acceptance and actual send — `PreferenceGate` is checked again immediately before each DeliveryAttempt, not only at acceptance, since the gap can be minutes for a busy queue.

## Tradeoffs
- **Chose**: async delivery with sync acceptance. **Rejected**: fully synchronous send-and-confirm. Reason — provider latency and retries would otherwise make every caller's request as slow as the flakiest downstream provider.
- **Chose**: rolling error-rate threshold for failover. **Rejected**: failover on first error. Reason — single transient errors are common and failing over on one would cause constant provider flapping under normal noise.

## Testing Strategy
- Unit: `TemplateRenderer` against missing/extra variables, malformed templates.
- Contract: `ProviderRouter` against fake providers simulating degraded-but-not-down behavior, verifying the threshold-based failover.
- Not covered by automation: actual deliverability/spam-filtering behavior of real providers — monitored in production, not testable synthetically.

## Operations
- Track delivery latency and failure rate per provider per channel; a provider trending worse than its failover partner should prompt a manual weight change, not wait for the threshold alone.
- Idempotency-key collision rate is a proxy for how often calling services are retrying, useful for finding upstream reliability issues in other services.
- Rollback for a bad `TemplateRenderer` deploy: templates are versioned, so a bad render can be traced to a specific template version.
