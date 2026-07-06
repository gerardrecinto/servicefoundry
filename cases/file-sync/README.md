# File Sync Service

## Problem
A file storage product needs to sync files across a user's devices, some of which are offline for extended periods, and resolve conflicts when the same file is edited on two devices before either has synced.

## Requirements

### Functional
- Upload a file version from a device and propagate it to the user's other devices.
- Detect when two devices have diverged edits to the same file and resolve or surface the conflict.
- Support a device coming back online after being offline for days and catching up.

### Non-functional
- Must not silently lose a user's edit in a conflict — data loss is worse than an annoying conflict prompt.
- Sync should be incremental; a device shouldn't have to re-download an entire file for a small edit if avoidable.

### Out of scope
- Real-time collaborative co-editing (multiple people editing simultaneously within the same session).
- File storage backend/CDN details.

## Domain Model
- **File** — has a current version chain; identified by a stable id independent of its path (renames don't create a new File).
- **FileVersion** — an immutable snapshot with a parent version reference, forming a version history per File.
- **Device** — tracks, per File, the last version it has synced (its "sync cursor").
- **Conflict** — created when a Device uploads a FileVersion whose parent isn't the File's current latest version, i.e., it was edited against a stale base.

## API Design
- `POST /files/{id}/versions` — device uploads a new version with its parent version id; idempotent on `(device_id, device_local_version_id)`.
- `GET /files/{id}/versions?since={cursor}` — device pulls versions newer than its cursor; the primary catch-up mechanism for a device coming back online.
- `POST /conflicts/{id}/resolve` — user or client-side merge logic picks a resolution (keep mine, keep theirs, keep both as separate files).

## Class / Module Design
- `VersionStore` — appends FileVersions and answers "since cursor" queries; never deletes history, so any conflict is always resolvable against the true divergence point.
- `ConflictDetector` — the only module that decides a new upload's parent doesn't match current latest, and creates a Conflict instead of accepting the upload as the new latest.
- `SyncCursorTracker` — per-device bookkeeping of what's been pulled; decoupled from `VersionStore` so a device's catch-up progress doesn't affect other devices' view of the version chain.
- `ConflictResolver` — applies a resolution decision; for "keep both," it creates a new File rather than trying to merge content the service doesn't understand.

## Edge Cases & Failure Modes
- Device uploads based on a stale parent because it was offline during someone else's edit — `ConflictDetector` catches this by parent-version mismatch, not by comparing content, so it works the same regardless of file type.
- Two devices come online and both try to push conflicting versions at nearly the same time — `VersionStore`'s append is atomic on "does this upload's parent equal current latest," so only one can land as the new latest; the second is deterministically routed into conflict handling, not a race with an unpredictable winner.
- Device has been offline so long that pulling "since cursor" would mean downloading an enormous number of intermediate versions — `VersionStore` supports pulling just the latest version plus a delta/checksum against the device's last known version, rather than the full intermediate history, when the gap exceeds a threshold.
- User picks "keep both" on a conflict, then does it again on the resulting duplicate — each resolution is independent and only ever looks at the specific Conflict record's two versions, so repeated splits don't compound into confusing state.

## Tradeoffs
- **Chose**: parent-version mismatch as the conflict signal. **Rejected**: content diffing/three-way merge for all file types. Reason — this service handles arbitrary file types, not just text; a merge strategy that only works for text would be inconsistent and surprising for other formats.
- **Chose**: immutable append-only version history. **Rejected**: overwriting the latest version in place. Reason — an in-place model can't reconstruct what a stale device's edit was actually based on, which is exactly the information needed to detect and explain a conflict.

## Testing Strategy
- Unit: `ConflictDetector` against parent-mismatch scenarios, including the exact-tie race between two near-simultaneous uploads.
- Integration: a simulated long-offline device performing catch-up via the delta path instead of full history replay.
- Not covered by automation: actual file content merge quality for "keep both" scenarios — this service intentionally never merges content, so there's nothing to test there.

## Operations
- Track conflict rate per user/file; a user with unusually high conflict rate may have a client-side sync bug worth investigating, not just bad luck.
- Alert on `VersionStore` append latency, since every sync operation funnels through it.
- Catch-up delta usage rate (vs. full history pulls) is a signal for whether the offline-gap threshold is tuned correctly.
