"""Celery tasks. Thin wrappers: the real logic lives in plain, separately tested functions."""

from __future__ import annotations

from celery import shared_task

from apps.reservations.expiry import DEFAULT_BATCH_SIZE, expire_holds

BATCH_SIZE = DEFAULT_BATCH_SIZE
MAX_BATCHES_PER_RUN = 100  # safety cap so one run cannot loop forever


@shared_task(name="apps.reservations.tasks.expire_lapsed_holds", ignore_result=True)
def expire_lapsed_holds() -> int:
    """Release every lapsed hold, one short transaction per batch. Returns the total.

    Idempotent, so it is safe under acks_late redelivery or an accidental double run.
    """
    total = 0
    for _ in range(MAX_BATCHES_PER_RUN):
        expired = expire_holds(batch_size=BATCH_SIZE)
        total += expired
        if expired < BATCH_SIZE:  # a partial batch means nothing is left
            break
    return total
