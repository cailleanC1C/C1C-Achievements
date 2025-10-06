# Architecture Map

## Current Flow
```
Discord events
  └─ on_message (claims)
       ├─ validates channel + attachments
       ├─ CategoryPicker / MultiImageChoice views (user interactions)
       ├─ process_claim → finalize_grant → audit + grouping buffer
       └─ Guardian Knight review flows (GKReview)
  └─ on_member_update
       └─ matches LEVELS rows → posts to #levels
CoreOps commands (cogs/ops)
  └─ Guard via `_coreops_guard` → render embeds via claims.ops helpers
Config loading (`load_config`)
  └─ Google Sheets / Excel synchronous fetch → populate CFG / ACHIEVEMENTS / CATEGORIES / LEVELS
Grouped praise
  └─ `_buffer_item` stores per-user queue → `_flush_group` posts combined embed after delay
Shards module (`cogs/shards`)
  └─ Thread listener → OCR helpers → Sheets adapter (append_row, summary refresh)
```

## Target Stabilisation for Carve-out
- **Config adapter boundary:** Extract Sheets/Excel fetch into async repository (off-thread) with schema validation. Expose immutable snapshot objects to bot layer.
- **Claims domain services:** Move `finalize_grant`, grouping buffer, and GK flows into dedicated module with unit-testable functions.
- **Prefix/CoreOps parity:** Share prefix guard + command registration utilities with Reminder bot (common package) to avoid drift.
- **Sheets I/O abstraction:** Wrap shard/claims Sheet writes in a client that batches updates, retries with backoff, and isolates credentials.
- **Event surface:** Define explicit interfaces for:
  - `ClaimsService.process_claim(interaction, selection, attachments)`
  - `PraisePublisher.enqueue(user_id, achievement_key)`
  - `ConfigService.reload(source)`
  - `ShardService.record_snapshot(...)`
- **Logging/Audit pipeline:** Centralise audit logging with structured payloads; ensure idempotency on reconnect/retry.
