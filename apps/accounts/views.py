from __future__ import annotations

from typing import Any, cast

from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.accounts.serializers import (
    RegisterSerializer,
    RoleUpdateSerializer,
    UserSerializer,
)


class RegisterView(generics.CreateAPIView):
    """Public endpoint: create a customer account."""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list[type] = []  # public: a stale token must not cause a 401


class MeView(generics.RetrieveAPIView):
    """Return the authenticated user."""

    serializer_class = UserSerializer

    def get_object(self) -> User:
        return cast(User, self.request.user)


class UserRoleView(generics.UpdateAPIView):
    """Admin-only: promote or demote a user. This is how organizers are created."""

    queryset = User.objects.all()
    serializer_class = RoleUpdateSerializer
    permission_classes = [IsAdmin]
    http_method_names = ["patch", "options"]

    def perform_update(self, serializer: Any) -> None:
        if serializer.instance.pk == self.request.user.pk:
            # Prevents locking the platform out of its last admin by accident.
            raise ValidationError("Admins cannot change their own role.")
        serializer.save()
