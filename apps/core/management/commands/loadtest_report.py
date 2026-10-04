"""After a load test: print what the database holds and fail loudly if any invariant broke."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.reservations.models import Reservation, ReservationSeat, ReservationStatus

LIVE = [ReservationStatus.HELD, ReservationStatus.CONFIRMED]


class Command(BaseCommand):
    help = "Check double-booking invariants for one event and print the headline numbers."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("event_id", type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        event_id = options["event_id"]
        claims = ReservationSeat.objects.filter(reservation__event_id=event_id, is_active=True)
        active = claims.count()
        distinct = claims.values("seat_id").distinct().count()
        in_live_reservations = ReservationSeat.objects.filter(
            reservation__event_id=event_id, reservation__status__in=LIVE
        ).count()
        held = Reservation.objects.filter(event_id=event_id, status=ReservationStatus.HELD).count()

        self.stdout.write(f"held reservations (successful holds): {held}")
        self.stdout.write(f"active seat claims: {active}")
        self.stdout.write(f"distinct seats with an active claim: {distinct}")

        if active != distinct:
            raise CommandError("DOUBLE BOOKING: a seat has more than one active claim")
        if active != in_live_reservations:
            raise CommandError("INCONSISTENT: active claims differ from live reservations' seats")
        self.stdout.write(self.style.SUCCESS("invariants hold: no double booking"))
