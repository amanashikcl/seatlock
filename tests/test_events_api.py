from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.events.models import Event

pytestmark = pytest.mark.django_db

EVENTS = "/api/v1/events/"


def make_user(email: str, role: str = Role.CUSTOMER) -> User:
    return User.objects.create_user(email, "pw", role=role)


def client_for(user: User | None = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def payload() -> dict[str, object]:
    now = timezone.now()
    return {
        "name": "Concert",
        "venue": "Main Hall",
        "starts_at": (now + timedelta(days=30)).isoformat(),
        "sales_open_at": (now + timedelta(days=1)).isoformat(),
    }


def make_event(organizer: User) -> Event:
    now = timezone.now()
    return Event.objects.create(
        organizer=organizer,
        name="Concert",
        venue="Main Hall",
        starts_at=now + timedelta(days=30),
        sales_open_at=now + timedelta(days=1),
    )


def detail(event: Event) -> str:
    return f"{EVENTS}{event.pk}/"


def test_anonymous_cannot_list_events() -> None:
    assert client_for().get(EVENTS).status_code == 401


def test_customer_can_list_and_retrieve_events() -> None:
    event = make_event(make_user("org@example.com", Role.ORGANIZER))
    customer = client_for(make_user("cust@example.com"))
    listing = customer.get(EVENTS)
    assert listing.status_code == 200
    assert len(listing.json()["results"]) == 1  # paginated shape
    assert customer.get(detail(event)).json()["name"] == "Concert"
    assert customer.get(f"{EVENTS}999999/").status_code == 404


def test_customer_cannot_create_an_event() -> None:
    response = client_for(make_user("cust@example.com")).post(EVENTS, payload(), format="json")
    assert response.status_code == 403
    assert Event.objects.count() == 0


def test_organizer_creates_an_event_owned_by_themselves_even_if_they_claim_otherwise() -> None:
    organizer = make_user("org@example.com", Role.ORGANIZER)
    other = make_user("other@example.com", Role.ORGANIZER)
    body = {**payload(), "organizer": other.pk}
    response = client_for(organizer).post(EVENTS, body, format="json")
    assert response.status_code == 201
    assert response.json()["organizer"] == organizer.pk


def test_admin_can_create_an_event() -> None:
    admin = User.objects.create_superuser("root@example.com", "pw")
    assert client_for(admin).post(EVENTS, payload(), format="json").status_code == 201


def test_sales_window_must_open_before_the_event_starts() -> None:
    organizer = make_user("org@example.com", Role.ORGANIZER)
    body = {**payload(), "sales_open_at": (timezone.now() + timedelta(days=40)).isoformat()}
    response = client_for(organizer).post(EVENTS, body, format="json")
    assert response.status_code == 400
    assert "sales_open_at" in response.json()


def test_owner_can_edit_their_event() -> None:
    organizer = make_user("org@example.com", Role.ORGANIZER)
    event = make_event(organizer)
    response = client_for(organizer).patch(detail(event), {"name": "Renamed"}, format="json")
    assert response.status_code == 200
    event.refresh_from_db()
    assert event.name == "Renamed"


def test_another_organizer_cannot_edit_the_event() -> None:
    event = make_event(make_user("org@example.com", Role.ORGANIZER))
    intruder = client_for(make_user("intruder@example.com", Role.ORGANIZER))
    assert intruder.patch(detail(event), {"name": "Hacked"}, format="json").status_code == 403
    event.refresh_from_db()
    assert event.name == "Concert"


def test_admin_can_edit_any_event_but_customers_cannot() -> None:
    event = make_event(make_user("org@example.com", Role.ORGANIZER))
    admin = User.objects.create_superuser("root@example.com", "pw")
    as_admin = client_for(admin).patch(detail(event), {"venue": "Arena"}, format="json")
    assert as_admin.status_code == 200
    customer = client_for(make_user("cust@example.com"))
    assert customer.patch(detail(event), {"venue": "Nope"}, format="json").status_code == 403


def test_editing_one_date_cannot_create_an_invalid_window() -> None:
    organizer = make_user("org@example.com", Role.ORGANIZER)
    event = make_event(organizer)
    late = (event.starts_at + timedelta(days=1)).isoformat()
    response = client_for(organizer).patch(detail(event), {"sales_open_at": late}, format="json")
    assert response.status_code == 400


def test_put_and_delete_are_not_allowed() -> None:
    organizer = make_user("org@example.com", Role.ORGANIZER)
    event = make_event(organizer)
    api = client_for(organizer)
    assert api.put(detail(event), payload(), format="json").status_code == 405
    assert api.delete(detail(event)).status_code == 405
