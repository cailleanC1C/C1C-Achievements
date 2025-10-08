# Shard Module Planning — Acceptance Checklist

- [ ] Manual-first button appears on the initial shard prompt and opens the manual modal without invoking OCR, regardless of attachment presence in eligible threads.
- [ ] Scan Image path behaviour and retry cache clearing remain unchanged; zero-result cases still post debug ROI images to threads.
- [ ] All shard render surfaces (preview, manual modal, final summary, logs) use the centralized emoji mapping, and health/info commands report OK or missing status per shard key.
- [ ] No implicit unicode-square fallbacks remain; any textual fallback is deliberate and generates a log entry for follow-up.
