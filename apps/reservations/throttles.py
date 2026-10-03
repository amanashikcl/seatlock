from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.throttling import BaseThrottle

from apps.core.ratelimit import check_rate_limit


class HoldRateThrottle(BaseThrottle):
    """Limit how often one signed-in user may try to hold seats (stops scripts hammering).

    Keyed by user id, not IP: the endpoint requires login, and many real users can share one
    IP (offices, mobile carriers) while one script can rotate IPs.
    """

    def __init__(self) -> None:
        self._retry_after = 0

    def allow_request(self, request: Any, view: Any) -> bool:
        decision = check_rate_limit(
            f"rl:holds:{request.user.pk}",
            limit=settings.HOLD_RATE_LIMIT,
            window_seconds=settings.HOLD_RATE_WINDOW_SECONDS,
        )
        self._retry_after = decision.retry_after
        return decision.allowed

    def wait(self) -> float | None:
        return float(self._retry_after) or None
