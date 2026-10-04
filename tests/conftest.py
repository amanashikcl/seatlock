from collections.abc import Iterator

import pytest
import redis

from apps.core.redis_client import get_client


@pytest.fixture(autouse=True)
def clean_rate_limit_keys() -> Iterator[None]:
    """Redis state lives outside the test database, so clear it around every test."""

    def clear() -> None:
        try:
            client = get_client()
            for pattern in ("rl:*", "seatgate:*"):
                for key in client.scan_iter(pattern):
                    client.delete(key)
        except redis.RedisError:
            pass  # no Redis: only the tests that need it will fail, and say why

    clear()
    yield
    clear()
