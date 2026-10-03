import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connections
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.events.models import Event, Seat
from apps.reservations.models import Reservation, ReservationSeat, ReservationStatus
from apps.reservations.services import (
    HOLD_DURATION,
    MAX_SEATS_PER_RESERVATION,
    InvalidSeatSelection,
    SalesNotOpen,
    SeatUnavailable,
    hold_seats,
)


@pytest.fixture
def event() -> Event:
    organizer = User.objects.create_user("org@example.com", "pw", role=Role.ORGANIZER)
    now = timezone.now()
    return Event.objects.create(
        organizer=organizer,
        name="Concert",
        venue="Main Hall",
        starts_at=now + timedelta(days=30),
        sales_open_at=now - timedelta(hours=1),
    )


def make_seats(event: Event, count: int) -> list[Seat]:
    return [
        Seat.objects.create(event=event, section="A", row="1", number=i + 1, price_cents=5000)
        for i in range(count)
    ]


def make_user(n: int) -> User:
    return User.objects.create_user(f"buyer{n}@example.com", "pw")


@pytest.mark.django_db
def test_hold_creates_a_held_reservation_with_active_items(event: Event) -> None:
    seats = make_seats(event, 2)
    now = timezone.now()
    reservation = hold_seats(
        user=make_user(1), event=event, seat_ids=[s.id for s in seats], now=now
    )
    assert reservation.status == ReservationStatus.HELD
    assert reservation.expires_at == now + HOLD_DURATION
    assert reservation.total_cents == 10000
    assert reservation.items.filter(is_active=True).count() == 2


@pytest.mark.django_db
def test_duplicate_seat_ids_are_collapsed(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    reservation = hold_seats(user=make_user(1), event=event, seat_ids=[seat.id, seat.id])
    assert reservation.items.count() == 1


@pytest.mark.django_db
def test_a_held_seat_cannot_be_held_again(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    hold_seats(user=make_user(1), event=event, seat_ids=[seat.id])
    with pytest.raises(SeatUnavailable) as excinfo:
        hold_seats(user=make_user(2), event=event, seat_ids=[seat.id])
    assert excinfo.value.seat_ids == [seat.id]
    assert Reservation.objects.count() == 1


@pytest.mark.django_db
def test_hold_is_all_or_nothing(event: Event) -> None:
    taken, free = make_seats(event, 2)
    hold_seats(user=make_user(1), event=event, seat_ids=[taken.id])
    with pytest.raises(SeatUnavailable):
        hold_seats(user=make_user(2), event=event, seat_ids=[taken.id, free.id])
    assert not ReservationSeat.objects.filter(seat=free).exists()


@pytest.mark.django_db
def test_seat_from_another_event_is_rejected(event: Event) -> None:
    now = timezone.now()
    other = Event.objects.create(
        organizer=event.organizer,
        name="Other",
        venue="Elsewhere",
        starts_at=now + timedelta(days=30),
        sales_open_at=now - timedelta(hours=1),
    )
    (foreign_seat,) = make_seats(other, 1)
    with pytest.raises(InvalidSeatSelection):
        hold_seats(user=make_user(1), event=event, seat_ids=[foreign_seat.id])


@pytest.mark.django_db
def test_empty_and_oversized_selections_are_rejected(event: Event) -> None:
    user = make_user(1)
    with pytest.raises(InvalidSeatSelection):
        hold_seats(user=user, event=event, seat_ids=[])
    too_many = list(range(1, MAX_SEATS_PER_RESERVATION + 2))
    with pytest.raises(InvalidSeatSelection):
        hold_seats(user=user, event=event, seat_ids=too_many)


@pytest.mark.django_db
def test_cannot_hold_before_sales_open_or_after_the_event_starts(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    user = make_user(1)
    early = event.sales_open_at - timedelta(minutes=1)
    late = event.starts_at + timedelta(minutes=1)
    with pytest.raises(SalesNotOpen):
        hold_seats(user=user, event=event, seat_ids=[seat.id], now=early)
    with pytest.raises(SalesNotOpen):
        hold_seats(user=user, event=event, seat_ids=[seat.id], now=late)


def race(event: Event, users: Sequence[User], seat_orders: Sequence[Sequence[int]]) -> list[str]:
    """Run one hold attempt per user in its own thread, all released at the same instant."""
    barrier = threading.Barrier(len(users), timeout=30)

    def attempt(user: User, seat_ids: Sequence[int]) -> str:
        try:
            barrier.wait()
            hold_seats(user=user, event=event, seat_ids=seat_ids)
            return "won"
        except SeatUnavailable:
            return "lost"
        finally:
            connections.close_all()  # each thread opened its own DB connection

    with ThreadPoolExecutor(max_workers=len(users)) as pool:
        return list(pool.map(attempt, users, seat_orders))


@pytest.mark.django_db(transaction=True)
def test_exactly_one_of_twenty_simultaneous_buyers_gets_the_seat(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    users = [make_user(n) for n in range(20)]
    results = race(event, users, [[seat.id]] * len(users))
    assert results.count("won") == 1
    assert results.count("lost") == 19
    assert ReservationSeat.objects.filter(seat=seat, is_active=True).count() == 1


@pytest.mark.django_db(transaction=True)
def test_opposite_seat_orders_do_not_deadlock_and_one_buyer_wins_both(event: Event) -> None:
    first, second = make_seats(event, 2)
    users = [make_user(n) for n in range(10)]
    orders = [[first.id, second.id] if n % 2 == 0 else [second.id, first.id] for n in range(10)]
    results = race(event, users, orders)
    assert results.count("won") == 1
    assert results.count("lost") == 9
    active = ReservationSeat.objects.filter(is_active=True)
    assert active.count() == 2
    assert active.values("reservation_id").distinct().count() == 1  # both seats, same buyer
