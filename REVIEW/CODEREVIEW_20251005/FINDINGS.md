# Findings

## F-01 (High) — Robustness: Config reload blocks the event loop
- **Where:** `c1c_claims_appreciation.py` (`load_config`, `_ensure_config_loaded`, `_auto_refresh_loop`, `reloadconfig`); `cogs/ops.py` (`OpsCog.reload_cmd`).【F:c1c_claims_appreciation.py†L213-L325】【F:c1c_claims_appreciation.py†L1545-L1554】【F:c1c_claims_appreciation.py†L1283-L1292】【F:cogs/ops.py†L214-L301】
- **Issue:** `load_config()` performs Google Sheets / Excel I/O synchronously. Every caller (`!reloadconfig`, CoreOps `reload`, auto-refresh loop, boot retry) invokes it directly on the gateway loop, blocking message dispatch for seconds whenever Sheets is slow.
- **Fix (diff-ready):** offload the heavy work to a thread and expose an async wrapper so all callers `await` it.
```diff
--- a/c1c_claims_appreciation.py
+++ b/c1c_claims_appreciation.py
@@
-async def _ensure_config_loaded(initial: bool = False) -> None:
+async def load_config_async() -> None:
+    loop = asyncio.get_running_loop()
+    await loop.run_in_executor(None, load_config)
+
+
+async def _ensure_config_loaded(initial: bool = False) -> None:
@@
-            load_config()
+            await load_config_async()
             return
@@
-            load_config()
+            await load_config_async()
@@
-async def reloadconfig(ctx: commands.Context):
+async def reloadconfig(ctx: commands.Context):
@@
-        load_config()
+        await load_config_async()
```
```diff
--- a/cogs/ops.py
+++ b/cogs/ops.py
@@
-            app.load_config()
+            await app.load_config_async()
```
- **Verify:**
  - `!reloadconfig` returns promptly while another command (`!ping`) still responds.
  - Flip `CONFIG_AUTO_REFRESH_MINUTES` to 1, point Sheets to a slow network (simulate with sleep), confirm bot stays responsive and logs reload completion.

## F-02 (Medium) — Correctness: Digest misreports runtime readiness
- **Where:** `claims/ops.py` (`build_digest_line`).【F:claims/ops.py†L86-L111】
- **Issue:** The local variable `ready` is reused for both runtime readiness and config readiness. As soon as `ready = cfg.get("ready")` executes, the runtime value is lost, so the digest prints the config flag twice (and may show `ready:False` even when the bot is ready).
- **Fix:** Keep the runtime flag separate and stringify both values explicitly.
```diff
-    ready  = "True" if rt.get("ready") else "False"
+    runtime_ready = "True" if rt.get("ready") else "False"
@@
-    status = cfg.get("status", "—")
-    ready  = cfg.get("ready")
+    status = cfg.get("status", "—")
+    config_ready = "True" if cfg.get("ready") else "False"
@@
-        f"ready:{ready} | latency:{_fmt(lat_ms)}ms | last_event:{_fmt(last_s)}s | "
-        f"cfg:{src} @ {when} | cfg_status:{status}/{ready} ({err_flag}) | "
+        f"ready:{runtime_ready} | latency:{_fmt(lat_ms)}ms | last_event:{_fmt(last_s)}s | "
+        f"cfg:{src} @ {when} | cfg_status:{status}/{config_ready} ({err_flag}) | "
```
- **Verify:** Run `!digest` when the bot is ready; the first `ready:` token should mirror `bot.is_ready()`, while `cfg_status` continues to reflect the config flag.

## F-03 (Medium) — Correctness: Shards summary header append fails once sheet has rows
- **Where:** `cogs/shards/sheets_adapter.py` (`set_summary_msg`).【F:cogs/shards/sheets_adapter.py†L139-L165】
- **Issue:** When the `SUMMARY_MSGS` worksheet already contains data, the code still executes `ws.append_row([])`, which gspread rejects (`ValueError: Row values must not be empty`). Result: subsequent summary updates crash instead of updating the row.
- **Fix:** Only append the header when the sheet is empty.
```diff
-    if target_idx:
-        ws.update(f"A{target_idx}:F{target_idx}", [payload], value_input_option="RAW")
-    else:
-        ws.append_row(
-            ["clan_tag", "thread_id", "pinned_message_id", "last_edit_ts_utc", "page_count", "page_size"]
-            if not rows else []
-        )
-        ws.append_row(payload, value_input_option="RAW")
+    if target_idx:
+        ws.update(f"A{target_idx}:F{target_idx}", [payload], value_input_option="RAW")
+    else:
+        if not rows:
+            ws.append_row(
+                ["clan_tag", "thread_id", "pinned_message_id", "last_edit_ts_utc", "page_count", "page_size"],
+                value_input_option="RAW",
+            )
+        ws.append_row(payload, value_input_option="RAW")
```
- **Verify:**
  1. Start with empty `SUMMARY_MSGS`; call `set_summary_msg` twice.
  2. Confirm the first call writes the header and payload, the second updates the existing row without raising and reflects the new message ID/timestamp.
