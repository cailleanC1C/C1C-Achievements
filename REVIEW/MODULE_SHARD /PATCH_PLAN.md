# Patch Plan

## 1. Manual entry (Skip OCR) button on first panel
- **File:** `cogs/shards/cog.py`
  - Introduce a reusable helper inside `on_message` to open the manual modal without OCR; reuse existing logic from the preview’s `manual_btn` callback.【F:cogs/shards/cog.py†L235-L259】
  - Add a `manual_btn_public` button to the public view alongside Scan/Dismiss, wiring it to the helper and ensuring it is available even when the message lacks image attachments.【F:cogs/shards/cog.py†L159-L333】
  - Adjust the attachment guard so shard-thread messages without images still post a manual-only prompt (or a prompt where Scan is disabled/hidden) to satisfy the spec.【F:cogs/shards/cog.py†L133-L166】
  - Clear OCR cache only when OCR actually runs; the manual-first path should bypass cache touches entirely.

```
@@ async def on_message(...):
-    if not (message.attachments and any(_is_image_attachment(a) for a in message.attachments)):
-        return
+    images = [a for a in message.attachments if _is_image_attachment(a)] if message.attachments else []
+
+    def _eligible_for_scan() -> bool:
+        return bool(images)
+
+    view = discord.ui.View(timeout=300)
+    scan_btn = discord.ui.Button(..., disabled=not _eligible_for_scan())
+    manual_btn_public = discord.ui.Button(label="Manual entry (Skip OCR)", style=discord.ButtonStyle.secondary, ...)
+    dismiss_btn = discord.ui.Button(...)
+
+    async def _manual_first(inter: discord.Interaction):
+        if inter.user.id != message.author.id and not _has_any_role(...):
+            ...
+        await _open_manual_modal(inter, prefill=None)
+
+    manual_btn_public.callback = _manual_first
+    view.add_item(scan_btn)
+    view.add_item(manual_btn_public)
+    view.add_item(dismiss_btn)
```

- Share the modal-opening logic between `_manual_first` and the existing preview buttons to avoid duplication and keep validation consistent.

## 2. Centralized shard emoji mapping
- **Files:**
  - `assets/emojis/shards.json` (new) — commit the canonical ID map referenced in the audit.【F:EMOJI_AUDIT.md†L15-L23】
  - `cogs/shards/constants.py` or a new helper module (e.g. `cogs/shards/emoji.py`) — load the JSON at startup and expose `get_shard_emoji(shard, overrides=None)`.
  - `cogs/shards/sheets_adapter.py` — replace unicode defaults with lookups against the JSON and validate that Sheet overrides are custom emoji strings (fallback to JSON if blank).【F:cogs/shards/sheets_adapter.py†L91-L99】
  - `cogs/shards/cog.py` — replace `_emoji_or_abbr` with helper usage and update any string formatting that currently appends abbreviations.【F:cogs/shards/cog.py†L94-L124】【F:cogs/shards/cog.py†L400-L407】
  - `cogs/shards/views.py` — compute modal labels and button text using the helper rather than hardcoded unicode.【F:cogs/shards/views.py†L10-L47】
  - `cogs/shards/renderer.py` — swap to helper for summary embed formatting.【F:cogs/shards/renderer.py†L11-L58】

```
+from .emoji import get_shard_emoji
@@
-def _fmt_counts_line(...):
-    label = self._emoji_or_abbr(st)
+    label = get_shard_emoji(st, overrides=self.cfg.emoji)
@@
-class SetCountsModal(...):
-    self.mys = discord.ui.TextInput(label="🟩 Mystery", ...)
+    mys_label = f"{get_shard_emoji(ShardType.MYSTERY, overrides=emoji_map)} Mystery"
+    self.mys = discord.ui.TextInput(label=mys_label, ...)
```

- Ensure the helper gracefully handles missing IDs (e.g. returns `<:placeholder:ID>` or a safe fallback) but log when defaults are used so staff can populate the mapping.
- Update unit/integration docs (`README` / shard help copy) to reflect that custom emojis are enforced.
