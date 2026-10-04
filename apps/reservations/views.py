from __future__ import annotations

from typing import Any

from django.db.models import Exists, OuterRef, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.metrics import HOLDS
from apps.events.models import Event, Seat
from apps.reservations import gate
from apps.reservations.models import ReservationSeat
from apps.reservations.pagination import SeatPagination
from apps.reservations.serializers import (
    HoldRequestSerializer,
    ReservationSerializer,
    SeatAvailabilitySerializer,
)
from apps.reservations.services import (
    InvalidSeatSelection,
    SalesNotOpen,
    SeatUnavailable,
    hold_seats,
)
from apps.reservations.throttles import HoldRateThrottle


def error(code: str, detail: str, http_status: int, **extra: Any) -> Response:
    """Uniform error body: a stable machine-readable `code` plus a human `detail`."""
    return Response({"code": code, "detail": detail, **extra}, status=http_status)


class EventSeatListView(generics.ListAPIView):
    """Seat map for an event. `available` means no active claim exists on the seat."""

    serializer_class = SeatAvailabilitySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SeatPagination

    def get_queryset(self) -> QuerySet[Seat]:
        event = get_object_or_404(Event, pk=self.kwargs["event_id"])
        active_claim = ReservationSeat.objects.filter(seat=OuterRef("pk"), is_active=True)
        return (
            Seat.objects.filter(event=event)
            .annotate(available=~Exists(active_claim))
            .order_by("section", "row", "number")
        )


class HoldSeatsView(APIView):
    """Hold seats for the authenticated user. All business rules live in `hold_seats`."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [HoldRateThrottle]

    def post(self, request: Any, event_id: int) -> Response:
        event = get_object_or_404(Event, pk=event_id)
        body = HoldRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        seat_ids = body.validated_data["seat_ids"]

        # Fast path: Redis says someone already has these seats -> no database work at all.
        claim = gate.claim(seat_ids)
        if not claim.ok:
            HOLDS.labels("gate_rejected").inc()
            return error(
                "seat_unavailable",
                "One or more seats are not available",
                status.HTTP_409_CONFLICT,
                seat_ids=list(claim.conflicts),
            )
        try:
            reservation = hold_seats(user=request.user, event=event, seat_ids=seat_ids)
        except SeatUnavailable as exc:
            HOLDS.labels("seat_unavailable").inc()
            gate.release(claim)
            return error(
                "seat_unavailable", str(exc), status.HTTP_409_CONFLICT, seat_ids=exc.seat_ids
            )
        except SalesNotOpen as exc:
            HOLDS.labels("sales_not_open").inc()
            gate.release(claim)
            return error("sales_not_open", str(exc), status.HTTP_409_CONFLICT)
        except InvalidSeatSelection as exc:
            HOLDS.labels("invalid_selection").inc()
            gate.release(claim)
            return error("invalid_selection", str(exc), status.HTTP_400_BAD_REQUEST)
        except Exception:
            gate.release(claim)  # never leave seats blocked because of our own bug
            raise
        HOLDS.labels("created").inc()
        gate.extend(claim)
        return Response(ReservationSerializer(reservation).data, status=status.HTTP_201_CREATED)
