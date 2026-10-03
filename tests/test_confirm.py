import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connections
from django.utils import timezone

from apps.events.models import Event, Seat
from apps.reservations.confirmation import (
    PaymentAmountMismatch,
    ReservationNotConfirmable,
    ReservationNotFound,
    confirm_reservation,
)
from apps.reservations.expiry import expire_holds
from apps.reservations.models import Reservation, ReservationStatus
from apps.reservations.services import HOLD_DURATION, hold_seats
from tests.factories import make_event, make_user


@pytest.fixture
def event() -> Event:
    return make_event()


def make_hold(event: Event, n: int, seconds_past_expiry: int) -> Reservation:
    """A hold whose window ended `seconds_past_expiry` ago (negative: still running)."""
    seat = Seat.objects.create(event=event, section="B", row="1", number=n, price_cents=5000)
    placed_at = timezone.now() - HOLD_DURATION - timedelta(seconds=seconds_past_expiry)
    return hold_seats(user=make_user(n), event=event, seat_ids=[seat.id], now=placed_at)


@pytest.mark.django_db
def test_confirming_a_live_hold_marks_it_confirmed_and_keeps_the_seats(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    confirmed = confirm_reservation(reservation_id=hold.id)
    assert confirmed.status == ReservationStatus.CONFIRMED
    assert hold.items.filter(is_active=True).count() == 1


@pytest.mark.django_db
def test_confirming_twice_is_harmless(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    confirm_reservation(reservation_id=hold.id)
    again = confirm_reservation(reservation_id=hold.id)  # duplicate webhook delivery
    assert again.status == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_unknown_reservation_raises_not_found() -> None:
    with pytest.raises(ReservationNotFound):
        confirm_reservation(reservation_id=uuid.uuid4())


@pytest.mark.django_db
def test_payment_just_after_the_hold_lapsed_is_accepted_within_the_grace_period(
    event: Event,
) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=30)  # lapsed 30s ago, grace is 60s
    assert expire_holds() == 0  # the sweeper leaves it alone during the grace period
    assert confirm_reservation(reservation_id=hold.id).status == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_payment_after_the_grace_period_is_rejected_even_before_the_sweeper_runs(
    event: Event,
) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=120)
    with pytest.raises(ReservationNotConfirmable) as excinfo:
        confirm_reservation(reservation_id=hold.id)
    assert excinfo.value.reason == "late"
    hold.refresh_from_db()
    assert hold.status == ReservationStatus.HELD  # untouched; the sweeper will release it
    assert expire_holds() == 1


@pytest.mark.django_db
def test_payment_for_an_already_expired_reservation_is_rejected(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=120)
    expire_holds()
    with pytest.raises(ReservationNotConfirmable) as excinfo:
        confirm_reservation(reservation_id=hold.id)
    assert excinfo.value.reason == "expired"
    assert hold.items.filter(is_active=True).count() == 0


@pytest.mark.django_db
def test_cancelled_reservation_cannot_be_confirmed(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    Reservation.objects.filter(id=hold.id).update(status=ReservationStatus.CANCELLED)
    with pytest.raises(ReservationNotConfirmable) as excinfo:
        confirm_reservation(reservation_id=hold.id)
    assert excinfo.value.reason == "cancelled"


@pytest.mark.django_db(transaction=True)
def test_confirm_racing_the_sweeper_never_leaves_an_inconsistent_reservation(
    event: Event,
) -> None:
    holds = [make_hold(event, n, seconds_past_expiry=120) for n in range(1, 11)]
    barrier = threading.Barrier(len(holds) + 2, timeout=30)

    def confirm(hold: Reservation) -> int:
        try:
            barrier.wait()
            # Simulates clock skew: this caller still believes the hold is inside its grace.
            confirm_reservation(reservation_id=hold.id, now=hold.expires_at)
            return 1
        except ReservationNotConfirmable:
            return 0
        finally:
            connections.close_all()

    def sweep() -> int:
        try:
            barrier.wait()
            return expire_holds()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(holds) + 2) as pool:
        confirm_futures = [pool.submit(confirm, hold) for hold in holds]
        sweep_futures = [pool.submit(sweep) for _ in range(2)]
        confirmed = sum(f.result() for f in confirm_futures)
        expired = sum(f.result() for f in sweep_futures)

    assert confirmed + expired == len(holds)  # every hold ended up exactly one way
    for hold in holds:
        hold.refresh_from_db()
        active = hold.items.filter(is_active=True).count()
        paid = hold.status == ReservationStatus.CONFIRMED and active == 1
        released = hold.status == ReservationStatus.EXPIRED and active == 0
        assert paid or released


@pytest.mark.django_db
def test_wrong_paid_amount_is_rejected_and_nothing_changes(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    with pytest.raises(PaymentAmountMismatch):
        confirm_reservation(reservation_id=hold.id, paid_cents=4999)
    hold.refresh_from_db()
    assert hold.status == ReservationStatus.HELD


@pytest.mark.django_db
def test_correct_paid_amount_confirms(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    confirmed = confirm_reservation(reservation_id=hold.id, paid_cents=5000)
    assert confirmed.status == ReservationStatus.CONFIRMED
