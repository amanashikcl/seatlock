"""Turn a held reservation into a paid one. No HTTP in here."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.reservations.expiry import HOLD_GRACE
from apps.reservations.models import Reservation, ReservationStatus
from apps.reservations.services import ReservationError


class ReservationNotFound(ReservationError):
    """No reservation has this id."""


class ReservationNotConfirmable(ReservationError):
    """The reservation can no longer be paid for. `reason` says why (expired/cancelled/late)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Reservation cannot be confirmed: {reason}")
        self.reason = reason


@transaction.atomic
def confirm_reservation(*, reservation_id: uuid.UUID, now: datetime | None = None) -> Reservation:
    """Mark a held reservation as confirmed (paid). Idempotent.

    The reservation row is locked first. The expiry sweeper skips locked rows, so the two can
    never both act: if the sweeper wins, we see `expired` and refuse; if we win, it skips us.
    Payment is accepted until `expires_at + HOLD_GRACE`, the same moment the sweeper starts
    expiring, so the cut-off is deterministic.
    """
    now = now or timezone.now()
    try:
        reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
    except Reservation.DoesNotExist as exc:
        raise ReservationNotFound(str(reservation_id)) from exc

    if reservation.status == ReservationStatus.CONFIRMED:
        return reservation  # a duplicate delivery: nothing to do
    if reservation.status != ReservationStatus.HELD:
        raise ReservationNotConfirmable(reservation.status)  # expired or cancelled
    if now > reservation.expires_at + HOLD_GRACE:
        raise ReservationNotConfirmable("late")  # too late; the sweeper will release the seats

    reservation.status = ReservationStatus.CONFIRMED
    reservation.save(update_fields=["status"])
    return reservation
