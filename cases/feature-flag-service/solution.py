"""Reference implementation for the Feature Flag Service design in README.md.

RuleEvaluator is a pure function per Class / Module Design: no I/O, so it's
exercised directly here without any snapshot-propagation machinery.
"""
from __future__ import annotations  # lets `list[TargetingRule]`-style hints work

import hashlib                                   # sha256 backs the deterministic bucketing hash
from dataclasses import dataclass                # Flag/TargetingRule are plain data holders
from typing import Any, Callable, Optional       # Any: rule values can be bool/str/whatever a flag returns


@dataclass(frozen=True)
class TargetingRule:
    name: str                       # human-readable label for logs/debugging
    matches: Callable[[dict], bool] # predicate over the evaluation context
    value: Any                      # value to return if this rule matches


@dataclass
class Flag:
    key: str                 # stable identifier services reference in code
    rules: list[TargetingRule]  # evaluated in order; first match wins
    default: Any              # returned if no rule matches


def deterministic_bucket(flag_key: str, user_id: str, buckets: int = 100) -> int:
    """Same (flag_key, user_id) always lands in the same bucket, so a user
    doesn't flip in and out of a rollout on repeated evaluations."""
    digest = hashlib.sha256(f"{flag_key}:{user_id}".encode()).hexdigest()  # stable, uniform hash of the pair
    return int(digest, 16) % buckets                                       # fold into [0, buckets)


def percentage_rule(name: str, flag_key: str, percentage: int, value: Any) -> TargetingRule:
    threshold = percentage  # e.g. 25 means buckets [0, 25) match, i.e. 25% of users
    return TargetingRule(
        name=name,
        matches=lambda ctx: deterministic_bucket(flag_key, ctx["user_id"]) < threshold,  # closes over threshold
        value=value,
    )


def attribute_rule(name: str, attribute: str, equals: Any, value: Any) -> TargetingRule:
    return TargetingRule(name=name, matches=lambda ctx: ctx.get(attribute) == equals, value=value)


class RuleEvaluator:
    """Pure function of (Flag, context) -> value. First match wins."""

    @staticmethod
    def evaluate(flag: Flag, context: dict) -> Any:
        for rule in flag.rules:       # walk rules in the order the Flag was authored
            if rule.matches(context): # first predicate that matches wins
                return rule.value
        return flag.default           # no rule matched: fall back to the flag's default


class KillSwitch:
    """Checked before RuleEvaluator per Edge Cases, so it can't race an
    in-progress rule update."""

    def __init__(self):
        self._killed: set[str] = set()  # set of flag keys currently killed

    def kill(self, flag_key: str) -> None:
        self._killed.add(flag_key)      # idempotent: killing twice is a no-op

    def is_killed(self, flag_key: str) -> bool:
        return flag_key in self._killed # O(1) membership check on the hot path


class FlagSnapshotStore:
    """Local, periodically-refreshed copy of flag definitions. evaluate()
    reads only this, never a network call, per the Tradeoffs decision."""

    def __init__(self):
        self._flags: dict[str, Flag] = {}       # flag_key -> Flag, the local snapshot
        self._kill_switch = KillSwitch()        # separate, narrow override path

    def publish(self, flag: Flag) -> None:
        self._flags[flag.key] = flag            # simulates SnapshotPublisher delivering an update

    def kill(self, flag_key: str) -> None:
        self._kill_switch.kill(flag_key)        # simulates POST /flags/{key}/kill

    def evaluate(self, flag_key: str, context: dict) -> Optional[Any]:
        if self._kill_switch.is_killed(flag_key):  # checked first: short-circuits everything else
            flag = self._flags.get(flag_key)
            return flag.default if flag else None  # safe default, even if the flag def is unknown
        flag = self._flags.get(flag_key)
        if flag is None:
            return None  # cold start: caller decides fallback, per Edge Cases
        return RuleEvaluator.evaluate(flag, context)  # normal path: delegate to the pure evaluator


if __name__ == "__main__":
    store = FlagSnapshotStore()
    store.publish(
        Flag(
            key="new-checkout",
            rules=[
                attribute_rule("internal-allowlist", "is_employee", True, True),  # employees always on
                percentage_rule("25pct-rollout", "new-checkout", 25, True),       # everyone else: 25% rollout
            ],
            default=False,  # off unless a rule above matched
        )
    )

    print("-- deterministic bucketing: same user always gets the same result --")
    for user_id in ["user-1", "user-2", "user-3", "user-4"]:
        r1 = store.evaluate("new-checkout", {"user_id": user_id, "is_employee": False})  # first evaluation
        r2 = store.evaluate("new-checkout", {"user_id": user_id, "is_employee": False})  # second, same input
        print(f"{user_id}: eval#1={r1} eval#2={r2} consistent={r1 == r2}")

    print("\n-- employee allowlist wins regardless of bucket --")
    print(store.evaluate("new-checkout", {"user_id": "user-99", "is_employee": True}))  # allowlist rule fires first

    print("\n-- cold start: flag never published to this snapshot --")
    print(store.evaluate("unpublished-flag", {"user_id": "user-1"}))  # None, not an exception

    print("\n-- kill switch short-circuits every rule --")
    store.kill("new-checkout")
    print(store.evaluate("new-checkout", {"user_id": "user-1", "is_employee": True}))  # False even for an employee
