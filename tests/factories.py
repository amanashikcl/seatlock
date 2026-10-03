"""Small helpers for building test data."""

from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.events.models import Event, Seat


def make_user(n: int) -> User:
    return User.objects.create_user(f"buyer{n}@example.com", "pw")


def make_event(organizer_email: str = "org@example.com") -> Event:
    """An event whose sales window is currently open."""
    organizer = User.objects.create_user(organizer_email, "pw", role=Role.ORGANIZER)
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
