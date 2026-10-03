from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.events.models import Event, Seat

pytestmark = pytest.mark.django_db


@pytest.fixture
def organizer() -> User:
    return User.objects.create_user("org@example.com", "pw", role=Role.ORGANIZER)


def make_event(
    organizer: User, *, name: str = "Concert", sales_open_in: int = 1, starts_in: int = 30
) -> Event:
    now = timezone.now()
    return Event.objects.create(
        organizer=organizer,
        name=name,
        venue="Main Hall",
        starts_at=now + timedelta(days=starts_in),
        sales_open_at=now + timedelta(days=sales_open_in),
    )


def make_seat(event: Event, number: int = 1, price_cents: int = 5000) -> Seat:
    return Seat.objects.create(
        event=event, section="A", row="1", number=number, price_cents=price_cents
    )


def test_event_and_seat_are_created_with_expected_defaults(organizer: User) -> None:
    event = make_event(organizer)
    seat = make_seat(event)
    assert str(event) == "Concert"
    assert str(seat) == "A-11"
    assert list(event.seats.all()) == [seat]


def test_same_seat_label_twice_in_one_event_is_rejected(organizer: User) -> None:
    event = make_event(organizer)
    make_seat(event, number=1)
    with pytest.raises(IntegrityError):
        make_seat(event, number=1)


def test_same_seat_label_is_allowed_in_a_different_event(organizer: User) -> None:
    make_seat(make_event(organizer, name="One"), number=1)
    make_seat(make_event(organizer, name="Two"), number=1)  # must not raise


def test_sales_cannot_open_after_the_event_starts(organizer: User) -> None:
    with pytest.raises(IntegrityError):
        make_event(organizer, sales_open_in=40, starts_in=30)


def test_negative_price_is_rejected_by_the_database(organizer: User) -> None:
    with pytest.raises(IntegrityError):
        make_seat(make_event(organizer), price_cents=-1)


def test_deleting_an_organizer_with_events_is_blocked(organizer: User) -> None:
    make_event(organizer)
    with pytest.raises(ProtectedError):
        organizer.delete()
