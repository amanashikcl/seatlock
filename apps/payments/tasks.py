"""Celery task wrapping the replay sweeper."""

from __future__ import annotations

from celery import shared_task

from apps.payments.replay import replay_unprocessed


@shared_task(name="apps.payments.tasks.replay_stuck_webhooks", ignore_result=True)
def replay_stuck_webhooks() -> int:
    """One batch per run; the schedule makes it recur. Returns how many events finished."""
    return replay_unprocessed()
