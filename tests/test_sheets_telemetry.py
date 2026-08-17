from achievements.sheets_telemetry import interval_metrics


def test_interval_metrics_reports_deltas_and_avoided_share():
    previous = {
        "physical_reads": 10,
        "cache_hits": 4,
        "stale_hits": 1,
        "coalesced_joins": 2,
        "cache_misses": 8,
        "retries": 1,
        "rate_limit_errors": 1,
        "invalidations": 2,
    }
    current = {
        "physical_reads": 14,
        "cache_hits": 10,
        "stale_hits": 2,
        "coalesced_joins": 5,
        "cache_misses": 11,
        "retries": 3,
        "rate_limit_errors": 2,
        "invalidations": 5,
    }

    metrics = interval_metrics(previous, current)

    assert metrics["physical_reads"] == 4
    assert metrics["cache_hits"] == 6
    assert metrics["stale_hits"] == 1
    assert metrics["coalesced_joins"] == 3
    assert metrics["cache_misses"] == 3
    assert metrics["retries"] == 2
    assert metrics["rate_limit_errors"] == 1
    assert metrics["invalidations"] == 3
    assert metrics["avoided_read_share_pct"] == 71.4


def test_interval_metrics_clamps_counter_resets_to_zero():
    previous = {
        "physical_reads": 20,
        "cache_hits": 15,
        "stale_hits": 4,
        "coalesced_joins": 3,
        "cache_misses": 10,
        "retries": 5,
        "rate_limit_errors": 4,
        "invalidations": 7,
    }
    current = {
        "physical_reads": 1,
        "cache_hits": 0,
        "stale_hits": 0,
        "coalesced_joins": 0,
        "cache_misses": 1,
        "retries": 0,
        "rate_limit_errors": 0,
        "invalidations": 0,
    }

    metrics = interval_metrics(previous, current)

    assert metrics["physical_reads"] == 0
    assert metrics["cache_hits"] == 0
    assert metrics["stale_hits"] == 0
    assert metrics["coalesced_joins"] == 0
    assert metrics["cache_misses"] == 0
    assert metrics["retries"] == 0
    assert metrics["rate_limit_errors"] == 0
    assert metrics["invalidations"] == 0
    assert metrics["avoided_read_share_pct"] == 0.0


def test_interval_metrics_handles_missing_counters():
    metrics = interval_metrics({}, {"physical_reads": 2, "cache_hits": 3})

    assert metrics["physical_reads"] == 2
    assert metrics["cache_hits"] == 3
    assert metrics["stale_hits"] == 0
    assert metrics["coalesced_joins"] == 0
    assert metrics["avoided_read_share_pct"] == 60.0
