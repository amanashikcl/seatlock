"""Create a fresh event with many seats for a load test. Safe to run in any environment.

Unlike seed_demo it creates NO login credentials: the organizer account has an unusable
password, and load-test buyers register themselves through the public API. That is why this
command may run inside the production-settings container.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.events.models import Event, Seat

ORGANIZER_EMAIL = "loadtest-org@example.com"


class Command(BaseCommand):
    help = "Create a new on-sale 'Load test' event with N seats and print its id."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--seats", type=int, default=200)

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        organizer = User.objects.filter(email=ORGANIZER_EMAIL).first()
        if organizer is None:
            organizer = User.objects.create_user(ORGANIZER_EMAIL, None, role=Role.ORGANIZER)
            organizer.set_unusable_password()
            organizer.save(update_fields=["password"])
        # A new event every run, so holds left by an earlier run cannot skew this one.
        event = Event.objects.create(
            organizer=organizer,
            name=f"Load test {now:%Y-%m-%d %H:%M:%S}",
            venue="Benchmark Arena",
            starts_at=now + timedelta(days=30),
            sales_open_at=now - timedelta(hours=1),
        )
        Seat.objects.bulk_create(
            Seat(event=event, section="A", row="1", number=n, price_cents=5000)
            for n in range(1, options["seats"] + 1)
        )
        self.stdout.write(f"event id: {event.id}, seats: {options['seats']}")
