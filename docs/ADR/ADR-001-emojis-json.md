# ADR-001 — Shard emojis via repo JSON (optional Sheet override)
**Status:** Accepted • **Date:** 2025-10-08

## Context
Shard-type icons should be consistent, fast to load, and versioned with code.

## Decision
- Default authority: **JSON in repo** mapping keys → custom emoji IDs.
- Optional override: **Google Sheet** fetch only on **manual refresh** command.
- Health/info command must warn if any emoji ID is missing in the guild.

## Consequences
- Faster UI, no quota hiccups, easy rollback via Git history.
- A manual refresh path exists if non-dev edits are needed.

## Alternatives considered
- Fully Sheet-driven (rejected: quotas, latency, silent fallbacks).
