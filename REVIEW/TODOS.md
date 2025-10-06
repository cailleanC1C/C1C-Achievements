# TODOs

- **P0 — F-01:** Introduce `load_config_async()` (run `load_config` in executor) and update all callers (`_ensure_config_loaded`, `_auto_refresh_loop`, `!reloadconfig`, CoreOps `reload`).
- **P1 — F-03:** Fix `set_summary_msg` so it only appends the header when the sheet is empty; verify updates succeed on populated sheets.
- **P1 — F-02:** Correct `build_digest_line` to track runtime and config readiness separately and add regression test for `!digest` output.
- **P2:** After F-01, add integration test that exercises `CONFIG_AUTO_REFRESH_MINUTES` with a mocked slow Sheets client to ensure no gateway stall.
- **P2:** Extend shard Sheets adapter with retry/backoff + batching (follow-up once header append fix lands).
