"""gunicorn settings that make Prometheus metrics correct with several worker processes."""

import os
from pathlib import Path

from prometheus_client import multiprocess

_METRICS_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")


def on_starting(server: object) -> None:
    """Start from a clean slate: stale files from a previous run would double-count."""
    if _METRICS_DIR:
        directory = Path(_METRICS_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        for leftover in directory.glob("*.db"):
            leftover.unlink()


def child_exit(server, worker):
    """A worker died or was recycled: stop its gauges from lingering in the totals."""
    if _METRICS_DIR:
        multiprocess.mark_process_dead(worker.pid)
