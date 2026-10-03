import json
from typing import Any

import pytest
from django.conf import settings
from django.test import Client

from apps.events.models import Event
from apps.payments.models import WebhookEvent, WebhookStatus
from apps.payments.signature import sign
from apps.reservations.models import ReservationStatus
from tests.factories import make_event, make_hold

URL = "/api/v1/webhooks/payments/"


def post(body: bytes, header: str | None = None) -> Any:
    headers = {} if header is None else {"X-Signature": header}
    return Client().post(URL, data=body, content_type="application/json", headers=headers)


def signed_post(payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode()
    return post(body, sign(body, settings.PAYMENT_WEBHOOK_SECRET))


def succeeded(evt_id: str, reservation_id: object, amount: int = 5000) -> dict[str, Any]:
    return {
        "id": evt_id,
        "type": "payment.succeeded",
        "data": {"reservation_id": str(reservation_id), "amount_cents": amount},
    }


@pytest.fixture
def event() -> Event:
    return make_event()


@pytest.mark.django_db
def test_signed_payment_confirms_the_reservation(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    resp = signed_post(succeeded("evt_1", hold.id))
    hold.refresh_from_db()
    assert resp.status_code == 200
    assert resp.json() == {"status": "processed"}
    assert hold.status == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_redelivery_returns_200_and_changes_nothing(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    payload = succeeded("evt_1", hold.id)
    assert signed_post(payload).status_code == 200
    assert signed_post(payload).status_code == 200
    assert WebhookEvent.objects.count() == 1


@pytest.mark.django_db
def test_missing_signature_is_401_and_stores_nothing(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    resp = post(json.dumps(succeeded("evt_1", hold.id)).encode())
    hold.refresh_from_db()
    assert resp.status_code == 401
    assert resp.json() == {"code": "invalid_signature"}
    assert WebhookEvent.objects.count() == 0
    assert hold.status == ReservationStatus.HELD


@pytest.mark.django_db
def test_wrong_secret_is_401() -> None:
    body = json.dumps({"id": "evt_1", "type": "x"}).encode()
    assert post(body, sign(body, "attacker-secret")).status_code == 401
    assert WebhookEvent.objects.count() == 0


@pytest.mark.django_db
def test_body_changed_after_signing_is_401() -> None:
    body = json.dumps({"id": "evt_1", "type": "x"}).encode()
    header = sign(body, settings.PAYMENT_WEBHOOK_SECRET)
    assert post(body + b" ", header).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"type":"x"}', b'{"id":"","type":"x"}', b'{"id":1,"type":"x"}'],
)
def test_signed_but_malformed_body_is_400(body: bytes) -> None:
    resp = post(body, sign(body, settings.PAYMENT_WEBHOOK_SECRET))
    assert resp.status_code == 400
    assert resp.json() == {"code": "invalid_payload"}


@pytest.mark.django_db
def test_business_failure_is_still_200_so_the_provider_stops_retrying() -> None:
    resp = signed_post(succeeded("evt_1", "00000000-0000-0000-0000-000000000000"))
    assert resp.status_code == 200
    assert resp.json() == {"status": WebhookStatus.FAILED}


@pytest.mark.django_db
def test_get_is_not_allowed() -> None:
    assert Client().get(URL).status_code == 405


@pytest.mark.django_db
def test_oversized_body_is_413() -> None:
    assert post(b"x" * (64 * 1024 + 1), "t=1,v1=00").status_code == 413
