"""Liveness and readiness probes."""

from __future__ import annotations

import logging
import socket
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0


def check_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def check_tcp(url: str) -> None:

    parsed = urlparse(url)
    if not parsed.hostname or not parsed.port:
        raise ValueError("URL must include host and port")
    with socket.create_connection((parsed.hostname, parsed.port), timeout=CHECK_TIMEOUT_SECONDS):
        pass


def check_redis() -> None:
    check_tcp(settings.REDIS_URL)


def check_broker() -> None:
    check_tcp(settings.CELERY_BROKER_URL)


def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def readyz(request: HttpRequest) -> JsonResponse:
    checks = {"database": check_database, "redis": check_redis, "broker": check_broker}
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            results[name] = "ok"
        except Exception:
            logger.exception("readiness check failed: %s", name)
            results[name] = "fail"
    ready = all(v == "ok" for v in results.values())
    return JsonResponse(
        {"status": "ok" if ready else "unavailable", "checks": results},
        status=200 if ready else 503,
    )
