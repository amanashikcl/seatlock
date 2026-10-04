"""Fixed-window rate limiting on Redis. One atomic Lua script, fail-open on Redis trouble."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

import redis

from apps.core.redis_client import get_client

logger = logging.getLogger(__name__)

# Runs inside Redis as ONE indivisible step: count the hit, start the window on the first
# hit, and report the time left. Two separate commands (INCR, then EXPIRE) could be split by a
# crash and leave a counter that never expires, locking the user out forever.
_HIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if count == 1 or ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int  # seconds until the window resets (0 when allowed)


def check_rate_limit(key: str, *, limit: int, window_seconds: int) -> Decision:
    """Count one request against `key`. Allowed while the count is within `limit`.

    Fails OPEN: if Redis is unreachable we allow the request and log it. Seat correctness is
    enforced by Postgres, so the limiter is protection, not a safety net; failing closed would
    turn a cache outage into a full outage of the sale.
    """
    try:
        raw = get_client().eval(_HIT_SCRIPT, 1, key, window_seconds)
    except redis.RedisError:
        logger.exception("rate limiter unavailable; allowing request (fail-open)")
        return Decision(allowed=True, retry_after=0)
    count, ttl = cast("list[int]", raw)
    if count <= limit:
        return Decision(allowed=True, retry_after=0)
    return Decision(allowed=False, retry_after=max(ttl, 1))
