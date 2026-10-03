from __future__ import annotations

from rest_framework import serializers

from apps.events.models import Seat
from apps.reservations.models import Reservation
from apps.reservations.services import MAX_SEATS_PER_RESERVATION


class SeatAvailabilitySerializer(serializers.ModelSerializer):
    """A seat plus `available`, computed by the query (no stored flag to drift)."""

    available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Seat
        fields = ["id", "section", "row", "number", "price_cents", "available"]
        read_only_fields = fields


class HoldRequestSerializer(serializers.Serializer):
    """Only checks the *shape* of the request. Business rules live in the service."""

    seat_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=MAX_SEATS_PER_RESERVATION,
    )


class ReservationSerializer(serializers.ModelSerializer):
    seat_ids = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = ["id", "event", "status", "total_cents", "expires_at", "seat_ids"]
        read_only_fields = fields

    def get_seat_ids(self, obj: Reservation) -> list[int]:
        return sorted(obj.items.values_list("seat_id", flat=True))
