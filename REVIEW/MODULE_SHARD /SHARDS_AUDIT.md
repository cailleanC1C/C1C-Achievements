# Achievement Bot — Shard Module Reality Check

## ✅ Verified against spec
- OCR heavy work runs off-thread and the scan flow mirrors the documented defer → cache → preview pipeline.【F:cogs/shards/cog.py†L82-L305】
- Cache keying, retry clearing, and the zero-result debug upload match the reference behavior.【F:cogs/shards/cog.py†L142-L278】
- Diagnostic commands `!ocr info` / `!ocr selftest` remain intact for staff triage.【F:cogs/shards/cog.py†L345-L382】
- OCR pipeline parameters (crop ratios, thresholding, OEM/PSM, confidence gate) align with the authoritative snapshot.【F:cogs/shards/ocr.py†L144-L405】

## ❌ Gaps to address immediately
1. **Manual-first path missing on first panel.** No button launches the manual modal until after OCR runs, and the listener bails out entirely when no screenshot is present.【F:cogs/shards/cog.py†L133-L333】
2. **Emoji policy violations.** Multiple UI surfaces fall back to unicode squares instead of guaranteed custom emojis (config defaults, modal labels, mercy buttons, help text, renderer).【F:cogs/shards/cog.py†L94-L124】【F:cogs/shards/views.py†L10-L47】【F:cogs/shards/renderer.py†L11-L58】【F:cogs/shards/sheets_adapter.py†L91-L99】
3. **Backlog readiness.** No feature/epic issues capture the mandated manual-first flow or emoji migration, and existing shard issues lack non-goals, test steps, and rollout notes.【F:ISSUE_AUDIT.md†L5-L14】

## 🎯 Recommended next steps
1. Ship the manual-first UX: add the “Manual entry (Skip OCR)” button to the public prompt, expose it even when no image is attached, and share modal-handling logic so both paths behave identically.【F:PATCH_PLAN.md†L3-L33】【F:UI_FLOW_MAP.md†L6-L23】
2. Centralize shard emojis: commit the JSON mapping + helper, validate Sheet overrides, and swap all unicode placeholders to the custom set (preview, modals, embeds, help text).【F:EMOJI_AUDIT.md†L3-L24】【F:PATCH_PLAN.md†L35-L65】
3. Refresh planning artifacts: adopt the new issue batch (milestone `Shard Module v0.4 — Manual First`) to track manual-first, emoji migration, and the deferred OCR epic.【F:issue-batches/shards-epic-refresh.json†L1-L69】
4. Hold release until prerequisites in the ready-to-implement gate are met (issue hygiene, emoji IDs, UX decisions for no-attachment cases).【F:READY_TO_IMPLEMENT.md†L1-L8】
