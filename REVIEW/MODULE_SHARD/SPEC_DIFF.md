# Spec vs. Implementation — Shard Module

## Confirmed matches
- **Watcher scope.** Listeners only act in enabled clan shard threads when an image attachment is present, then post the Scan Image / Dismiss buttons as described.【F:cogs/shards/cog.py†L128-L166】
- **OCR execution path.** Scan defers ephemerally, reuses cached counts, and offers Use / Manual entry / Retry / Close options in the preview state.【F:cogs/shards/cog.py†L168-L307】
- **Cache + retry semantics.** Cache key is `(guild_id, channel_id, message_id)` and Retry clears the cache before rerunning OCR.【F:cogs/shards/cog.py†L185-L278】
- **Zero-result diagnostics.** When OCR finds only zeros, the background task posts the grayscale and binarized ROI for tuning.【F:cogs/shards/cog.py†L142-L155】
- **Diagnostics + pipeline.** `!ocr info` / `!ocr selftest` remain and the OCR pipeline retains the spec’d ratios, preprocessing, OEM/PSM sequence, numeric token filters, and band scoring.【F:cogs/shards/cog.py†L345-L382】【F:cogs/shards/ocr.py†L122-L452】

## Divergences
- **Manual entry on first panel (missing).** The opening prompt lacks the promised “Manual entry (Skip OCR)” control; the manual modal is only reachable after pressing Scan Image.【F:cogs/shards/cog.py†L160-L206】
- **Custom emoji guarantee (not enforced).** Emoji sources default to unicode squares in `_emoji_or_abbr`, modal labels, and Sheets config, so there is no assurance of custom ID usage.【F:cogs/shards/cog.py†L94-L125】【F:cogs/shards/views.py†L13-L47】【F:cogs/shards/sheets_adapter.py†L91-L99】
- **Central emoji registry (absent).** No shared mapping file or assets directory exists; each surface hand-rolls labels, risking inconsistency with the policy.【F:cogs/shards/cog.py†L94-L125】【F:cogs/shards/views.py†L13-L47】【F:cogs/shards/renderer.py†L11-L61】
