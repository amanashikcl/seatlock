from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.models import User
from apps.core.redis_client import get_client
from apps.events.models import Event, Seat
from apps.reservations import gate
from apps.reservations.models import ReservationStatus
from apps.reservations.services import hold_seats
from tests.factories import make_event, make_seats, make_user


def run(name: str, *args: object) -> str:
    out = StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_seed_loadtest_makes_a_fresh_event_each_run_without_credentials() -> None:
    run("seed_loadtest", "--seats", "7")
    run("seed_loadtest", "--seats", "3")
    assert Event.objects.count() == 2
    assert Seat.objects.count() == 10
    assert not User.objects.get(email="loadtest-org@example.com").has_usable_password()
    assert User.objects.count() == 1  # no buyers, no known passwords


@pytest.mark.django_db
def test_report_passes_when_holds_are_consistent() -> None:
    event = make_event()
    seats = make_seats(event, 3)
    hold_seats(user=make_user(1), event=event, seat_ids=[seats[0].id, seats[1].id])
    output = run("loadtest_report", event.id)
    assert "held reservations (successful holds): 1" in output
    assert "invariants hold" in output


@pytest.mark.django_db
def test_report_fails_loudly_if_claims_and_reservations_disagree() -> None:
    event = make_event()
    (seat,) = make_seats(event, 1)
    reservation = hold_seats(user=make_user(1), event=event, seat_ids=[seat.id])
    reservation.status = ReservationStatus.CANCELLED
    reservation.save(update_fields=["status"])  # live claim under a dead reservation
    with pytest.raises(CommandError, match="INCONSISTENT"):
        run("loadtest_report", event.id)


@override_settings(SEAT_GATE_ENABLED=False)
def test_a_disabled_gate_claims_nothing_and_touches_no_keys() -> None:
    claim = gate.claim([1, 2])
    assert claim.ok
    gate.extend(claim)
    gate.release(claim)
    assert not get_client().exists(f"{gate.PREFIX}1", f"{gate.PREFIX}2")
