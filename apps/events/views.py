from __future__ import annotations

from typing import Any

from rest_framework import generics, permissions

from apps.accounts.permissions import IsOrganizer
from apps.events.models import Event
from apps.events.permissions import IsOwnerOrAdmin
from apps.events.serializers import EventSerializer


class EventListCreateView(generics.ListCreateAPIView):
    """List events (any logged-in user); create one (organizers and admins)."""

    serializer_class = EventSerializer
    # Explicit tiebreaker: ties in starts_at would make page boundaries unstable.
    queryset = Event.objects.order_by("starts_at", "id")

    def get_permissions(self) -> list[Any]:
        if self.request.method == "POST":
            return [IsOrganizer()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer: Any) -> None:
        serializer.save(organizer=self.request.user)  # never trust a client-supplied organizer


class EventDetailView(generics.RetrieveUpdateAPIView):
    """Read an event (any logged-in user); PATCH it (its organizer or an admin)."""

    serializer_class = EventSerializer
    queryset = Event.objects.all()
    http_method_names = ["get", "patch", "head", "options"]  # no PUT, no DELETE

    def get_permissions(self) -> list[Any]:
        if self.request.method == "PATCH":
            return [IsOrganizer(), IsOwnerOrAdmin()]
        return [permissions.IsAuthenticated()]
