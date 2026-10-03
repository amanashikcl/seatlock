from __future__ import annotations

from django.db import models
from django.db.models import Q


class WebhookStatus(models.TextChoices):
    RECEIVED = "received", "Received"  # stored, not yet (fully) processed
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"  # business problem; needs a human or a refund job


class WebhookEvent(models.Model):
    """Every webhook we accept, stored exactly once before we act on it."""

    # UNIQUE: the database, not Python, decides whether we have seen this event before.
    provider_event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    status = models.CharField(
        max_length=20, choices=WebhookStatus.choices, default=WebhookStatus.RECEIVED
    )
    detail = models.CharField(max_length=200, blank=True)  # why it failed, or a note
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=WebhookStatus.values), name="webhook_status_valid"
            ),
        ]
        indexes = [
            # The replay job looks for unfinished events; index only those.
            models.Index(
                fields=["received_at"],
                condition=Q(status=WebhookStatus.RECEIVED),
                name="webhook_unprocessed_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider_event_id} ({self.status})"
