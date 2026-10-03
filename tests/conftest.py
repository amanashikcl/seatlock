from collections.abc import Iterator

import pytest
import redis

from apps.core.ratelimit import get_client


@pytest.fixture(autouse=True)
def clean_rate_limit_keys() -> Iterator[None]:
    """Counters live in Redis, outside the test database, so clear them around every test."""

    def clear() -> None:
        try:
            client = get_client()
            for key in client.scan_iter("rl:*"):
                client.delete(key)
        except redis.RedisError:
            pass  # no Redis: only the tests that need it will fail, and say why

    clear()
    yield
    clear()
