# Changelog

## [1.0.2] – 2025-10-05

### Reliability

* Added guarded startup loop with exponential backoff so Cloudflare 1015/429 responses pause reconnect attempts instead of bouncing the process.
* Replaced the fatal config bootstrap with a background retry worker that survives transient Google Sheets outages and advertises status/last-error metadata via CoreOps embeds.
* Documented the offline investigation and mitigation steps in `docs/offline_analysis.md` for future incident response.

## [1.0.1] – 2025-10-02

### Fixes

* Restored runtime telemetry surfaces (uptime, last-event age, watchdog config) so `!health`, `!digest`, and `!env` return complete diagnostics again.
* Updated prefix resolution to prioritize scoped prefixes (`!sc`, `!rem`, `!wc`, `!mm`) ahead of the global fallback, ensuring staff-prefixed CoreOps commands execute correctly.

## [1.0.0] – 2025-10-01

### Infrastructure

* Initial carve-out from the monolith into a dedicated Achievement Bot package.
* Sheets-driven configuration established (General, Categories, Achievements, Levels, Reasons).
* CoreOps prefix router added (`!sc …`) with shared command model.

### New functionality

* Smart appreciation messages when configured roles are granted.
* Burst grouping window prevents spam by combining multiple grants into one message.
* Guardian Knight claim-review flow added: screenshot thread, decision reasons, approvals/denials.
* Audit-log filtering: only specific roles trigger entries.
* Preview commands (`!testach`, `!testlevel`) for admins to check formatting before rollout.
* Shared OpsCommands introduced (scoped `!sc health`, `!sc digest`, `!sc reload`, etc. with bare-command picker).

### Bugfixes / Adjustments

* N/A — first release.
