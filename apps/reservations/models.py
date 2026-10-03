from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.events.models import Event, Seat


class ReservationStatus(models.TextChoices):
    HELD = "held", "Held"  # seats locked for a short time while the customer pays
    CONFIRMED = "confirmed", "Confirmed"  # payment succeeded
    EXPIRED = "expired", "Expired"  # hold ran out
    CANCELLED = "cancelled", "Cancelled"


class Reservation(models.Model):
    """A customer's claim on one or more seats for one event."""

    # UUID: appears in payment webhooks and links, so it must not be guessable.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservations"
    )
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="reservations")
    status = models.CharField(
        max_length=20, choices=ReservationStatus.choices, default=ReservationStatus.HELD
    )
    total_cents = models.PositiveIntegerField()  # snapshot of the price quoted at hold time
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # `choices` is only checked in Python; this makes the database enforce it too.
            models.CheckConstraint(
                condition=Q(status__in=ReservationStatus.values),
                name="reservation_status_valid",
            ),
        ]
        indexes = [
            # The expiry sweeper asks "which holds have lapsed?" all the time. Indexing only
            # held rows keeps it tiny however much history accumulates.
            models.Index(
                fields=["expires_at"],
                condition=Q(status=ReservationStatus.HELD),
                name="reservation_held_expiry_idx",
            ),
            models.Index(fields=["user", "-created_at"], name="reservation_user_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.id} ({self.status})"


class ReservationSeat(models.Model):
    """One seat inside a reservation.

    `is_active` is true while the seat is claimed (held or confirmed) and flips to false in
    the same transaction that expires or cancels the reservation. A partial unique index on
    it lets Postgres itself guarantee that a seat has at most one active claim.
    """

    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="items")
    # PROTECT: a seat with booking history must never be deleted out from under it.
    seat = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name="reservation_items")
    price_cents = models.PositiveIntegerField()  # snapshot: later price changes don't apply
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # THE double-booking guard: two live claims on one seat are impossible, even if
            # app code has a race or is bypassed (bulk_create, raw SQL, a buggy worker).
            models.UniqueConstraint(
                fields=["seat"],
                condition=Q(is_active=True),
                name="reservation_seat_one_active_per_seat",
            ),
            models.UniqueConstraint(
                fields=["reservation", "seat"], name="reservation_seat_unique_in_reservation"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reservation_id} -> seat {self.seat_id}"
