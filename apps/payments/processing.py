"""Store and apply payment webhooks. No HTTP in here: the view and the replay job call this."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.payments.models import WebhookEvent, WebhookStatus
from apps.reservations.confirmation import (
    PaymentAmountMismatch,
    ReservationNotConfirmable,
    ReservationNotFound,
    confirm_reservation,
)

logger = logging.getLogger(__name__)

PAYMENT_SUCCEEDED = "payment.succeeded"


def record_event(
    *, provider_event_id: str, event_type: str, payload: dict[str, Any]
) -> tuple[WebhookEvent, bool]:
    """Store the event once. Returns (event, created). Duplicates return the original row.

    get_or_create leans on the UNIQUE constraint, so two simultaneous deliveries of the same
    event cannot both create a row.
    """
    return WebhookEvent.objects.get_or_create(
        provider_event_id=provider_event_id,
        defaults={"event_type": event_type, "payload": payload},
    )


def process_event(event: WebhookEvent, *, now: datetime | None = None) -> WebhookEvent:
    """Apply a stored event. Idempotent: only `received` events are acted on.

    Business problems (unknown reservation, too late, wrong amount) are recorded as `failed`
    with a reason, not raised: re-delivery cannot fix them. Unexpected errors propagate and
    leave the event `received`, so it can be retried or replayed.
    """
    if event.status != WebhookStatus.RECEIVED:
        return event
    if event.event_type != PAYMENT_SUCCEEDED:
        return _finish(event, WebhookStatus.PROCESSED, "ignored: unhandled event type", now)

    try:
        data = event.payload["data"]
        reservation_id = uuid.UUID(str(data["reservation_id"]))
        paid_cents = int(data["amount_cents"])
    except (KeyError, TypeError, ValueError):
        return _finish(event, WebhookStatus.FAILED, "malformed_payload", now)

    try:
        confirm_reservation(reservation_id=reservation_id, paid_cents=paid_cents, now=now)
    except ReservationNotFound:
        return _finish(event, WebhookStatus.FAILED, "reservation_not_found", now)
    except ReservationNotConfirmable as exc:
        return _finish(event, WebhookStatus.FAILED, f"needs_refund:{exc.reason}", now)
    except PaymentAmountMismatch:
        return _finish(event, WebhookStatus.FAILED, "amount_mismatch", now)
    return _finish(event, WebhookStatus.PROCESSED, "", now)


def _finish(event: WebhookEvent, status: str, detail: str, now: datetime | None) -> WebhookEvent:
    event.status = status
    event.detail = detail
    event.processed_at = now or timezone.now()
    event.save(update_fields=["status", "detail", "processed_at"])
    if status == WebhookStatus.FAILED:
        logger.warning("webhook %s failed: %s", event.provider_event_id, detail)
    return event
