*** /dev/null
--- a/cogs/shards/renderer.py
@@
+from __future__ import annotations
+import math
+from typing import Dict, List, Tuple
+import discord
+from datetime import datetime, timezone
+
+from .constants import DISPLAY_ORDER, ShardType, PITY_LABELS
+
+UTC = timezone.utc
+
+def _fmt_counts(emoji_map: Dict[ShardType,str], inv: Dict[ShardType,int]) -> List[str]:
+    # Two lines for inventory (mobile tidy) in the agreed order
+    line1 = f"{emoji_map[ShardType.MYSTERY]} {inv.get(ShardType.MYSTERY,0)} · {emoji_map[ShardType.ANCIENT]} {inv.get(ShardType.ANCIENT,0)} · {emoji_map[ShardType.VOID]} {inv.get(ShardType.VOID,0)}"
+    line2 = f"{emoji_map[ShardType.PRIMAL]} {inv.get(ShardType.PRIMAL,0)} · {emoji_map[ShardType.SACRED]} {inv.get(ShardType.SACRED,0)}"
+    return [line1, line2]
+
+def _fmt_pity_line(pity: Dict[Tuple[ShardType,str], int]) -> str:
+    # Pity rendered as: L-Anc 47 | E-Anc 12 | L-Void 0 | E-Void 3 | L-Pri 21 | M-Pri 0 | L-Sac 5
+    parts = []
+    for label, shard, rarity in PITY_LABELS:
+        val = pity.get((shard, rarity.value), 0)
+        parts.append(f"{label} {val}")
+    return "Pity: " + " | ".join(parts)
+
+def build_summary_embed(
+    *,
+    clan_name: str,
+    emoji_map: Dict[ShardType,str],
+    participants: int,
+    totals: Dict[ShardType,int],
+    page_index: int,
+    page_size: int,
+    members_page: List[Tuple[str, Dict[ShardType,int], Dict[Tuple[ShardType,str],int]]],  # (mention, inv, pity)
+    top_risers: List[str],
+    updated_dt: datetime,
+) -> discord.Embed:
+    title = f"Shard & Mercy — {clan_name}"
+    updated_utc = updated_dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
+    embed = discord.Embed(title=title, description=f"Updated: {updated_utc}")
+    # Overview
+    totals_line = f"{emoji_map[ShardType.MYSTERY]} {totals.get(ShardType.MYSTERY,0)} · " \
+                  f"{emoji_map[ShardType.ANCIENT]} {totals.get(ShardType.ANCIENT,0)} · " \
+                  f"{emoji_map[ShardType.VOID]} {totals.get(ShardType.VOID,0)} · " \
+                  f"{emoji_map[ShardType.PRIMAL]} {totals.get(ShardType.PRIMAL,0)} · " \
+                  f"{emoji_map[ShardType.SACRED]} {totals.get(ShardType.SACRED,0)}"
+    overview = f"Participants: **{participants}**\nTotals: {totals_line}"
+    if top_risers:
+        overview += f"\nTop pity risers (since Monday UTC): " + " · ".join(top_risers[:3])
+    embed.add_field(name="Overview", value=overview, inline=False)
+
+    # Members page
+    page_no = page_index + 1
+    total_pages = max(1, math.ceil(max(1, participants) / page_size))
+    embed.add_field(name=f"Members (Page {page_no}/{total_pages})", value="—", inline=False)
+    # For each member, add a small block
+    for mention, inv, pity in members_page:
+        inv_lines = _fmt_counts(emoji_map, inv)
+        pity_line = _fmt_pity_line(pity)
+        block = f"{mention}\n{inv_lines[0]}\n{inv_lines[1]}\n{pity_line}"
+        embed.add_field(name="•", value=block, inline=False)
+
+    notes = [
+        "Guaranteed threshold doesn’t reset mercy.",
+        "Extra Legendary bonus doesn’t reset mercy.",
+        "Mystery is tracked for inventory only.",
+    ]
+    embed.add_field(name="Notes", value="\n".join(notes), inline=False)
+    embed.set_footer(text="Use Prev/Next to browse pages · Page size: 10")
+    return embed
