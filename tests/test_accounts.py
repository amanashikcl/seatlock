import pytest
from django.db import IntegrityError

from apps.accounts.models import User
from apps.accounts.roles import Role

pytestmark = pytest.mark.django_db


def test_create_user_defaults_and_normalizes_email() -> None:
    user = User.objects.create_user("Alice@Example.COM", "s3cret-pass")
    assert user.email == "alice@example.com"
    assert user.role == Role.CUSTOMER
    assert user.is_active and not user.is_staff and not user.is_superuser
    assert user.password != "s3cret-pass"  # stored hashed
    assert user.check_password("s3cret-pass")


def test_create_user_requires_email() -> None:
    with pytest.raises(ValueError):
        User.objects.create_user("", "pw")


def test_duplicate_email_differing_only_by_case_is_rejected() -> None:
    User.objects.create_user("bob@example.com", "pw")
    with pytest.raises(IntegrityError):
        User.objects.create_user("BOB@example.com", "pw")


def test_database_constraint_blocks_case_variants_even_if_save_is_bypassed() -> None:
    User.objects.create_user("carol@example.com", "pw")
    with pytest.raises(IntegrityError):
        User.objects.bulk_create([User(email="CAROL@example.com")])  # skips save()


def test_create_superuser_sets_flags_and_admin_role() -> None:
    admin = User.objects.create_superuser("root@example.com", "pw")
    assert admin.is_staff and admin.is_superuser
    assert admin.role == Role.ADMIN


def test_create_superuser_rejects_non_staff() -> None:
    with pytest.raises(ValueError):
        User.objects.create_superuser("x@example.com", "pw", is_staff=False)
