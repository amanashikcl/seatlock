from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin, IsOrganizer
from apps.accounts.roles import Role


@pytest.mark.parametrize(
    ("role", "organizer_ok", "admin_ok"),
    [
        (Role.CUSTOMER, False, False),
        (Role.ORGANIZER, True, False),
        (Role.ADMIN, True, True),
    ],
)
def test_role_permission_matrix(role: Role, organizer_ok: bool, admin_ok: bool) -> None:
    request = SimpleNamespace(user=User(email="x@example.com", role=role))
    assert IsOrganizer().has_permission(request, None) is organizer_ok
    assert IsAdmin().has_permission(request, None) is admin_ok


def test_anonymous_user_has_no_role_permissions() -> None:
    request = SimpleNamespace(user=AnonymousUser())
    assert IsOrganizer().has_permission(request, None) is False
    assert IsAdmin().has_permission(request, None) is False
