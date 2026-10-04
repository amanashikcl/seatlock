"""Record request count and latency for every view, labelled by URL *template*."""

from __future__ import annotations

import time
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.metrics import HTTP_LATENCY, HTTP_REQUESTS

UNMATCHED = "unmatched"  # 404s: a bot probing random paths must not create endless label values
SKIPPED_ROUTES = {"metrics"}  # scraping itself is not interesting traffic


class MetricsMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed = time.perf_counter() - started

        match = request.resolver_match
        route = match.route if match is not None and match.route else UNMATCHED
        if route in SKIPPED_ROUTES:
            return response
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(elapsed)
        return response
