from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.events.models import Event
from apps.payments import replay, tasks
from apps.payments.models import WebhookEvent, WebhookStatus
from apps.payments.processing import PAYMENT_SUCCEEDED, process_event, record_event
from apps.reservations.models import ReservationStatus
from tests.factories import make_event, make_hold


@pytest.fixture
def event() -> Event:
    return make_event()


def stuck(evt_id: str, reservation_id: object, age: timedelta) -> WebhookEvent:
    """A stored-but-unprocessed event that arrived `age` ago."""
    body: dict[str, Any] = {"data": {"reservation_id": str(reservation_id), "amount_cents": 5000}}
    evt, _ = record_event(provider_event_id=evt_id, event_type=PAYMENT_SUCCEEDED, payload=body)
    WebhookEvent.objects.filter(pk=evt.pk).update(received_at=timezone.now() - age)
    return evt


@pytest.mark.django_db
def test_old_unprocessed_event_is_applied(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    evt = stuck("evt_1", hold.id, timedelta(minutes=5))
    assert replay.replay_unprocessed() == 1
    evt.refresh_from_db()
    hold.refresh_from_db()
    assert evt.status == WebhookStatus.PROCESSED
    assert hold.status == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_recent_events_are_left_for_the_original_request(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    evt = stuck("evt_1", hold.id, timedelta(seconds=5))
    assert replay.replay_unprocessed() == 0
    evt.refresh_from_db()
    assert evt.status == WebhookStatus.RECEIVED


@pytest.mark.django_db
def test_finished_events_are_not_touched(event: Event) -> None:
    hold = make_hold(event, 1, seconds_past_expiry=-300)
    evt = stuck("evt_1", hold.id, timedelta(minutes=5))
    WebhookEvent.objects.filter(pk=evt.pk).update(status=WebhookStatus.FAILED, detail="x")
    assert replay.replay_unprocessed() == 0
    evt.refresh_from_db()
    assert evt.detail == "x"


@pytest.mark.django_db
def test_one_failing_event_does_not_block_the_rest(
    event: Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = stuck("evt_bad", make_hold(event, 1, seconds_past_expiry=-300).id, timedelta(minutes=9))
    good = stuck("evt_good", make_hold(event, 2, seconds_past_expiry=-300).id, timedelta(minutes=5))

    def flaky(evt: WebhookEvent, **kwargs: Any) -> WebhookEvent:
        if evt.provider_event_id == "evt_bad":
            raise RuntimeError("boom")
        return process_event(evt, **kwargs)

    monkeypatch.setattr("apps.payments.replay.process_event", flaky)
    assert replay.replay_unprocessed() == 1
    bad.refresh_from_db()
    good.refresh_from_db()
    assert bad.status == WebhookStatus.RECEIVED  # retried on the next run
    assert good.status == WebhookStatus.PROCESSED


@pytest.mark.django_db
def test_batch_size_limits_work_per_run(event: Event) -> None:
    for n in (1, 2, 3):
        stuck(f"evt_{n}", make_hold(event, n, seconds_past_expiry=-300).id, timedelta(minutes=5))
    assert replay.replay_unprocessed(batch_size=2) == 2
    assert tasks.replay_stuck_webhooks() == 1  # the task picks up the remainder
