import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event
from tests.factories import make_event, make_seats, make_user


def client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def event() -> Event:
    return make_event()


@pytest.mark.django_db
@override_settings(HOLD_RATE_LIMIT=2)
def test_third_attempt_in_the_window_is_429_with_retry_after(event: Event) -> None:
    seats = make_seats(event, 3)
    client = client_for(make_user(1))
    url = f"/api/v1/events/{event.pk}/holds/"
    codes = [client.post(url, {"seat_ids": [s.id]}, format="json").status_code for s in seats]
    assert codes == [201, 201, 429]
    blocked = client.post(url, {"seat_ids": [seats[0].id]}, format="json")
    assert int(blocked["Retry-After"]) >= 1


@pytest.mark.django_db
@override_settings(HOLD_RATE_LIMIT=1)
def test_one_users_limit_does_not_affect_another(event: Event) -> None:
    first, second = make_seats(event, 2)
    url = f"/api/v1/events/{event.pk}/holds/"
    one = client_for(make_user(1)).post(url, {"seat_ids": [first.id]}, format="json")
    two = client_for(make_user(2)).post(url, {"seat_ids": [second.id]}, format="json")
    assert (one.status_code, two.status_code) == (201, 201)
