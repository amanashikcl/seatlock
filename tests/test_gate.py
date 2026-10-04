import time

import pytest
import redis

from apps.core.redis_client import get_client
from apps.reservations import gate
from apps.reservations.services import HOLD_DURATION


def key(seat_id: int) -> str:
    return f"{gate.PREFIX}{seat_id}"


def test_free_seats_are_claimed_with_a_short_in_flight_ttl() -> None:
    claim = gate.claim([1, 2])
    assert claim.ok
    assert 0 < get_client().ttl(key(1)) <= gate.IN_FLIGHT_TTL_SECONDS


def test_a_taken_seat_is_reported_and_nothing_else_is_claimed() -> None:
    gate.claim([2])
    second = gate.claim([1, 2, 3])
    assert second.conflicts == (2,)
    assert not get_client().exists(key(1), key(3))  # all-or-nothing: no partial claim


def test_release_frees_the_seats() -> None:
    claim = gate.claim([1])
    gate.release(claim)
    assert gate.claim([1]).ok


def test_release_never_deletes_someone_elses_claim() -> None:
    mine = gate.claim([1])
    get_client().delete(key(1))  # my claim lapsed ...
    theirs = gate.claim([1])  # ... and another buyer took the seat
    gate.release(mine)
    assert get_client().get(key(1)) == theirs.token


def test_extend_keeps_the_claim_until_the_hold_would_expire() -> None:
    claim = gate.claim([1])
    gate.extend(claim)
    ttl = get_client().ttl(key(1))
    assert HOLD_DURATION.total_seconds() - 5 < ttl <= HOLD_DURATION.total_seconds()


def test_extend_never_touches_someone_elses_claim() -> None:
    mine = gate.claim([1])
    get_client().delete(key(1))
    theirs = gate.claim([1])
    gate.extend(mine)
    assert get_client().ttl(key(1)) <= gate.IN_FLIGHT_TTL_SECONDS
    assert get_client().get(key(1)) == theirs.token


def test_a_crashed_claim_heals_itself_when_the_ttl_ends() -> None:
    gate.claim([1])  # claimed, then the process "died": nobody releases or extends it
    get_client().pexpire(key(1), 1)  # fast-forward: the in-flight TTL runs out
    time.sleep(0.05)
    assert gate.claim([1]).ok


def test_sold_seats_block_claims_and_survive_release() -> None:
    gate.mark_sold([1])
    claim = gate.claim([1])
    assert claim.conflicts == (1,)
    gate.release(claim)
    assert get_client().get(key(1)) == gate.SOLD_MARKER


def test_duplicate_ids_do_not_conflict_with_themselves() -> None:
    assert gate.claim([4, 4, 5]).ok


def test_redis_outage_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1)
    monkeypatch.setattr(gate, "get_client", lambda: dead)
    claim = gate.claim([1])
    assert claim.ok  # the gate steps aside; Postgres still decides
    gate.extend(claim)
    gate.release(claim)
    gate.mark_sold([1])  # none of these raise


def test_forget_clears_keys_whatever_their_owner() -> None:
    gate.claim([1, 2])
    gate.forget([1, 2, 3])
    assert not get_client().exists(key(1), key(2))
    gate.forget([])  # nothing to do, must not fail
