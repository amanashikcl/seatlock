"""Prometheus metrics: what the system is doing, in numbers a dashboard or alert can use.

Rules for adding a metric: labels must have few, fixed values (never a user id, seat id or
raw URL: every distinct label value creates a new time series and memory grows without bound).
"""

from __future__ import annotations

import os

from django.http import HttpRequest, HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

HOLDS = Counter(
    "seatlock_holds_total",
    "Seat hold attempts by outcome.",
    ["outcome"],  # created | gate_rejected | seat_unavailable | sales_not_open | invalid_selection
)

WEBHOOKS = Counter(
    "seatlock_webhook_events_total",
    "Payment webhook deliveries by result.",
    ["result"],  # processed | failed | received | duplicate | bad_signature | bad_payload
)

HTTP_REQUESTS = Counter(
    "seatlock_http_requests_total",
    "HTTP requests by method, route template and status code.",
    ["method", "route", "status"],
)

HTTP_LATENCY = Histogram(
    "seatlock_http_request_seconds",
    "HTTP request latency by method and route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def metrics_view(request: HttpRequest) -> HttpResponse:
    """Expose all metrics in Prometheus text format.

    gunicorn runs several worker processes and each has its own memory. In multiprocess mode
    (PROMETHEUS_MULTIPROC_DIR set) every process writes its numbers to files, and this view
    merges them, so a scrape sees the whole service and not whichever worker answered.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        payload = generate_latest(registry)
    else:
        payload = generate_latest()
    return HttpResponse(payload, content_type=CONTENT_TYPE_LATEST)
