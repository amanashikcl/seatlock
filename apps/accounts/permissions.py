from __future__ import annotations

from typing import Any, ClassVar

from rest_framework.permissions import BasePermission

from apps.accounts.roles import Role


class HasRole(BasePermission):
    """Allow only authenticated users whose role is in `allowed_roles`."""

    allowed_roles: ClassVar[frozenset[str]] = frozenset()

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.role in self.allowed_roles)


class IsOrganizer(HasRole):
    """Organizers, plus admins (an admin can do anything an organizer can)."""

    allowed_roles = frozenset({Role.ORGANIZER, Role.ADMIN})


class IsAdmin(HasRole):
    allowed_roles = frozenset({Role.ADMIN})
