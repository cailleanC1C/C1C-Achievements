# ADR-002 — Shards UX: Manual-first, OCR v2 postponed
**Status:** Accepted • **Date:** 2025-10-08

## Context
Current OCR is inconsistent for big numbers; we need a reliable UX now.

## Decision
- Add **“Manual entry (Skip OCR)”** to the **first** public panel.
- Keep current OCR pipeline; improvements tracked under **Epic: OCR v2** (blocked).

## Consequences
- Users bypass flaky OCR when needed.
- Clear follow-up scope (token stitching, per-band OCR, richer debug).
