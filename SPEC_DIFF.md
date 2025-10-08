# Spec vs. Implementation — Shard Module

## Interaction Flow
- ✅ **Image watcher defers OCR work off the gateway loop.** `_ocr_prefill_from_attachment` wraps `extract_counts_from_image_bytes` in `asyncio.to_thread`, matching the spec requirement to keep the listener responsive.【F:cogs/shards/cog.py†L82-L91】
- ✅ **Scan button defers ephemerally before heavy work.** The scan callback calls `inter.response.defer(ephemeral=True, thinking=True)` prior to reading from cache/OCR, matching the spec.【F:cogs/shards/cog.py†L168-L205】
- ✅ **OCR preview is ephemeral with Use/Manual/Retry/Close actions.** The follow-up response posts the preview with an ephemeral view that wires those four buttons, in line with the described UX.【F:cogs/shards/cog.py†L193-L305】
- ✅ **Retry clears the cache before re-running OCR.** `_retry` pops the cache entry for the `(guild, channel, message)` key then rebuilds it, which satisfies “Retry resets cache.”【F:cogs/shards/cog.py†L185-L278】
- ✅ **Counts are cached per (guild, channel, message).** The tuple key uses guild/thread/message IDs as specified.【F:cogs/shards/cog.py†L185-L190】
- ✅ **All-zero OCR results trigger debug ROI uploads.** The background task posts grayscale/binarized ROIs when the sum of counts is zero, matching the requirement.【F:cogs/shards/cog.py†L142-L157】
- ✅ **Staff diagnostics exist.** `!ocr info` and `!ocr selftest` commands mirror the spec’s tooling.【F:cogs/shards/cog.py†L345-L382】
- ❌ **Manual entry (Skip OCR) button is missing on the first public panel.** The public prompt only includes “Scan Image” and “Dismiss,” so the manual-first path is absent. *Fix:* add a third button to the initial view that opens the manual modal without touching OCR/cache.【F:cogs/shards/cog.py†L159-L333】
- ❌ **Manual entry path is unavailable when no image is attached.** The listener exits early if the message lacks an image, so the manual-first requirement “available even without an attachment” is unmet. *Fix:* allow the manual button to be shown (or a manual-only prompt) even when attachments are missing, gated to shard threads to avoid spam.【F:cogs/shards/cog.py†L133-L166】

## OCR Pipeline Parameters
- ✅ **Crop ratios match 0.38/0.42/0.46.**【F:cogs/shards/ocr.py†L144-L206】
- ✅ **Binarize threshold 160 with MaxFilter(3).**【F:cogs/shards/ocr.py†L235-L245】
- ✅ **PSM order (6 then 11) and OEM 3 are respected.**【F:cogs/shards/ocr.py†L361-L378】
- ✅ **Left-side gate clamps at 60% of ROI width.**【F:cogs/shards/ocr.py†L367-L401】
- ✅ **Confidence floor at 18 before accepting tokens.**【F:cogs/shards/ocr.py†L391-L405】

## Miscellaneous
- ✅ **OCR runs in a background thread for self-test and runtime info is logged once on cog init, aligning with expectations for diagnostics visibility.**【F:cogs/shards/cog.py†L34-L61】【F:cogs/shards/ocr.py†L100-L119】
