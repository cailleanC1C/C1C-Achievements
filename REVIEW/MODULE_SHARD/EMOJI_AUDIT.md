# Shard Emoji Usage Audit

| Location | Purpose | Current Source | Custom emoji? | Notes |
| --- | --- | --- | --- | --- |
| `ShardsConfig.emoji` map from Sheets【F:cogs/shards/sheets_adapter.py†L91-L99】 | Persist configured shard emoji strings | Google Sheet columns `emoji_*`, defaulting to colored squares | ✅ if sheet stores `<:name:id>` strings, but defaults fall back to unicode | Defaults violate the policy when the sheet is blank; needs enforced custom IDs. |
| `ShardsCog._emoji_or_abbr` fallback map【F:cogs/shards/cog.py†L94-L115】 | Formats shard labels in OCR preview and elsewhere | `cfg.emoji` lookup by shorthand, else hardcoded colored-square text | ❌ uses unicode fallback (`🟩Myst`, etc.) | Replace with centralized mapping; drop text suffix once IDs return full emoji codes. |
| `SetCountsModal` field labels【F:cogs/shards/views.py†L10-L23】 | Modal input labels for manual counts | Literal unicode squares in labels | ❌ | Should pull display emoji from shared mapping so modal mirrors server icons. |
| `AddPullsStart` buttons (mercy flow)【F:cogs/shards/views.py†L34-L47】 | Buttons to pick shard type | Literal unicode squares in button labels | ❌ | Swap to centralized emoji helper. |
| `!shards help` copy【F:cogs/shards/cog.py†L400-L407】 | Help text describing shards | Inline unicode squares | ❌ | Update copy to interpolate custom emoji names. |

## Recommended central mapping
- **File:** `assets/emojis/shards.json`
```json
{
  "mystery": "<:mystery_shard:000000000000000000>",
  "ancient": "<:ancient_shard:000000000000000000>",
  "void": "<:void_shard:000000000000000000>",
  "primal": "<:primal_shard:000000000000000000>",
  "sacred": "<:sacred_shard:000000000000000000>"
}
```
- **Access helper signature:**
```python
def get_shard_emoji(shard: ShardType, *, overrides: Mapping[ShardType, str] | None = None) -> str:
    """Return the configured custom emoji for the shard, falling back to the JSON mapping."""
```
- **Call sites to update:**
  1. `ShardsCog._emoji_or_abbr` → delete fallback text and delegate to `get_shard_emoji`.
  2. `SetCountsModal` labels → format labels dynamically.
  3. `AddPullsStart` buttons → use helper.
  4. Any string literals referencing shard emoji (`!shards help`, summary renderer) → inject helper output.【F:cogs/shards/renderer.py†L11-L58】
  5. Sheets config loader → validate/normalize IDs rather than unicode defaults.【F:cogs/shards/sheets_adapter.py†L91-L99】
