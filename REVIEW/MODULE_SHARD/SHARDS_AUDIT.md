# Achievement Bot — Shard Module Audit

## Spec alignment highlights
- Thread watcher only reacts to clan shard threads with image attachments and posts the Scan/Dismiss prompt, matching the documented entry point. It also schedules the zero-result ROI debug upload in the background task.【F:cogs/shards/cog.py†L128-L166】【F:cogs/shards/cog.py†L142-L155】
- Scan Image defers ephemerally, consults the `(guild_id, channel_id, message_id)` cache, and renders the preview with Use/Manual/Retry/Close, keeping heavy OCR work off the event loop.【F:cogs/shards/cog.py†L168-L307】
- Retry purges the cache entry before rerunning OCR, and diagnostics `!ocr info` / `!ocr selftest` remain available for staff triage.【F:cogs/shards/cog.py†L261-L382】
- OCR pipeline preserves the reference behavior: EXIF transpose and scaling, left-rail ratios (0.38/0.42/0.46), preprocessing stack, OEM 3 with PSM 6 then 11, numeric token gating, 60% X cutoff, band assignment, and all-zero rejection.【F:cogs/shards/ocr.py†L122-L452】

## Mismatches and risks (severity ≥ low)
1. **Manual-first gap on the public prompt (medium).** The first panel exposes only Scan Image and Dismiss, so the promised “Manual entry (Skip OCR)” path is absent until after a scan succeeds. If no attachment OCR succeeds, users must fall back to chat commands.【F:cogs/shards/cog.py†L160-L206】
2. **Emoji policy drift (low).** UI layers fall back to unicode squares rather than guaranteed custom server emojis: `_emoji_or_abbr` hard-codes 🟩/🟦…, modal labels use the same glyphs, and the Sheets defaults mirror those placeholders.【F:cogs/shards/cog.py†L94-L125】【F:cogs/shards/views.py†L13-L47】【F:cogs/shards/sheets_adapter.py†L91-L99】
3. **No centralized emoji inventory (low).** There is no `assets/emojis` directory or shared mapping module; each surface relies on config defaults or inline labels, making it easy for future drift.【F:cogs/shards/cog.py†L94-L125】【F:cogs/shards/views.py†L13-L47】【F:cogs/shards/renderer.py†L11-L61】

## Recommendations
- Add the manual-entry button to the public prompt (and allow it even when OCR is skipped) so the UX matches expectations for hard-to-scan images.
- Introduce a canonical emoji map (e.g., ID-based config loader) and update all shard surfaces to consume it without unicode fallbacks.
- Document the emoji requirements and manual-entry UX in planning materials before implementing changes.
