from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from apps.accounts.roles import Role


class IsOwnerOrAdmin(BasePermission):
    """Object-level: only an event's own organizer, or an admin, may modify it.

    Role checks alone would let organizer A edit organizer B's event (an IDOR bug).
    """

    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        user = request.user
        return bool(user.role == Role.ADMIN or obj.organizer_id == user.id)
