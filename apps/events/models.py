from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Event(models.Model):
    """A ticketed event. Seats are sold between `sales_open_at` and `starts_at`."""

    # PROTECT: deleting a user must never silently delete events that may have orders.
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="events"
    )
    name = models.CharField(max_length=200)
    venue = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    sales_open_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(sales_open_at__lt=F("starts_at")),
                name="event_sales_open_before_start",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Seat(models.Model):
    """A physical seat for one event.

    Deliberately has NO sold/available flag: availability is derived from reservation
    rows (the single source of truth), so it can never drift out of sync.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="seats")
    section = models.CharField(max_length=20)
    row = models.CharField(max_length=10)
    number = models.PositiveSmallIntegerField()
    # Money is integer cents: exact arithmetic, no float rounding. DB also enforces >= 0.
    price_cents = models.PositiveIntegerField()

    class Meta:
        ordering = ["section", "row", "number"]
        constraints = [
            # Also serves as the index for "all seats of an event" (event is the leading column).
            models.UniqueConstraint(
                fields=["event", "section", "row", "number"],
                name="seat_unique_label_per_event",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.section}-{self.row}{self.number}"
