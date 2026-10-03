import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connections
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event
from apps.reservations.expiry import expire_holds
from apps.reservations.models import ReservationSeat
from apps.reservations.services import hold_seats
from tests.factories import make_event, make_seats, make_user


def client_for(user: User | None = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def seats_url(event: Event) -> str:
    return f"/api/v1/events/{event.pk}/seats/"


def holds_url(event: Event) -> str:
    return f"/api/v1/events/{event.pk}/holds/"


@pytest.fixture
def event() -> Event:
    return make_event()


@pytest.mark.django_db
def test_seat_map_shows_which_seats_are_available(event: Event) -> None:
    held, free = make_seats(event, 2)
    hold_seats(user=make_user(1), event=event, seat_ids=[held.id])
    response = client_for(make_user(2)).get(seats_url(event))
    assert response.status_code == 200
    availability = {row["id"]: row["available"] for row in response.json()["results"]}
    assert availability == {held.id: False, free.id: True}


@pytest.mark.django_db
def test_seat_becomes_available_again_after_its_hold_expires(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    placed_at = timezone.now() - timedelta(minutes=20)
    hold_seats(user=make_user(1), event=event, seat_ids=[seat.id], now=placed_at)
    expire_holds()
    rows = client_for(make_user(2)).get(seats_url(event)).json()["results"]
    assert rows[0]["available"] is True


@pytest.mark.django_db
def test_seat_map_and_holds_require_login_and_a_real_event(event: Event) -> None:
    assert client_for().get(seats_url(event)).status_code == 401
    anonymous = client_for().post(holds_url(event), {"seat_ids": [1]}, format="json")
    assert anonymous.status_code == 401
    user = client_for(make_user(1))
    assert user.get("/api/v1/events/999999/seats/").status_code == 404
    missing = user.post("/api/v1/events/999999/holds/", {"seat_ids": [1]}, format="json")
    assert missing.status_code == 404


@pytest.mark.django_db
def test_hold_succeeds_and_returns_the_reservation(event: Event) -> None:
    first, second = make_seats(event, 2)
    buyer = make_user(1)
    response = client_for(buyer).post(
        holds_url(event), {"seat_ids": [first.id, second.id]}, format="json"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "held"
    assert body["total_cents"] == 10000
    assert body["seat_ids"] == sorted([first.id, second.id])
    assert ReservationSeat.objects.filter(reservation_id=body["id"], is_active=True).count() == 2


@pytest.mark.django_db
def test_taking_a_held_seat_is_a_409_with_a_stable_code(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    assert (
        client_for(make_user(1))
        .post(holds_url(event), {"seat_ids": [seat.id]}, format="json")
        .status_code
        == 201
    )
    loser = client_for(make_user(2))
    response = loser.post(holds_url(event), {"seat_ids": [seat.id]}, format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "seat_unavailable"
    assert response.json()["seat_ids"] == [seat.id]


@pytest.mark.django_db
def test_hold_is_all_or_nothing_over_http(event: Event) -> None:
    taken, free = make_seats(event, 2)
    hold_seats(user=make_user(1), event=event, seat_ids=[taken.id])
    response = client_for(make_user(2)).post(
        holds_url(event), {"seat_ids": [taken.id, free.id]}, format="json"
    )
    assert response.status_code == 409
    assert not ReservationSeat.objects.filter(seat=free).exists()


@pytest.mark.django_db
def test_bad_selections_are_400(event: Event) -> None:
    buyer = client_for(make_user(1))
    other_event = make_event("other-org@example.com")
    (foreign,) = make_seats(other_event, 1)
    wrong_event = buyer.post(holds_url(event), {"seat_ids": [foreign.id]}, format="json")
    assert wrong_event.status_code == 400
    assert wrong_event.json()["code"] == "invalid_selection"
    assert buyer.post(holds_url(event), {"seat_ids": []}, format="json").status_code == 400
    assert buyer.post(holds_url(event), {"seat_ids": ["x"]}, format="json").status_code == 400
    assert buyer.post(holds_url(event), {}, format="json").status_code == 400


@pytest.mark.django_db
def test_hold_before_sales_open_is_a_409(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    event.sales_open_at = timezone.now() + timedelta(days=1)
    event.save()
    buyer = client_for(make_user(1))
    response = buyer.post(holds_url(event), {"seat_ids": [seat.id]}, format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "sales_not_open"


@pytest.mark.django_db(transaction=True)
def test_twenty_simultaneous_http_requests_for_one_seat_yield_one_201(event: Event) -> None:
    (seat,) = make_seats(event, 1)
    users = [make_user(n) for n in range(20)]
    barrier = threading.Barrier(len(users), timeout=30)

    def attempt(user: User) -> int:
        client = client_for(user)
        try:
            barrier.wait()
            response = client.post(holds_url(event), {"seat_ids": [seat.id]}, format="json")
            return int(response.status_code)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(users)) as pool:
        codes = list(pool.map(attempt, users))
    assert sorted(codes) == [201] + [409] * 19
