"""Metadata-only periodic telemetry for the Achievements Sheets broker."""

from __future__ import annotations

import logging
import threading
from typing import Any, Mapping

from achievements.sheets_read_broker import broker

log = logging.getLogger("c1c-claims.sheets.telemetry")

_INITIAL_DELAY_SECONDS = 60.0
_INTERVAL_SECONDS = 300.0
_COUNTER_KEYS = (
    "physical_reads",
    "cache_hits",
    "stale_hits",
    "coalesced_joins",
    "cache_misses",
    "retries",
    "rate_limit_errors",
    "invalidations",
)

_START_LOCK = threading.Lock()
_STARTED = False


def interval_metrics(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, int | float]:
    """Return non-negative interval deltas plus physical-read avoidance share."""

    out: dict[str, int | float] = {}
    for key in _COUNTER_KEYS:
        before = int(previous.get(key, 0) or 0)
        after = int(current.get(key, 0) or 0)
        out[key] = max(0, after - before)

    avoided = (
        int(out["cache_hits"])
        + int(out["stale_hits"])
        + int(out["coalesced_joins"])
    )
    physical = int(out["physical_reads"])
    served = avoided + physical
    out["avoided_read_share_pct"] = (
        round((avoided / served) * 100.0, 1) if served else 0.0
    )
    return out


def _emit(previous: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    delta = interval_metrics(previous, current)
    log.info(
        "Sheets broker interval: budget_rpm=%s physical_reads=%s cache_hits=%s "
        "stale_hits=%s coalesced=%s misses=%s retries=%s rate_limits=%s "
        "invalidations=%s avoided_read_share_pct=%.1f cache_entries=%s "
        "inflight=%s cooldown_seconds=%.1f",
        current.get("read_budget_rpm", 0),
        delta["physical_reads"],
        delta["cache_hits"],
        delta["stale_hits"],
        delta["coalesced_joins"],
        delta["cache_misses"],
        delta["retries"],
        delta["rate_limit_errors"],
        delta["invalidations"],
        float(delta["avoided_read_share_pct"]),
        current.get("cache_entries", 0),
        current.get("inflight", 0),
        float(current.get("cooldown_seconds", 0.0) or 0.0),
    )


def _report_loop() -> None:
    stop = threading.Event()
    previous = broker.snapshot()
    if stop.wait(_INITIAL_DELAY_SECONDS):
        return

    current = broker.snapshot()
    _emit(previous, current)
    previous = current

    while not stop.wait(_INTERVAL_SECONDS):
        current = broker.snapshot()
        _emit(previous, current)
        previous = current


def start_sheets_telemetry() -> None:
    """Start the one-per-process daemon reporter."""

    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        threading.Thread(
            target=_report_loop,
            name="sheets-broker-telemetry",
            daemon=True,
        ).start()
