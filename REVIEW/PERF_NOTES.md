# Performance Notes

- Config reloads (`load_config`) call Google Sheets APIs synchronously on the event loop thread. Each reload blocks the gateway while waiting on network I/O; move the heavy work into `asyncio.to_thread` or an executor and swap the config atomically once fresh data is available.
- Auto-refresh (`_auto_refresh_loop`) currently reuses the same blocking `load_config`, compounding the stall risk. Consider running reloads off-thread and applying jitter/backoff for repeated failures.
- Shards Sheets adapter performs `append_row` calls per event with no batching; if usage spikes, switch to `batch_update` to reduce API round trips.
- Could not run a cyclomatic-complexity scan because `radon` could not be installed in this environment (proxy 403). See TODOs for manual hotspots.
