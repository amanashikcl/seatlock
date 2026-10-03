from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.events.models import Event


class EventSerializer(serializers.ModelSerializer):
    """Public representation of an event. `organizer` is set by the server, never the client."""

    class Meta:
        model = Event
        fields = ["id", "name", "venue", "starts_at", "sales_open_at", "organizer", "created_at"]
        read_only_fields = ["id", "organizer", "created_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # On PATCH, combine new values with the stored ones so changing one date cannot
        # produce an invalid pair. The DB CHECK constraint remains the final guarantee.
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        sales_open_at = attrs.get("sales_open_at", getattr(self.instance, "sales_open_at", None))
        if starts_at and sales_open_at and sales_open_at >= starts_at:
            raise serializers.ValidationError(
                {"sales_open_at": "Ticket sales must open before the event starts."}
            )
        return attrs
