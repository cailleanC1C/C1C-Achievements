# Emoji Audit — Shard Module

## Sources in code
- `_emoji_or_abbr` reads `self.cfg.emoji` (populated from Sheets) but falls back to hard-coded unicode squares with text abbreviations when entries are missing.【F:cogs/shards/cog.py†L94-L125】
- `SetCountsModal` labels and `AddPullsStart` buttons embed the same unicode squares directly in the UI components.【F:cogs/shards/views.py†L13-L47】
- Summary renderer expects the emoji map to already contain the final display strings/IDs and prints them inline in embeds.【F:cogs/shards/renderer.py†L11-L61】
- Sheets adapter seeds the emoji map with unicode defaults (🟩/🟦/🟪/🟥/🟨) if spreadsheet cells are blank, so custom IDs are optional rather than required.【F:cogs/shards/sheets_adapter.py†L91-L99】

## Policy compliance assessment
- **Custom emoji guarantee:** Not enforced. Every surface gracefully falls back to unicode glyphs, so missing or misconfigured custom IDs will silently degrade instead of surfacing errors.【F:cogs/shards/cog.py†L94-L125】【F:cogs/shards/views.py†L13-L47】
- **Centralized mapping:** Absent. There is no shared `assets/emojis` dataset or helper module; each layer consumes `self.cfg.emoji` or literals, risking divergence across panels.【F:cogs/shards/cog.py†L94-L125】【F:cogs/shards/views.py†L13-L47】【F:cogs/shards/renderer.py†L11-L61】

## Suggested follow-ups
- Require Sheet-configured entries to be custom emoji IDs (or `<:name:id>` strings) and fail fast when missing.
- Provide a single helper/module that returns consistent emoji labels for previews, modals, buttons, and embeds.
