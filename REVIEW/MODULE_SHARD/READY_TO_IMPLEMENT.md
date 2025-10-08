# Ready to Implement?

**Status:** No — planning prerequisites remain.

## Blocking prerequisites
- Product/UX sign-off on adding the “Manual entry (Skip OCR)” button to the public prompt (and behaviour when OCR is bypassed), since the current implementation only exposes manual entry after Scan Image or via `!shards set`.【F:cogs/shards/cog.py†L160-L206】【F:cogs/shards/cog.py†L385-L451】
- Technical design for enforcing custom emoji usage and centralizing the mapping instead of relying on unicode fallbacks scattered across helper methods and UI components.【F:cogs/shards/cog.py†L94-L125】【F:cogs/shards/views.py†L13-L47】【F:cogs/shards/renderer.py†L11-L61】
- Configuration plan to ensure Sheets-provided emoji entries are populated with the required custom emoji strings (no silent unicode defaults).【F:cogs/shards/sheets_adapter.py†L91-L99】
