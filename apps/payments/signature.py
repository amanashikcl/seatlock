"""HMAC-SHA256 webhook signatures with a timestamp window (header: `t=<unix>,v1=<hex>`)."""

from __future__ import annotations

import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300  # reject signatures older (or newer) than 5 minutes: stops replays


class InvalidSignature(Exception):
    """The signature header is missing, malformed, stale or does not match the body."""


def _digest(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.".encode() + payload  # the timestamp is part of what is signed
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def sign(payload: bytes, secret: str, *, timestamp: int | None = None) -> str:
    """Build a signature header (used by the mock provider and by tests)."""
    if not secret:
        raise ValueError("secret must not be empty")
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},v1={_digest(payload, secret, ts)}"


def verify(
    payload: bytes,
    header: str,
    secret: str,
    *,
    now: int | None = None,
    tolerance: int = TOLERANCE_SECONDS,
) -> None:
    """Raise InvalidSignature unless `header` is a fresh, correct signature of `payload`."""
    if not secret:
        raise ValueError("secret must not be empty")  # misconfiguration must be loud
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        received = parts["v1"]
    except (ValueError, KeyError) as exc:
        raise InvalidSignature("malformed signature header") from exc

    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance:
        raise InvalidSignature("timestamp outside the allowed window")
    # compare_digest takes the same time however many leading characters match.
    if not hmac.compare_digest(_digest(payload, secret, timestamp), received):
        raise InvalidSignature("signature does not match")
