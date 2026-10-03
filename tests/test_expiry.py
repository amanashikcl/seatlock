import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connections
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event
from apps.reservations.expiry import expire_holds
from apps.reservations.models import Reservation, ReservationStatus
from apps.reservations.services import hold_seats
from tests.factories import make_event, make_seats, make_user


@pytest.fixture
def event() -> Event:
    return make_event()


def hold_that_already_lapsed(event: Event, user: User, seat_ids: Sequence[int]) -> Reservation:
    """A hold placed 20 minutes ago: its 10-minute window ended 10 minutes ago."""
    placed_at = timezone.now() - timedelta(minutes=20)
    return hold_seats(user=user, event=event, seat_ids=seat_ids, now=placed_at)


@pytest.mark.django_db
def test_lapsed_hold_is_expired_and_its_seats_are_released(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    reservation = hold_that_already_lapsed(event, make_user(1), [seat.id])
    assert expire_holds() == 1
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.EXPIRED
    assert reservation.items.filter(is_active=True).count() == 0


@pytest.mark.django_db
def test_live_hold_is_left_alone(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    reservation = hold_seats(user=make_user(1), event=event, seat_ids=[seat.id])
    assert expire_holds() == 0
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.HELD
    assert reservation.items.filter(is_active=True).count() == 1


@pytest.mark.django_db
def test_confirmed_reservation_is_never_expired(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    reservation = hold_that_already_lapsed(event, make_user(1), [seat.id])
    Reservation.objects.filter(id=reservation.id).update(status=ReservationStatus.CONFIRMED)
    assert expire_holds() == 0
    assert reservation.items.filter(is_active=True).count() == 1


@pytest.mark.django_db
def test_seat_can_be_held_again_after_its_hold_expires(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    hold_that_already_lapsed(event, make_user(1), [seat.id])
    expire_holds()
    hold_seats(user=make_user(2), event=event, seat_ids=[seat.id])  # must not raise


@pytest.mark.django_db
def test_batch_size_limits_work_per_run_and_runs_are_idempotent(event: Event) -> None:
    seats = make_seats(event, 3)
    for n, seat in enumerate(seats):
        hold_that_already_lapsed(event, make_user(n), [seat.id])
    assert expire_holds(batch_size=2) == 2
    assert expire_holds(batch_size=2) == 1
    assert expire_holds(batch_size=2) == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_sweepers_never_expire_the_same_hold_twice(event: Event) -> None:
    seats = make_seats(event, 10)
    for n, seat in enumerate(seats):
        hold_that_already_lapsed(event, make_user(n), [seat.id])
    barrier = threading.Barrier(4, timeout=30)

    def sweep() -> int:
        try:
            barrier.wait()
            return expire_holds()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(lambda _: sweep(), range(4)))
    assert sum(counts) == 10  # every hold expired exactly once across all sweepers
    assert Reservation.objects.filter(status=ReservationStatus.EXPIRED).count() == 10
