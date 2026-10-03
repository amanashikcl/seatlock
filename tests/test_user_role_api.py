import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role

pytestmark = pytest.mark.django_db


def role_url(user: User) -> str:
    return f"/api/v1/auth/users/{user.pk}/role/"


def client_for(user: User | None = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def test_admin_can_promote_a_customer_to_organizer() -> None:
    admin = User.objects.create_superuser("root@example.com", "pw")
    customer = User.objects.create_user("cust@example.com", "pw")
    response = client_for(admin).patch(role_url(customer), {"role": "organizer"})
    assert response.status_code == 200
    assert response.json()["role"] == "organizer"
    customer.refresh_from_db()
    assert customer.role == Role.ORGANIZER


def test_customer_cannot_change_roles() -> None:
    customer = User.objects.create_user("cust@example.com", "pw")
    other = User.objects.create_user("other@example.com", "pw")
    response = client_for(customer).patch(role_url(other), {"role": "admin"})
    assert response.status_code == 403
    other.refresh_from_db()
    assert other.role == Role.CUSTOMER


def test_organizer_cannot_change_roles() -> None:
    organizer = User.objects.create_user("org@example.com", "pw", role=Role.ORGANIZER)
    other = User.objects.create_user("other@example.com", "pw")
    assert client_for(organizer).patch(role_url(other), {"role": "admin"}).status_code == 403


def test_anonymous_request_is_401() -> None:
    target = User.objects.create_user("t@example.com", "pw")
    assert client_for().patch(role_url(target), {"role": "admin"}).status_code == 401


def test_invalid_role_is_rejected() -> None:
    admin = User.objects.create_superuser("root@example.com", "pw")
    target = User.objects.create_user("t@example.com", "pw")
    response = client_for(admin).patch(role_url(target), {"role": "superhero"})
    assert response.status_code == 400


def test_admin_cannot_change_their_own_role() -> None:
    admin = User.objects.create_superuser("root@example.com", "pw")
    response = client_for(admin).patch(role_url(admin), {"role": "customer"})
    assert response.status_code == 400
    admin.refresh_from_db()
    assert admin.role == Role.ADMIN
