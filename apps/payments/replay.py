"""Re-run webhook events that were stored but never finished (a crash between save and apply)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.payments.models import WebhookEvent, WebhookStatus
from apps.payments.processing import process_event

logger = logging.getLogger(__name__)

# Give the request that stored the event time to finish it before the sweeper steps in.
MIN_AGE = timedelta(minutes=1)
DEFAULT_BATCH_SIZE = 100


def replay_unprocessed(
    *,
    min_age: timedelta = MIN_AGE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
) -> int:
    """Process up to `batch_size` stuck events, oldest first. Returns how many finished.

    Each event gets its own transaction, so one poisonous event cannot roll back or block the
    others. skip_locked lets two sweepers run side by side without waiting on each other.
    Safe against the original request still running: confirming is idempotent.
    """
    now = now or timezone.now()
    stuck_ids = list(
        WebhookEvent.objects.filter(status=WebhookStatus.RECEIVED, received_at__lte=now - min_age)
        .order_by("received_at")
        .values_list("pk", flat=True)[:batch_size]
    )
    finished = 0
    for pk in stuck_ids:
        try:
            with transaction.atomic():
                event = (
                    WebhookEvent.objects.select_for_update(skip_locked=True)
                    .filter(pk=pk, status=WebhookStatus.RECEIVED)
                    .first()
                )
                if event is None:  # finished or locked by someone else meanwhile
                    continue
                process_event(event, now=now)
                finished += 1
        except Exception:
            # Leave it `received`; it is retried next run. Log with the traceback and move on.
            logger.exception("webhook replay failed for event pk=%s", pk)
    return finished
