# Offline Investigation — Discord Cloudflare 1015 Lockouts

## Observed behaviour
- Hosting logs show `discord.com` responding with Cloudflare **1015 (You are being rate limited)** and a temporary IP ban banner.
- The application process immediately exits whenever the configuration bootstrap fails, so Render restarts the container and the bot attempts to identify again almost instantly.
- Because the retry loop had **no backoff**, repeated logins compounded until Cloudflare rate-limited the IP, leaving the bot offline even after the config issue cleared.

## Root cause in the codebase
1. **Hard failure during `on_ready` config load**
   - `on_ready` directly invoked `load_config()` and called `await bot.close()` on any exception.
   - Any transient Google Sheets error (network blip, expired service account token, etc.) therefore caused the process to terminate. Render immediately re-ran the start command, creating rapid reconnect attempts.
2. **No handshake backoff**
   - The entrypoint relied on `bot.run(token)` without guarding `discord.HTTPException` (429/503) or network connector errors. When Discord/Cloudflare rejected the handshake, the script exited and restarted right away, hammering the same endpoint.
3. **Limited visibility for operators**
   - Health commands exposed `loaded_at`/`source` but did not surface whether configuration was actually ready or why it last failed, making these restart loops harder to diagnose live.

## Fixes implemented in this patch
- Added an asynchronous `_ensure_config_loaded` bootstrap that retries with exponential backoff instead of shutting the client down on the first failure.
- Replaced the bare `bot.run` call with `_run_bot`, which wraps `login/connect` in a guarded loop, applies cooldowns after 429/503/Cloudflare bans, and handles network connector errors gracefully.
- Surfaced `status`, `ready`, and `last_error` metadata through the CoreOps embeds/digests so ops staff can spot stalled config loads without reading logs.

These changes collectively slow down reconnect thrash, keep the process alive during Google Sheets hiccups, and expose richer telemetry for future incidents.
