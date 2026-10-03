from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.reservations import tasks
from apps.reservations.models import Reservation, ReservationStatus
from apps.reservations.services import hold_seats
from config.celery import app
from tests.factories import make_event, make_seats, make_user


@pytest.mark.django_db
def test_task_drains_every_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "BATCH_SIZE", 2)
    event = make_event()
    placed_at = timezone.now() - timedelta(minutes=20)
    for n, seat in enumerate(make_seats(event, 5)):
        hold_seats(user=make_user(n), event=event, seat_ids=[seat.id], now=placed_at)
    assert tasks.expire_lapsed_holds() == 5  # 2 + 2 + 1 across three batches
    assert not Reservation.objects.filter(status=ReservationStatus.HELD).exists()


@pytest.mark.django_db
def test_task_with_nothing_to_do_returns_zero() -> None:
    assert tasks.expire_lapsed_holds() == 0


def test_every_beat_schedule_entry_points_at_a_registered_task() -> None:
    # A typo here fails silently in production: the worker just discards the message.
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        assert entry["task"] in app.tasks, f"{name} schedules unknown task {entry['task']}"
