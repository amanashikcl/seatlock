import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from django.db import IntegrityError, connections, transaction

from apps.events.models import Event
from apps.payments.models import WebhookEvent, WebhookStatus
from apps.payments.processing import PAYMENT_SUCCEEDED, process_event, record_event
from apps.reservations.models import ReservationStatus
from tests.factories import make_event, make_hold


@pytest.fixture
def event() -> Event:
    return make_event()


def payload(reservation_id: object, amount_cents: object = 5000) -> dict[str, Any]:
    return {"data": {"reservation_id": str(reservation_id), "amount_cents": amount_cents}}


def store(evt_id: str, body: dict[str, Any], event_type: str = PAYMENT_SUCCEEDED) -> WebhookEvent:
    return record_event(provider_event_id=evt_id, event_type=event_type, payload=body)[0]


@pytest.mark.django_db
def test_an_event_is_stored_once_and_a_duplicate_returns_the_original() -> None:
    first, created_first = record_event(
        provider_event_id="evt_1", event_type=PAYMENT_SUCCEEDED, payload={"a": 1}
    )
    second, created_second = record_event(
        provider_event_id="evt_1", event_type=PAYMENT_SUCCEEDED, payload={"a": 2}
    )
    assert created_first and not created_second
    assert second.pk == first.pk
    assert second.payload == {"a": 1}
    assert WebhookEvent.objects.count() == 1


@pytest.mark.django_db
def test_database_itself_rejects_a_duplicate_provider_event_id() -> None:
    WebhookEvent.objects.create(provider_event_id="evt_1", event_type="x", payload={})
    with pytest.raises(IntegrityError), transaction.atomic():
        WebhookEvent.objects.create(provider_event_id="evt_1", event_type="x", payload={})


@pytest.mark.django_db
def test_successful_payment_confirms_the_reservation(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    result = process_event(store("evt_1", payload(hold.id)))
    hold.refresh_from_db()
    assert result.status == WebhookStatus.PROCESSED
    assert result.processed_at is not None
    assert hold.status == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_processing_twice_is_a_no_op(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    evt = store("evt_1", payload(hold.id))
    first = process_event(evt)
    stamp = first.processed_at
    again = process_event(WebhookEvent.objects.get(pk=evt.pk))
    assert again.status == WebhookStatus.PROCESSED
    assert again.processed_at == stamp


@pytest.mark.django_db
def test_unknown_event_types_are_acknowledged_and_ignored() -> None:
    result = process_event(store("evt_1", {}, event_type="customer.created"))
    assert result.status == WebhookStatus.PROCESSED
    assert result.detail.startswith("ignored")


@pytest.mark.django_db
def test_unknown_reservation_is_recorded_as_failed() -> None:
    result = process_event(store("evt_1", payload(uuid.uuid4())))
    assert result.status == WebhookStatus.FAILED
    assert result.detail == "reservation_not_found"


@pytest.mark.django_db
def test_payment_after_the_grace_period_is_flagged_for_refund(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=600)
    result = process_event(store("evt_1", payload(hold.id)))
    hold.refresh_from_db()
    assert result.status == WebhookStatus.FAILED
    assert result.detail == "needs_refund:late"
    assert hold.status == ReservationStatus.HELD


@pytest.mark.django_db
def test_wrong_amount_is_recorded_and_the_reservation_stays_held(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    result = process_event(store("evt_1", payload(hold.id, amount_cents=1)))
    hold.refresh_from_db()
    assert result.status == WebhookStatus.FAILED
    assert result.detail == "amount_mismatch"
    assert hold.status == ReservationStatus.HELD


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": None},
        {"data": {}},
        {"data": {"reservation_id": "not-a-uuid", "amount_cents": 5000}},
        {"data": {"reservation_id": str(uuid.uuid4()), "amount_cents": "abc"}},
    ],
)
def test_malformed_payloads_are_recorded_as_failed(body: dict[str, Any]) -> None:
    result = process_event(store("evt_1", body))
    assert result.status == WebhookStatus.FAILED
    assert result.detail == "malformed_payload"


@pytest.mark.django_db(transaction=True)
def test_simultaneous_duplicate_deliveries_store_one_row_and_confirm_once(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    body = payload(hold.id)
    barrier = threading.Barrier(6)

    def deliver() -> str:
        try:
            barrier.wait()
            evt, _ = record_event(
                provider_event_id="evt_race", event_type=PAYMENT_SUCCEEDED, payload=body
            )
            return process_event(evt).status
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = [f.result() for f in [pool.submit(deliver) for _ in range(6)]]

    hold.refresh_from_db()
    assert WebhookEvent.objects.filter(provider_event_id="evt_race").count() == 1
    assert hold.status == ReservationStatus.CONFIRMED
    assert set(statuses) <= {WebhookStatus.PROCESSED, WebhookStatus.RECEIVED}
