"""The one shared Redis client for the whole app."""

from __future__ import annotations

from functools import lru_cache

import redis
from django.conf import settings


@lru_cache(maxsize=1)
def get_client() -> redis.Redis:
    """One shared client (it manages its own connection pool). Short timeouts: fail fast."""
    return redis.Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
        decode_responses=True,
    )
