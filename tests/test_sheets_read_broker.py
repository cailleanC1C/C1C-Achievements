from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import achievements
from achievements.sheets_read_broker import (
    CONFIG_DATA,
    FRESH_REQUIRED,
    QuotaCooldownError,
    SheetsReadBroker,
    broker,
)


def _fast_broker(**kwargs) -> SheetsReadBroker:
    return SheetsReadBroker(
        rpm=1_000_000,
        rate_window_seconds=0.001,
        retry_base_seconds=0,
        retry_cap_seconds=0,
        exhausted_cooldown_seconds=0.05,
        **kwargs,
    )


def test_package_installs_process_wide_gspread_boundary():
    from gspread.client import Client
    from gspread.spreadsheet import Spreadsheet
    from gspread.worksheet import Worksheet

    assert achievements is not None
    assert getattr(Client.open_by_key, "__c1c_sheets_brokered__", False)
    assert getattr(Spreadsheet.worksheets, "__c1c_sheets_brokered__", False)
    assert getattr(Spreadsheet.worksheet, "__c1c_sheets_brokered__", False)
    assert getattr(Worksheet.get, "__c1c_sheets_brokered__", False)
    assert broker.rpm >= 1


def test_config_reads_are_cached_sequentially():
    local = _fast_broker()
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return {"version": calls}

    assert local.read("config", loader, policy=CONFIG_DATA) == {"version": 1}
    assert local.read("config", loader, policy=CONFIG_DATA) == {"version": 1}
    assert calls == 1
    assert local.snapshot()["cache_hits"] == 1


def test_fresh_required_reads_again_sequentially():
    local = _fast_broker()
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return calls

    assert local.read("help", loader, policy=FRESH_REQUIRED) == 1
    assert local.read("help", loader, policy=FRESH_REQUIRED) == 2
    assert calls == 2


def test_concurrent_identical_reads_singleflight_once():
    local = _fast_broker()
    calls = 0
    lock = threading.Lock()

    def loader():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.02)
        return "ok"

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(
                lambda _: local.read("same", loader, policy=CONFIG_DATA),
                range(16),
            )
        )

    assert results == ["ok"] * 16
    assert calls == 1
    assert local.snapshot()["coalesced_joins"] >= 15


def test_rate_limit_retry_is_centralized_in_broker():
    local = _fast_broker(retry_attempts=3)
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED read requests")
        return "ok"

    assert local.read("quota", loader, policy=FRESH_REQUIRED) == "ok"
    assert calls == 3
    snapshot = local.snapshot()
    assert snapshot["rate_limit_errors"] == 2
    assert snapshot["retries"] == 2
    assert snapshot["physical_reads"] == 3


def test_exhausted_quota_enters_fast_fail_cooldown():
    local = _fast_broker(retry_attempts=1)

    with pytest.raises(RuntimeError, match="429"):
        local.read(
            "quota",
            lambda: (_ for _ in ()).throw(RuntimeError("429 quota")),
            policy=FRESH_REQUIRED,
        )

    physical_before = local.snapshot()["physical_reads"]
    with pytest.raises(QuotaCooldownError):
        local.read("next", lambda: "should-not-run", policy=FRESH_REQUIRED)
    assert local.snapshot()["physical_reads"] == physical_before


def test_stale_config_is_available_during_quota_failure():
    local = _fast_broker(retry_attempts=1)
    state = {"fail": False}

    def loader():
        if state["fail"]:
            raise RuntimeError("429 quota")
        return "cached"

    assert local.read("stale", loader, policy=CONFIG_DATA) == "cached"
    local._cache["stale"].loaded_at -= CONFIG_DATA.fresh_seconds + 1
    state["fail"] = True

    assert local.read("stale", loader, policy=CONFIG_DATA) == "cached"
    assert local.snapshot()["stale_hits"] == 1


def test_worksheet_write_invalidation_is_targeted():
    local = _fast_broker()
    key_a = ("values", "book", "tab-a", (), ())
    key_b = ("values", "book", "tab-b", (), ())

    local.read(key_a, lambda: "a", policy=CONFIG_DATA)
    local.read(key_b, lambda: "b", policy=CONFIG_DATA)

    removed = local.invalidate_worksheet("book", "tab-a")

    assert removed == 1
    assert key_a not in local._cache
    assert key_b in local._cache
    assert local.snapshot()["invalidations"] == 1


def test_sustained_budget_refills_instead_of_unbounded_reads():
    local = SheetsReadBroker(
        rpm=2,
        rate_window_seconds=0.04,
        retry_attempts=1,
        retry_base_seconds=0,
        retry_cap_seconds=0,
        exhausted_cooldown_seconds=0,
    )
    timestamps = []

    def physical(value):
        timestamps.append(time.monotonic())
        return value

    # Two reads consume the initial burst capacity immediately.  The third must
    # wait for one token to refill.
    local.read("one", lambda: physical(1), policy=FRESH_REQUIRED)
    local.read("two", lambda: physical(2), policy=FRESH_REQUIRED)
    local.read("three", lambda: physical(3), policy=FRESH_REQUIRED)

    assert timestamps[2] - timestamps[1] >= 0.015
