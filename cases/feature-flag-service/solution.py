"""Reference implementation for the Feature Flag Service design in README.md.

RuleEvaluator is a pure function per Class / Module Design: no I/O, so it's
exercised directly here without any snapshot-propagation machinery.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class TargetingRule:
    name: str
    matches: Callable[[dict], bool]
    value: Any


@dataclass
class Flag:
    key: str
    rules: list[TargetingRule]
    default: Any


def deterministic_bucket(flag_key: str, user_id: str, buckets: int = 100) -> int:
    """Same (flag_key, user_id) always lands in the same bucket, so a user
    doesn't flip in and out of a rollout on repeated evaluations."""
    digest = hashlib.sha256(f"{flag_key}:{user_id}".encode()).hexdigest()
    return int(digest, 16) % buckets


def percentage_rule(name: str, flag_key: str, percentage: int, value: Any) -> TargetingRule:
    threshold = percentage
    return TargetingRule(
        name=name,
        matches=lambda ctx: deterministic_bucket(flag_key, ctx["user_id"]) < threshold,
        value=value,
    )


def attribute_rule(name: str, attribute: str, equals: Any, value: Any) -> TargetingRule:
    return TargetingRule(name=name, matches=lambda ctx: ctx.get(attribute) == equals, value=value)


class RuleEvaluator:
    """Pure function of (Flag, context) -> value. First match wins."""

    @staticmethod
    def evaluate(flag: Flag, context: dict) -> Any:
        for rule in flag.rules:
            if rule.matches(context):
                return rule.value
        return flag.default


class KillSwitch:
    """Checked before RuleEvaluator per Edge Cases, so it can't race an
    in-progress rule update."""

    def __init__(self):
        self._killed: set[str] = set()

    def kill(self, flag_key: str) -> None:
        self._killed.add(flag_key)

    def is_killed(self, flag_key: str) -> bool:
        return flag_key in self._killed


class FlagSnapshotStore:
    """Local, periodically-refreshed copy of flag definitions. evaluate()
    reads only this, never a network call, per the Tradeoffs decision."""

    def __init__(self):
        self._flags: dict[str, Flag] = {}
        self._kill_switch = KillSwitch()

    def publish(self, flag: Flag) -> None:
        self._flags[flag.key] = flag

    def kill(self, flag_key: str) -> None:
        self._kill_switch.kill(flag_key)

    def evaluate(self, flag_key: str, context: dict) -> Optional[Any]:
        if self._kill_switch.is_killed(flag_key):
            flag = self._flags.get(flag_key)
            return flag.default if flag else None
        flag = self._flags.get(flag_key)
        if flag is None:
            return None  # cold start: caller decides fallback, per Edge Cases
        return RuleEvaluator.evaluate(flag, context)


if __name__ == "__main__":
    store = FlagSnapshotStore()
    store.publish(
        Flag(
            key="new-checkout",
            rules=[
                attribute_rule("internal-allowlist", "is_employee", True, True),
                percentage_rule("25pct-rollout", "new-checkout", 25, True),
            ],
            default=False,
        )
    )

    print("-- deterministic bucketing: same user always gets the same result --")
    for user_id in ["user-1", "user-2", "user-3", "user-4"]:
        r1 = store.evaluate("new-checkout", {"user_id": user_id, "is_employee": False})
        r2 = store.evaluate("new-checkout", {"user_id": user_id, "is_employee": False})
        print(f"{user_id}: eval#1={r1} eval#2={r2} consistent={r1 == r2}")

    print("\n-- employee allowlist wins regardless of bucket --")
    print(store.evaluate("new-checkout", {"user_id": "user-99", "is_employee": True}))

    print("\n-- cold start: flag never published to this snapshot --")
    print(store.evaluate("unpublished-flag", {"user_id": "user-1"}))

    print("\n-- kill switch short-circuits every rule --")
    store.kill("new-checkout")
    print(store.evaluate("new-checkout", {"user_id": "user-1", "is_employee": True}))
