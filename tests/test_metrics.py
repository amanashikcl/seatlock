import json
from typing import Any

import pytest
from django.conf import settings
from django.test import Client
from prometheus_client import REGISTRY
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.payments.signature import sign
from apps.reservations import gate
from apps.reservations.services import hold_seats
from tests.factories import make_event, make_seats, make_user


def count(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def hold(user: User, event_id: int, seat_id: int) -> Any:
    url = f"/api/v1/events/{event_id}/holds/"
    return client_for(user).post(url, {"seat_ids": [seat_id]}, "json")


def test_metrics_endpoint_serves_prometheus_text() -> None:
    response = Client().get("/metrics")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert b"seatlock_holds_total" in response.content


@pytest.mark.django_db
def test_a_successful_hold_is_counted_as_created() -> None:
    event = make_event()
    (seat,) = make_seats(event, 1)
    before = count("seatlock_holds_total", outcome="created")
    assert hold(make_user(1), event.pk, seat.id).status_code == 201
    assert count("seatlock_holds_total", outcome="created") == before + 1


@pytest.mark.django_db
def test_gate_and_database_rejections_are_counted_separately() -> None:
    event = make_event()
    gated, unknown_to_gate = make_seats(event, 2)
    gate.claim([gated.id])  # the gate knows this one is taken
    hold_seats(user=make_user(1), event=event, seat_ids=[unknown_to_gate.id])  # only the DB does
    gate_before = count("seatlock_holds_total", outcome="gate_rejected")
    db_before = count("seatlock_holds_total", outcome="seat_unavailable")
    assert hold(make_user(2), event.pk, gated.id).status_code == 409
    assert hold(make_user(3), event.pk, unknown_to_gate.id).status_code == 409
    assert count("seatlock_holds_total", outcome="gate_rejected") == gate_before + 1
    assert count("seatlock_holds_total", outcome="seat_unavailable") == db_before + 1


@pytest.mark.django_db
def test_requests_are_labelled_by_route_template_not_raw_path() -> None:
    event = make_event()
    client_for(make_user(1)).get(f"/api/v1/events/{event.pk}/seats/")
    body = Client().get("/metrics").content.decode()
    assert 'route="api/v1/events/<int:event_id>/seats/"' in body
    assert f"/events/{event.pk}/seats" not in body  # the id must never become a label


@pytest.mark.django_db
def test_unknown_paths_share_one_label_so_cardinality_stays_bounded() -> None:
    Client().get("/no/such/page-1/")
    Client().get("/no/such/page-2/")
    body = Client().get("/metrics").content.decode()
    assert 'route="unmatched"' in body
    assert "page-1" not in body


@pytest.mark.django_db
def test_webhook_outcomes_are_counted() -> None:
    bad_before = count("seatlock_webhook_events_total", result="bad_signature")
    url = "/api/v1/webhooks/payments/"
    unsigned = Client().post(url, data=b"{}", content_type="application/json")
    assert unsigned.status_code == 401
    assert count("seatlock_webhook_events_total", result="bad_signature") == bad_before + 1

    body = json.dumps({"id": "evt_m1", "type": "customer.created"}).encode()
    header = sign(body, settings.PAYMENT_WEBHOOK_SECRET)
    processed_before = count("seatlock_webhook_events_total", result="processed")
    dup_before = count("seatlock_webhook_events_total", result="duplicate")
    for _ in range(2):
        Client().post(
            url, data=body, content_type="application/json", headers={"X-Signature": header}
        )
    assert count("seatlock_webhook_events_total", result="processed") == processed_before + 1
    assert count("seatlock_webhook_events_total", result="duplicate") == dup_before + 1
