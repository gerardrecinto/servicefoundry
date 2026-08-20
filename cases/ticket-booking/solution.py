"""Reference implementation for the Ticket Booking design in README.md.

SeatAvailability's hold() is compare-and-set on Seat status, per Class /
Module Design, so two concurrent hold requests for the same seat can't
both succeed. BookingConfirmer re-validates hold expiry at confirm time
rather than trusting the check made when the hold was created.
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass
from typing import Optional

_ids = itertools.count(1)


@dataclass
class Seat:
    id: str
    event_id: str
    status: str = "available"          # available -> held -> booked (or back to available on expiry)
    current_hold_id: Optional[int] = None


@dataclass
class Hold:
    id: int
    seat_id: str
    customer_id: str
    expires_at: float
    released: bool = False


@dataclass(frozen=True)
class Booking:
    id: int
    hold_id: int
    seat_id: str
    created_at: float


class SeatAvailability:
    """The only module that transitions Seat state. hold() is
    compare-and-set: read current status, write `held` only if it was
    `available`, in one atomic operation guarded by a single lock."""

    def __init__(self, seats: dict[str, Seat]):
        self._lock = threading.Lock()
        self._seats = seats
        self._holds: dict[int, Hold] = {}
        self._holds_by_customer_seat: dict[tuple[str, str], int] = {}  # enforces hold() idempotency

    def hold(self, seat_id: str, customer_id: str, now: float, ttl: float = 120.0) -> Optional[Hold]:
        with self._lock:
            existing_id = self._holds_by_customer_seat.get((customer_id, seat_id))
            if existing_id is not None:
                existing = self._holds[existing_id]
                if not existing.released and existing.expires_at > now:
                    return existing  # idempotent: same customer double-clicking gets the same hold back

            seat = self._seats.get(seat_id)
            if seat is None or seat.status != "available":
                return None  # compare-and-set failed: seat wasn't available, no hold created

            hold = Hold(id=next(_ids), seat_id=seat_id, customer_id=customer_id, expires_at=now + ttl)
            self._holds[hold.id] = hold
            self._holds_by_customer_seat[(customer_id, seat_id)] = hold.id
            seat.status = "held"
            seat.current_hold_id = hold.id
            return hold

    def get_hold(self, hold_id: int) -> Optional[Hold]:
        with self._lock:
            return self._holds.get(hold_id)

    def get_seat(self, seat_id: str) -> Optional[Seat]:
        with self._lock:
            return self._seats.get(seat_id)

    def mark_booked(self, hold_id: int) -> None:
        with self._lock:
            hold = self._holds[hold_id]
            seat = self._seats[hold.seat_id]
            seat.status = "booked"

    def release_expired(self, now: float) -> list[Hold]:
        """HoldExpiry's sweep: releases expired holds back to available.
        Separate from the request path so checkout latency doesn't depend
        on expiry-scanning work."""
        released = []
        with self._lock:
            for hold in self._holds.values():
                if hold.released or hold.expires_at > now:
                    continue
                seat = self._seats.get(hold.seat_id)
                if seat is not None and seat.status == "held" and seat.current_hold_id == hold.id:
                    seat.status = "available"
                    seat.current_hold_id = None
                hold.released = True
                released.append(hold)
        return released


class HoldExpiry:
    """Background sweep wrapper around SeatAvailability.release_expired,
    kept as its own class per Class / Module Design so the sweep can be
    scheduled independently of the request path."""

    def __init__(self, availability: SeatAvailability):
        self._availability = availability

    def sweep(self, now: float) -> list[Hold]:
        return self._availability.release_expired(now)


class BookingConfirmer:
    """The only module allowed to create a Booking, and only from a Hold
    it can verify is still valid at confirmation time, not at the time
    the hold was created."""

    def __init__(self, availability: SeatAvailability):
        self._availability = availability
        self._lock = threading.Lock()
        self._bookings_by_hold: dict[int, Booking] = {}

    def confirm(self, hold_id: int, now: float) -> Booking:
        with self._lock:
            existing = self._bookings_by_hold.get(hold_id)
            if existing is not None:
                return existing  # idempotent: retried confirm after a client-side timeout, no double booking

            hold = self._availability.get_hold(hold_id)
            if hold is None:
                raise ValueError(f"no such hold: {hold_id}")
            if hold.released or hold.expires_at <= now:
                raise ValueError(f"hold {hold_id} is no longer valid at confirm time")

            seat = self._availability.get_seat(hold.seat_id)
            if seat is None or seat.status != "held" or seat.current_hold_id != hold_id:
                raise ValueError(f"seat {hold.seat_id} is not held by hold {hold_id}")

            self._availability.mark_booked(hold_id)
            booking = Booking(id=next(_ids), hold_id=hold_id, seat_id=hold.seat_id, created_at=now)
            self._bookings_by_hold[hold_id] = booking
            return booking


if __name__ == "__main__":
    seats = {"A1": Seat(id="A1", event_id="show-1"), "A2": Seat(id="A2", event_id="show-1")}
    availability = SeatAvailability(seats)
    expiry = HoldExpiry(availability)
    confirmer = BookingConfirmer(availability)

    print("-- concurrent hold attempts on the same seat: exactly one wins --")
    results: list[Optional[Hold]] = [None] * 20
    barrier = threading.Barrier(20)

    def attempt(i: int) -> None:
        barrier.wait()  # line everyone up so the race is real, not just sequential calls
        results[i] = availability.hold("A1", f"customer-{i}", now=0.0)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    successes = [r for r in results if r is not None]
    print(f"20 concurrent customers, seat A1: {len(successes)} hold(s) succeeded")
    assert len(successes) == 1  # compare-and-set must let exactly one through

    print("\n-- idempotent hold: same customer double-clicks the same seat --")
    seats["A2"].status = "available"
    h1 = availability.hold("A2", "customer-x", now=0.0)
    h2 = availability.hold("A2", "customer-x", now=1.0)
    print(f"first hold id={h1.id}, second hold id={h2.id}, same_hold={h1.id == h2.id}")
    assert h1.id == h2.id

    print("\n-- confirm succeeds on a valid hold, and is idempotent on retry --")
    booking1 = confirmer.confirm(h1.id, now=2.0)
    booking2 = confirmer.confirm(h1.id, now=2.5)  # simulates a client retry after a timed-out response
    print(f"booking id={booking1.id}, seat A2 status={seats['A2'].status}, retry_returned_same={booking1.id == booking2.id}")
    assert booking1.id == booking2.id

    print("\n-- hold expires before confirm: seat is swept back to available, confirm rejects it --")
    seats["A1"] = Seat(id="A1", event_id="show-1")  # fresh seat; `seats` is the same dict SeatAvailability holds
    stale_hold = availability.hold("A1", "customer-slow", now=0.0, ttl=5.0)
    swept = expiry.sweep(now=10.0)  # well past the 5s ttl
    print(f"seat A1 status after sweep={seats['A1'].status}, holds released={len(swept)}")
    try:
        confirmer.confirm(stale_hold.id, now=10.0)
        raise AssertionError("expected confirm on an expired hold to raise")
    except ValueError as e:
        print(f"confirm correctly rejected the expired hold: {e}")
