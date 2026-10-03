"""Release holds whose time ran out. Plain function: a Celery task just calls it."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.reservations.models import Reservation, ReservationSeat, ReservationStatus

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
# Payments may arrive a little after a hold lapses (provider latency). Holds are only expired
# once `expires_at + HOLD_GRACE` has passed, and confirmation accepts payment until then too,
# so the cut-off is a fixed moment rather than "whenever the sweeper last ran".
HOLD_GRACE = timedelta(seconds=60)


@transaction.atomic
def expire_holds(*, now: datetime | None = None, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Expire up to `batch_size` holds past their grace period, freeing seats. Returns how many.

    SKIP LOCKED: rows another transaction is working on (a concurrent sweeper, or a payment
    being confirmed) are skipped, never waited on, so sweepers cannot collide or stall.
    Idempotent: only `held` rows are touched, so a retry or double run is harmless.
    The reservation status and its seat claims flip in this one transaction, so they can
    never disagree.
    """
    now = now or timezone.now()
    ids = list(
        Reservation.objects.select_for_update(skip_locked=True)
        .filter(status=ReservationStatus.HELD, expires_at__lte=now - HOLD_GRACE)
        .order_by("expires_at")
        .values_list("id", flat=True)[:batch_size]
    )
    if not ids:
        return 0
    Reservation.objects.filter(id__in=ids).update(status=ReservationStatus.EXPIRED)
    ReservationSeat.objects.filter(reservation_id__in=ids).update(is_active=False)
    logger.info("expired %d lapsed holds", len(ids))
    return len(ids)
