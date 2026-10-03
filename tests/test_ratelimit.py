import pytest
import redis

from apps.core import ratelimit
from apps.core.ratelimit import check_rate_limit, get_client


def test_requests_within_the_limit_are_allowed_then_blocked() -> None:
    results = [check_rate_limit("rl:t:a", limit=3, window_seconds=60) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert 1 <= results[-1].retry_after <= 60


def test_keys_are_counted_independently() -> None:
    check_rate_limit("rl:t:a", limit=1, window_seconds=60)
    assert not check_rate_limit("rl:t:a", limit=1, window_seconds=60).allowed
    assert check_rate_limit("rl:t:b", limit=1, window_seconds=60).allowed


def test_the_counter_always_has_an_expiry() -> None:
    check_rate_limit("rl:t:a", limit=1, window_seconds=60)
    assert 0 < get_client().ttl("rl:t:a") <= 60


def test_a_counter_missing_its_expiry_is_repaired() -> None:
    get_client().set("rl:t:a", 5)  # simulates a key left without a TTL
    check_rate_limit("rl:t:a", limit=1, window_seconds=60)
    assert get_client().ttl("rl:t:a") > 0


def test_redis_outage_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1)
    monkeypatch.setattr(ratelimit, "get_client", lambda: dead)
    decision = check_rate_limit("rl:t:a", limit=1, window_seconds=60)
    assert decision.allowed
