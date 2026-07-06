"""Reference implementation for the File Sync Service design in README.md.

VersionStore's append is atomic on "does this upload's parent equal current
latest," per Edge Cases, which is what routes a stale-parent upload into
conflict handling instead of racing unpredictably.
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Optional


_ids = itertools.count(1)


@dataclass
class FileVersion:
    id: int
    file_id: str
    parent_version_id: Optional[int]
    content: str
    device_id: str


@dataclass
class Conflict:
    id: int
    file_id: str
    losing_version: FileVersion
    winning_version_id: int
    resolved: bool = False


class VersionStore:
    """Append-only. Never deletes history, so a conflict is always
    resolvable against the true divergence point."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latest: dict[str, int] = {}
        self._versions: dict[int, FileVersion] = {}
        self._history: dict[str, list[FileVersion]] = {}

    def append(self, file_id: str, parent_version_id: Optional[int], content: str, device_id: str):
        with self._lock:
            current_latest = self._latest.get(file_id)
            if parent_version_id != current_latest:
                stale = FileVersion(next(_ids), file_id, parent_version_id, content, device_id)
                return None, stale  # signals a conflict to the caller
            version = FileVersion(next(_ids), file_id, parent_version_id, content, device_id)
            self._versions[version.id] = version
            self._latest[file_id] = version.id
            self._history.setdefault(file_id, []).append(version)
            return version, None

    def since(self, file_id: str, cursor: Optional[int]) -> list[FileVersion]:
        history = self._history.get(file_id, [])
        if cursor is None:
            return list(history)
        return [v for v in history if v.id > cursor]

    def latest_id(self, file_id: str) -> Optional[int]:
        return self._latest.get(file_id)


class SyncCursorTracker:
    def __init__(self):
        self._cursors: dict[tuple[str, str], int] = {}

    def cursor(self, device_id: str, file_id: str) -> Optional[int]:
        return self._cursors.get((device_id, file_id))

    def advance(self, device_id: str, file_id: str, version_id: int) -> None:
        self._cursors[(device_id, file_id)] = version_id


class ConflictDetector:
    def __init__(self, store: VersionStore):
        self._store = store
        self._conflicts: dict[int, Conflict] = {}

    def upload(self, file_id: str, parent_version_id: Optional[int], content: str, device_id: str):
        version, stale = self._store.append(file_id, parent_version_id, content, device_id)
        if version is not None:
            return version, None
        conflict = Conflict(next(_ids), file_id, stale, self._store.latest_id(file_id))
        self._conflicts[conflict.id] = conflict
        return None, conflict

    def resolve(self, conflict_id: int, resolution: str) -> str:
        """Applies a resolution; 'keep_both' creates a new File id rather
        than attempting a content merge, per Tradeoffs."""
        conflict = self._conflicts[conflict_id]
        conflict.resolved = True
        if resolution == "keep_theirs":
            return f"file {conflict.file_id} unchanged, kept version {conflict.winning_version_id}"
        if resolution == "keep_mine":
            new_version, _ = self._store.append(
                conflict.file_id, conflict.winning_version_id, conflict.losing_version.content,
                conflict.losing_version.device_id,
            )
            return f"file {conflict.file_id} updated to version {new_version.id}"
        if resolution == "keep_both":
            new_file_id = f"{conflict.file_id}-copy-{conflict.id}"
            new_version, _ = self._store.append(
                new_file_id, None, conflict.losing_version.content, conflict.losing_version.device_id
            )
            return f"created new file {new_file_id} at version {new_version.id}"
        raise ValueError(f"unknown resolution: {resolution}")


if __name__ == "__main__":
    store = VersionStore()
    conflicts = ConflictDetector(store)
    cursors = SyncCursorTracker()

    v1, _ = conflicts.upload("doc-1", None, "hello", "device-a")
    cursors.advance("device-a", "doc-1", v1.id)
    print(f"device-a created doc-1 v{v1.id}")

    print("\n-- device-b pulls since its (empty) cursor to catch up --")
    for v in store.since("doc-1", cursors.cursor("device-b", "doc-1")):
        print(f"device-b pulls v{v.id}: {v.content!r}")
    cursors.advance("device-b", "doc-1", v1.id)

    print("\n-- device-a edits normally --")
    v2, _ = conflicts.upload("doc-1", v1.id, "hello world", "device-a")
    print(f"device-a advanced doc-1 to v{v2.id}")

    print("\n-- device-b edits against its stale cursor (v1), creating a conflict --")
    version, conflict = conflicts.upload("doc-1", v1.id, "hello there", "device-b")
    assert version is None and conflict is not None
    print(f"conflict {conflict.id}: device-b's edit was based on v{v1.id}, current latest is v{v2.id}")

    print("\n-- user resolves as keep_both --")
    print(conflicts.resolve(conflict.id, "keep_both"))
