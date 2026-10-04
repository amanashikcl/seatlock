from datetime import timedelta
from typing import Any

import pytest
import redis
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.redis_client import get_client
from apps.events.models import Event
from apps.payments.processing import PAYMENT_SUCCEEDED, process_event, record_event
from apps.reservations import gate
from apps.reservations.expiry import expire_holds
from apps.reservations.services import HOLD_DURATION, hold_seats
from tests.factories import make_event, make_hold, make_seats, make_user


def client_for(user: User, **kwargs: Any) -> APIClient:
    client = APIClient(**kwargs)
    client.force_authenticate(user=user)
    return client


def hold(client: APIClient, event: Event, *seat_ids: int) -> Any:
    return client.post(f"/api/v1/events/{event.pk}/holds/", {"seat_ids": list(seat_ids)}, "json")


@pytest.fixture
def event() -> Event:
    return make_event()


@pytest.mark.django_db
def test_a_gated_conflict_is_409_and_never_reaches_the_database(
    event: Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    (seat,) = make_seats(event, 1)
    gate.claim([seat.id])  # somebody else already holds it

    def boom(**kwargs: Any) -> None:
        raise AssertionError("the database must not be touched")

    monkeypatch.setattr("apps.reservations.views.hold_seats", boom)
    response = hold(client_for(make_user(1)), event, seat.id)
    assert response.status_code == 409
    assert response.json()["code"] == "seat_unavailable"
    assert response.json()["seat_ids"] == [seat.id]


@pytest.mark.django_db
def test_a_successful_hold_keeps_the_claim_for_the_hold_duration(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    assert hold(client_for(make_user(1)), event, seat.id).status_code == 201
    ttl = get_client().ttl(f"{gate.PREFIX}{seat.id}")
    assert HOLD_DURATION.total_seconds() - 10 < ttl <= HOLD_DURATION.total_seconds()


@pytest.mark.django_db
def test_database_refusal_releases_the_claim(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    hold_seats(user=make_user(1), event=event, seat_ids=[seat.id])  # DB knows, Redis does not
    response = hold(client_for(make_user(2)), event, seat.id)
    assert response.status_code == 409
    assert get_client().exists(f"{gate.PREFIX}{seat.id}") == 0


@pytest.mark.django_db
def test_unexpected_error_releases_the_claim(event: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    (seat,) = make_seats(event, 1)

    def broken(**kwargs: Any) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr("apps.reservations.views.hold_seats", broken)
    response = hold(client_for(make_user(1), raise_request_exception=False), event, seat.id)
    assert response.status_code == 500
    assert get_client().exists(f"{gate.PREFIX}{seat.id}") == 0


@pytest.mark.django_db
def test_holds_still_work_when_redis_is_down(event: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    (seat,) = make_seats(event, 1)
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1)
    monkeypatch.setattr(gate, "get_client", lambda: dead)
    monkeypatch.setattr("apps.core.ratelimit.get_client", lambda: dead)
    assert hold(client_for(make_user(1)), event, seat.id).status_code == 201


@pytest.mark.django_db
def test_a_confirmed_payment_marks_the_seats_sold_after_commit(
    event: Event, django_capture_on_commit_callbacks: Any
) -> None:
    reservation = make_hold(event, 1, seconds_past_expiry=-300)
    body = {"data": {"reservation_id": str(reservation.id), "amount_cents": 5000}}
    evt, _ = record_event(provider_event_id="evt_1", event_type=PAYMENT_SUCCEEDED, payload=body)
    with django_capture_on_commit_callbacks(execute=True):
        process_event(evt)
    seat_id = reservation.items.get().seat_id
    assert get_client().get(f"{gate.PREFIX}{seat_id}") == gate.SOLD_MARKER


@pytest.mark.django_db
def test_expired_holds_free_their_seats_in_the_gate_too(
    event: Event, django_capture_on_commit_callbacks: Any
) -> None:
    (seat,) = make_seats(event, 1)
    past = timezone.now() - HOLD_DURATION - timedelta(minutes=5)
    hold_seats(user=make_user(1), event=event, seat_ids=[seat.id], now=past)
    # The key a real earlier hold would have left behind:
    get_client().set(f"{gate.PREFIX}{seat.id}", "old-claim", ex=600)
    with django_capture_on_commit_callbacks(execute=True):
        assert expire_holds() == 1
    assert hold(client_for(make_user(2)), event, seat.id).status_code == 201
