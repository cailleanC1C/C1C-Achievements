# UI Flow Map — Shard Threads

## Trigger: Message in clan shard thread
- Preconditions: user message in a configured shard thread with an image attachment (current implementation ignores messages without images).【F:cogs/shards/cog.py†L128-L140】
- Bot action: posts a **public** prompt message with persistent buttons (timeout 5 minutes).【F:cogs/shards/cog.py†L159-L343】
  - **Scan Image** (primary) → goes to *OCR Preview* flow (ephemeral).【F:cogs/shards/cog.py†L168-L305】
  - **Dismiss** (secondary) → deletes the public prompt if pressed by author/staff.【F:cogs/shards/cog.py†L310-L327】
  - **Manual entry (Skip OCR)** — **required addition** per spec. This button should open the manual modal immediately. *(Gap: not yet implemented.)*【F:cogs/shards/cog.py†L159-L333】

> **Edge-case requirement:** Manual-entry button must be available even when a thread message lacks images. Today, the listener returns early and nothing is posted, so the manual path never appears; planned fix is to surface a manual-only button when no image is present.【F:cogs/shards/cog.py†L133-L166】

## Flow: Scan Image → OCR Preview (ephemeral)
1. **Deferral:** Interaction defers ephemerally with thinking indicator.【F:cogs/shards/cog.py†L179-L205】
2. **OCR fetch:** Uses cache `(guild, channel, message)`; runs OCR via `asyncio.to_thread` on cache miss.【F:cogs/shards/cog.py†L82-L91】【F:cogs/shards/cog.py†L185-L206】
3. **Ephemeral panel:** Bot replies ephemerally with `**OCR Preview**` text and a 4-button view (timeout 3 minutes).【F:cogs/shards/cog.py†L193-L305】
   - **Use these counts** (success) → opens `SetCountsModal` prefilled with OCR values; on submit, writes snapshot and responds ephemerally “Counts saved…”.【F:cogs/shards/cog.py†L209-L234】
   - **Manual entry** (primary) → opens empty `SetCountsModal`; same save path as above.【F:cogs/shards/cog.py†L235-L259】
   - **Retry OCR** (secondary) → defers, clears cache, re-runs OCR, edits the original ephemeral preview.【F:cogs/shards/cog.py†L261-L278】
   - **Close** (danger) → defers and edits the ephemeral message to “Closed.” without buttons.【F:cogs/shards/cog.py†L280-L291】

## Flow: Manual entry (Skip OCR) — *planned*
- **Entry point:** New button on the public prompt (and fallback when there is no attachment).
- **Action:** Immediately open `SetCountsModal` with empty fields; bypass OCR/cache entirely.
- **Post-submit:** Reuse existing manual save logic (snapshot append + summary refresh + ephemeral confirmation).【F:cogs/shards/cog.py†L235-L259】
