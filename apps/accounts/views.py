from __future__ import annotations

from typing import cast

from rest_framework import generics, permissions

from apps.accounts.models import User
from apps.accounts.serializers import RegisterSerializer, UserSerializer


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
