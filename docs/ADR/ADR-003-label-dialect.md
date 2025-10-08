# ADR-003 — Label dialect (harmonized)
+**Status:** Accepted • **Date:** 2025-10-08
+
+## Decision
+Use `.github/labels/harmonized.json` as the single source of truth.
+Examples: `bot:achievements`, `comp:shards`, `feature|epic`, `ready|blocked`, `P0..P4`, `severity:*`.
+
+## Consequences
+- Batch issue files must use only canon labels.
+- CI will fail PRs that introduce unknown/variant labels.
