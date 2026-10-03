"""Booking use-cases. No HTTP in here: callers (API views, workers) map exceptions themselves."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event, Seat
from apps.reservations.models import Reservation, ReservationSeat, ReservationStatus

HOLD_DURATION = timedelta(minutes=10)
MAX_SEATS_PER_RESERVATION = 6


class ReservationError(Exception):
    """Base class for expected booking failures."""


class InvalidSeatSelection(ReservationError):
    """Empty/oversized selection, or seats that do not belong to the event."""


class SalesNotOpen(ReservationError):
    """The event is not currently on sale."""


class SeatUnavailable(ReservationError):
    """At least one requested seat is already claimed."""

    def __init__(self, seat_ids: Sequence[int]) -> None:
        super().__init__(f"Seats unavailable: {list(seat_ids)}")
        self.seat_ids = list(seat_ids)


@transaction.atomic
def hold_seats(
    *,
    user: User,
    event: Event,
    seat_ids: Sequence[int],
    now: datetime | None = None,
) -> Reservation:
    """Hold seats for `user` for HOLD_DURATION, all or nothing.

    Pessimistic locking: lock the seat rows (in ascending id order so two buyers wanting the
    same seats in opposite orders cannot deadlock), then check availability. A competing
    request blocks on the lock and, once it proceeds, sees our committed claim.
    The partial unique index remains the final backstop.
    """
    now = now or timezone.now()
    if not event.sales_open_at <= now < event.starts_at:
        raise SalesNotOpen("Tickets for this event are not on sale")

    ids = sorted(set(seat_ids))
    if not ids or len(ids) > MAX_SEATS_PER_RESERVATION:
        raise InvalidSeatSelection(f"Choose between 1 and {MAX_SEATS_PER_RESERVATION} seats")

    seats = list(Seat.objects.select_for_update().filter(event=event, id__in=ids).order_by("id"))
    if len(seats) != len(ids):  # unknown id, or a seat from another event
        raise InvalidSeatSelection("Some seats do not exist for this event")

    taken = sorted(
        ReservationSeat.objects.filter(seat_id__in=ids, is_active=True).values_list(
            "seat_id", flat=True
        )
    )
    if taken:
        raise SeatUnavailable(taken)

    reservation = Reservation.objects.create(
        user=user,
        event=event,
        status=ReservationStatus.HELD,
        total_cents=sum(seat.price_cents for seat in seats),
        expires_at=now + HOLD_DURATION,
    )
    try:
        with transaction.atomic():  # savepoint, so catching the error keeps the outer txn usable
            ReservationSeat.objects.bulk_create(
                [
                    ReservationSeat(
                        reservation=reservation, seat=seat, price_cents=seat.price_cents
                    )
                    for seat in seats
                ]
            )
    except IntegrityError as exc:  # backstop: the DB refused a second active claim
        raise SeatUnavailable(ids) from exc
    return reservation
