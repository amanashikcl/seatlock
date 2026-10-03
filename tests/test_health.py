from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from django.test import Client

from apps.core import health


@contextmanager
def fake_checks(**overrides: Exception) -> Iterator[None]:
    """Replace each dependency check with a stub; raise if an override is given."""
    with ExitStack() as stack:
        for name in ("check_database", "check_redis", "check_broker"):
            stack.enter_context(patch.object(health, name, side_effect=overrides.get(name)))
        yield


def test_healthz_is_ok_without_touching_dependencies(client: Client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ok_when_all_dependencies_up(client: Client) -> None:
    with fake_checks():
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "redis": "ok", "broker": "ok"}


def test_readyz_503_and_no_leak_when_a_dependency_is_down(client: Client) -> None:
    with fake_checks(check_redis=OSError("secret-host refused")):
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "fail"
    assert "secret-host" not in response.content.decode()


@pytest.mark.django_db
def test_check_database_against_real_db() -> None:
    health.check_database()  # raises on failure
