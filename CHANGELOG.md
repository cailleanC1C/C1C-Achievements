# Changelog

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
