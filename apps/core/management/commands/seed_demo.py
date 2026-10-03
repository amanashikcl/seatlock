"""Create (or top up) demo accounts and an event with seats, for manual testing and load tests."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.events.models import Event, Seat

DEMO_PASSWORD = "Demo-pass-12345!"  # noqa: S105 - throwaway value for local demo data only
ORGANIZER_EMAIL = "demo-org@example.com"
BUYER_EMAIL = "demo-buyer@example.com"
EVENT_NAME = "Demo concert"


class Command(BaseCommand):
    help = "Create demo accounts and an on-sale event with seats. Safe to run repeatedly."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--seats", type=int, default=5, help="total seats for the event")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            # Known passwords must never be created outside a development environment.
            raise CommandError("seed_demo only runs with DEBUG=True (development settings).")
        now = timezone.now()
        organizer = self._user(ORGANIZER_EMAIL, Role.ORGANIZER)
        self._user(BUYER_EMAIL, Role.CUSTOMER)
        event, _ = Event.objects.get_or_create(
            organizer=organizer,
            name=EVENT_NAME,
            defaults={
                "venue": "Main Hall",
                "starts_at": now + timedelta(days=30),
                "sales_open_at": now - timedelta(hours=1),
            },
        )
        for number in range(event.seats.count() + 1, options["seats"] + 1):
            Seat.objects.create(event=event, section="A", row="1", number=number, price_cents=5000)
        self.stdout.write(f"event id: {event.id}, seats: {event.seats.count()}")

    @staticmethod
    def _user(email: str, role: str) -> User:
        user = User.objects.filter(email=email).first()
        return user or User.objects.create_user(email, DEMO_PASSWORD, role=role)
