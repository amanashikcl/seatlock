"""Webhook endpoint. Plain Django view, not DRF: we need the raw bytes the signature covers."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.metrics import WEBHOOKS
from apps.payments.processing import process_event, record_event
from apps.payments.signature import InvalidSignature, verify

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Signature"
MAX_BODY_BYTES = 64 * 1024  # a webhook is a few hundred bytes; refuse anything absurd


def _error(status: int, code: str) -> JsonResponse:
    return JsonResponse({"code": code}, status=status)


@csrf_exempt  # the provider has no CSRF token; the HMAC signature is the authentication
@require_POST
def payment_webhook(request: HttpRequest) -> HttpResponse:
    """Verify, store once, process. Returns 200 for anything we have safely recorded.

    Order matters: the signature is checked against the raw body BEFORE it is parsed, so
    unauthenticated callers never reach JSON parsing, the database or business logic.
    """
    raw = request.body
    if len(raw) > MAX_BODY_BYTES:
        return _error(413, "payload_too_large")

    try:
        verify(raw, request.headers.get(SIGNATURE_HEADER, ""), settings.PAYMENT_WEBHOOK_SECRET)
    except InvalidSignature:
        logger.warning("webhook rejected: bad signature")
        WEBHOOKS.labels("bad_signature").inc()
        return _error(401, "invalid_signature")

    try:
        body = json.loads(raw)
        event_id = body["id"]
        event_type = body["type"]
    except (ValueError, KeyError, TypeError):
        WEBHOOKS.labels("bad_payload").inc()
        return _error(400, "invalid_payload")
    if not (isinstance(event_id, str) and isinstance(event_type, str) and event_id):
        WEBHOOKS.labels("bad_payload").inc()
        return _error(400, "invalid_payload")
    if len(event_id) > 100 or len(event_type) > 100:
        WEBHOOKS.labels("bad_payload").inc()
        return _error(400, "invalid_payload")

    event, created = record_event(provider_event_id=event_id, event_type=event_type, payload=body)
    event = process_event(event)  # an unexpected error here -> 500 -> provider retries
    WEBHOOKS.labels(event.status if created else "duplicate").inc()
    return JsonResponse({"status": event.status})
