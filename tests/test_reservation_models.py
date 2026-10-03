import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.events.models import Event, Seat
from apps.reservations.models import Reservation, ReservationSeat, ReservationStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def event() -> Event:
    organizer = User.objects.create_user("org@example.com", "pw", role=Role.ORGANIZER)
    now = timezone.now()
    return Event.objects.create(
        organizer=organizer,
        name="Concert",
        venue="Main Hall",
        starts_at=now + timedelta(days=30),
        sales_open_at=now + timedelta(days=1),
    )


@pytest.fixture
def seat(event: Event) -> Seat:
    return Seat.objects.create(event=event, section="A", row="1", number=1, price_cents=5000)


def make_reservation(event: Event, email: str, status: str = "held") -> Reservation:
    user = User.objects.create_user(email, "pw")
    return Reservation.objects.create(
        user=user,
        event=event,
        status=status,
        total_cents=5000,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def claim(reservation: Reservation, seat: Seat, *, is_active: bool = True) -> ReservationSeat:
    return ReservationSeat.objects.create(
        reservation=reservation, seat=seat, price_cents=seat.price_cents, is_active=is_active
    )


def test_new_reservation_defaults_to_held_with_uuid_id(event: Event) -> None:
    reservation = make_reservation(event, "a@example.com")
    assert reservation.status == ReservationStatus.HELD
    assert isinstance(reservation.id, uuid.UUID)


def test_second_active_claim_on_the_same_seat_is_rejected(event: Event, seat: Seat) -> None:
    claim(make_reservation(event, "a@example.com"), seat)
    with pytest.raises(IntegrityError):
        claim(make_reservation(event, "b@example.com"), seat)


def test_bulk_insert_cannot_bypass_the_one_active_claim_rule(event: Event, seat: Seat) -> None:
    first = make_reservation(event, "a@example.com")
    second = make_reservation(event, "b@example.com")
    with pytest.raises(IntegrityError):
        ReservationSeat.objects.bulk_create(
            [
                ReservationSeat(reservation=first, seat=seat, price_cents=5000),
                ReservationSeat(reservation=second, seat=seat, price_cents=5000),
            ]
        )


def test_seat_can_be_rebooked_after_the_first_claim_is_released(event: Event, seat: Seat) -> None:
    first = claim(make_reservation(event, "a@example.com"), seat)
    first.is_active = False
    first.save()
    claim(make_reservation(event, "b@example.com"), seat)  # must not raise


def test_many_inactive_claims_on_one_seat_are_allowed(event: Event, seat: Seat) -> None:
    claim(make_reservation(event, "a@example.com", "expired"), seat, is_active=False)
    claim(make_reservation(event, "b@example.com", "cancelled"), seat, is_active=False)
    assert ReservationSeat.objects.filter(seat=seat, is_active=False).count() == 2


def test_same_seat_twice_in_one_reservation_is_rejected(event: Event, seat: Seat) -> None:
    reservation = make_reservation(event, "a@example.com")
    claim(reservation, seat)
    with pytest.raises(IntegrityError):
        claim(reservation, seat)


def test_unknown_status_is_rejected_by_the_database(event: Event) -> None:
    with pytest.raises(IntegrityError):
        make_reservation(event, "a@example.com", status="bogus")


def test_seat_with_booking_history_cannot_be_deleted(event: Event, seat: Seat) -> None:
    claim(make_reservation(event, "a@example.com"), seat)
    with pytest.raises(ProtectedError):
        seat.delete()
