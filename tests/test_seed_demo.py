import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.events.models import Event, Seat

pytestmark = pytest.mark.django_db


def test_seed_demo_creates_accounts_event_and_seats_and_is_idempotent(settings: object) -> None:
    settings.DEBUG = True  # type: ignore[attr-defined]
    call_command("seed_demo", "--seats", "3")
    call_command("seed_demo", "--seats", "3")  # second run must change nothing
    assert User.objects.filter(email__startswith="demo-").count() == 2
    assert Event.objects.filter(name="Demo concert").count() == 1
    assert Seat.objects.count() == 3


def test_seed_demo_refuses_to_run_outside_debug(settings: object) -> None:
    settings.DEBUG = False  # type: ignore[attr-defined]
    with pytest.raises(CommandError):
        call_command("seed_demo")
    assert User.objects.count() == 0
