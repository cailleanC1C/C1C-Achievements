# UI Flow Map — Shard Image Handling

1. **Auto-detected thread message**
   - Trigger: non-bot message in an enabled clan shard thread that carries an image attachment.【F:cogs/shards/cog.py†L128-L140】
   - Bot posts “Spotted a shard screen. Scan it for counts?” with two public buttons: **Scan Image** (primary) and **Dismiss** (secondary). No manual-entry shortcut is exposed here.【F:cogs/shards/cog.py†L160-L166】
   - Background task runs `extract_counts_with_debug`; if OCR returns all zeros it posts the grayscale/binarized ROI to the thread.【F:cogs/shards/cog.py†L142-L155】

2. **Scan Image pressed**
   - Interaction defers ephemerally (thinking), looks up/creates the cache entry keyed by `(guild_id, channel_id, message_id)`, and formats the preview counts line.【F:cogs/shards/cog.py†L168-L205】
   - Ephemeral panel content: “**OCR Preview**” followed by the counts line and four buttons: **Use these counts**, **Manual entry**, **Retry OCR**, **Close**.【F:cogs/shards/cog.py†L193-L307】

3. **Ephemeral button behaviors**
   - **Use these counts** → opens `SetCountsModal` prefilled with OCR data; on submit, writes snapshot, refreshes summary, acknowledges ephemerally.【F:cogs/shards/cog.py†L209-L234】
   - **Manual entry** → opens the same modal without defaults (acts as Skip OCR but only accessible after hitting Scan).【F:cogs/shards/cog.py†L235-L259】
   - **Retry OCR** → clears cache entry and reruns OCR, editing the original ephemeral preview when possible.【F:cogs/shards/cog.py†L261-L278】
   - **Close** → defers ephemerally and edits the message to “Closed.”, removing the view.【F:cogs/shards/cog.py†L280-L291】

4. **Dismiss pressed**
   - Validates author/staff, defers, then deletes the public prompt.【F:cogs/shards/cog.py†L310-L326】

5. **Manual entry via command (fallback)**
   - `!shards set` posts a button that opens `SetCountsModal` with empty defaults, allowing manual entry outside the scan flow.【F:cogs/shards/cog.py†L385-L451】

> **Gap:** The requested “Manual entry (Skip OCR)” option on the first panel is not implemented; users must trigger Scan (or use `!shards set`) to reach the manual modal.【F:cogs/shards/cog.py†L160-L206】【F:cogs/shards/cog.py†L385-L451】
