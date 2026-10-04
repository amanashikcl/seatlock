"""Redis seat gate: a cheap pre-check that turns away obviously-taken seats before Postgres.

The gate is a HINT, never the truth. Postgres decides who owns a seat. The gate may be wrong
in two ways, and both are safe:
  * missing key (Redis restarted, key expired): the request falls through to Postgres, which
    answers correctly, just without the speed-up;
  * stale key (a process died after claiming): self-heals when the short in-flight TTL ends.
If Redis is down the gate steps aside (fail-open).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import redis

from apps.core.redis_client import get_client
from apps.reservations.services import HOLD_DURATION

logger = logging.getLogger(__name__)

PREFIX = "seatgate:"
IN_FLIGHT_TTL_SECONDS = 30  # while the DB transaction runs: a crash blocks a seat this long
SOLD_TTL_SECONDS = 24 * 60 * 60
SOLD_MARKER = "sold"  # never equals a claim token, so release/extend leave it alone

# All-or-nothing, atomically: if any seat is already claimed, claim nothing and report which.
_CLAIM = """
local conflicts = {}
for i, key in ipairs(KEYS) do
  if redis.call('EXISTS', key) == 1 then conflicts[#conflicts + 1] = i end
end
if #conflicts > 0 then return conflicts end
for _, key in ipairs(KEYS) do redis.call('SET', key, ARGV[1], 'EX', ARGV[2]) end
return conflicts
"""

# Only touch keys that still hold OUR token. After our TTL lapses another buyer may have
# claimed the seat; deleting or extending their key would break their claim.
_RELEASE = """
for _, key in ipairs(KEYS) do
  if redis.call('GET', key) == ARGV[1] then redis.call('DEL', key) end
end
return 1
"""
_EXTEND = """
for _, key in ipairs(KEYS) do
  if redis.call('GET', key) == ARGV[1] then redis.call('EXPIRE', key, ARGV[2]) end
end
return 1
"""


@dataclass(frozen=True)
class Claim:
    token: str
    seat_ids: tuple[int, ...]
    conflicts: tuple[int, ...]  # seats already claimed by someone else; empty means we hold all

    @property
    def ok(self) -> bool:
        return not self.conflicts


def _keys(seat_ids: Sequence[int]) -> list[str]:
    return [f"{PREFIX}{seat_id}" for seat_id in seat_ids]


def claim(seat_ids: Sequence[int]) -> Claim:
    """Try to claim every seat for the short in-flight window."""
    ids = tuple(sorted(set(seat_ids)))  # sorted + unique: stable, and no self-conflict
    token = uuid.uuid4().hex
    try:
        raw = get_client().eval(_CLAIM, len(ids), *_keys(ids), token, IN_FLIGHT_TTL_SECONDS)
    except redis.RedisError:
        logger.exception("seat gate unavailable; skipping it (fail-open)")
        return Claim(token=token, seat_ids=ids, conflicts=())
    indexes = cast("list[int]", raw)
    return Claim(token=token, seat_ids=ids, conflicts=tuple(ids[i - 1] for i in indexes))


def release(claim_: Claim) -> None:
    """Give the seats back (the DB refused the hold). Best effort: the TTL is the backstop."""
    _run(_RELEASE, claim_, claim_.token)


def extend(claim_: Claim) -> None:
    """The DB committed the hold: keep the claim until the hold itself would expire."""
    _run(_EXTEND, claim_, claim_.token, int(HOLD_DURATION.total_seconds()))


def mark_sold(seat_ids: Sequence[int]) -> None:
    """A payment confirmed these seats: keep turning buyers away from them cheaply."""
    ids = sorted(set(seat_ids))
    if not ids:
        return
    try:
        client = get_client()
        with client.pipeline() as pipe:
            for key in _keys(ids):
                pipe.set(key, SOLD_MARKER, ex=SOLD_TTL_SECONDS)
            pipe.execute()
    except redis.RedisError:
        logger.exception("could not mark seats sold in the gate (harmless: DB is the truth)")


def forget(seat_ids: Sequence[int]) -> None:
    """The database released these seats (hold expired): drop their gate keys at once.

    Plain delete, no token check: the real owner is gone. Deleting a brand-new claim by
    mistake only costs a missed hint, which is the safe direction.
    """
    ids = sorted(set(seat_ids))
    if not ids:
        return
    try:
        with get_client().pipeline() as pipe:
            for key in _keys(ids):
                pipe.delete(key)
            pipe.execute()
    except redis.RedisError:
        logger.exception("could not clear gate keys for expired holds; their TTL will")


def _run(script: str, claim_: Claim, *args: str | int) -> None:
    if not claim_.seat_ids:
        return
    try:
        get_client().eval(script, len(claim_.seat_ids), *_keys(claim_.seat_ids), *args)
    except redis.RedisError:
        logger.exception("seat gate cleanup failed; the TTL will clear it")
