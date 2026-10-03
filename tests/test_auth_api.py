import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
TOKEN = "/api/v1/auth/token/"
ME = "/api/v1/auth/me/"
GOOD_PASSWORD = "Tr1cky-Horse-Battery!"


@pytest.fixture
def api() -> APIClient:
    return APIClient()


def register(api: APIClient, email: str = "dave@example.com", **extra: str) -> int:
    response = api.post(REGISTER, {"email": email, "password": GOOD_PASSWORD, **extra})
    return int(response.status_code)


def login(api: APIClient, email: str = "dave@example.com") -> str:
    response = api.post(TOKEN, {"email": email, "password": GOOD_PASSWORD})
    assert response.status_code == 200
    return str(response.json()["access"])


def test_register_creates_customer_and_never_returns_password(api: APIClient) -> None:
    response = api.post(REGISTER, {"email": "Dave@Example.com", "password": GOOD_PASSWORD})
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "dave@example.com"
    assert "password" not in body
    assert User.objects.get(email="dave@example.com").role == Role.CUSTOMER


def test_register_cannot_choose_role(api: APIClient) -> None:
    assert register(api, role="admin") == 201
    assert User.objects.get(email="dave@example.com").role == Role.CUSTOMER


def test_register_rejects_duplicate_email_in_any_case(api: APIClient) -> None:
    assert register(api, "erin@example.com") == 201
    assert register(api, "ERIN@example.com") == 400


def test_register_rejects_weak_password(api: APIClient) -> None:
    response = api.post(REGISTER, {"email": "weak@example.com", "password": "12345678"})
    assert response.status_code == 400
    assert "password" in response.json()


def test_login_returns_access_and_refresh_tokens(api: APIClient) -> None:
    register(api)
    response = api.post(TOKEN, {"email": "dave@example.com", "password": GOOD_PASSWORD})
    assert response.status_code == 200
    assert {"access", "refresh"} <= set(response.json())


def test_login_with_wrong_password_is_401(api: APIClient) -> None:
    register(api)
    response = api.post(TOKEN, {"email": "dave@example.com", "password": "nope-nope-nope"})
    assert response.status_code == 401


def test_me_requires_a_token(api: APIClient) -> None:
    assert api.get(ME).status_code == 401


def test_me_returns_the_authenticated_user(api: APIClient) -> None:
    register(api)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login(api)}")
    response = api.get(ME)
    assert response.status_code == 200
    assert response.json()["email"] == "dave@example.com"
    assert response.json()["role"] == "customer"
