*** /dev/null
--- a/cogs/shards/sheets_adapter.py
@@
+"""
+Sheets adapter for Shards & Mercy.
+TODO: Wire the marked sections to your existing Google Sheets helpers.
+Uses tabs we defined together:
+  - CONFIG_SHARDS, CONFIG_CLANS, SHARD_SNAPSHOTS, SHARD_EVENTS, MERCY_STATE, SUMMARY_MSGS
+"""
+from __future__ import annotations
+from dataclasses import dataclass
+from typing import Dict, Optional, Tuple, List
+from datetime import datetime, timezone
+
+from .constants import ShardType, Rarity
+
+UTC = timezone.utc
+
+@dataclass
+class ShardsConfig:
+    server_id: int
+    display_timezone: str
+    page_size: int
+    emoji: Dict[ShardType,str]
+    roles_staff_override: List[int]
+
+@dataclass
+class ClanConfig:
+    clan_tag: str
+    clan_name: str
+    role_id: int
+    channel_id: int
+    thread_id: int
+    pinned_message_id: Optional[int]
+    is_enabled: bool
+
+def _now_iso() -> str:
+    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
+
+# ---------- LOAD CONFIG ----------
+def load_config() -> Tuple[ShardsConfig, Dict[str,ClanConfig]]:
+    """
+    TODO: Replace the placeholders with SELECTs from CONFIG_SHARDS / CONFIG_CLANS.
+    Return (global_config, {clan_tag: ClanConfig})
+    """
+    # TODO wire: READ from CONFIG_SHARDS
+    global_cfg = ShardsConfig(
+        server_id=0,
+        display_timezone="UTC",
+        page_size=10,
+        emoji={
+            ShardType.MYSTERY: "🟩",
+            ShardType.ANCIENT: "🟦",
+            ShardType.VOID:    "🟪",
+            ShardType.PRIMAL:  "🟥",
+            ShardType.SACRED:  "🟨",
+        },
+        roles_staff_override=[],
+    )
+    # TODO wire: READ all enabled rows from CONFIG_CLANS
+    clans: Dict[str,ClanConfig] = {}
+    return global_cfg, clans
+
+# ---------- SUMMARY MSG TRACKING ----------
+def get_summary_msg(clan_tag: str) -> Tuple[Optional[int], Optional[int]]:
+    """
+    Returns (thread_id, pinned_message_id) for this clan from SUMMARY_MSGS/CONFIG_CLANS.
+    TODO: Wire to Sheets.
+    """
+    return None, None
+
+def set_summary_msg(clan_tag: str, thread_id: int, message_id: int, page_size: int, page_count: int) -> None:
+    """
+    Upsert SUMMARY_MSGS row for this clan.
+    TODO: Wire to Sheets.
+    """
+    pass
+
+# ---------- SNAPSHOTS & EVENTS ----------
+def append_snapshot(discord_id: int, user_name: str, clan_tag: str, counts: Dict[ShardType,int], source: str, message_link: Optional[str]) -> None:
+    """
+    Append one row to SHARD_SNAPSHOTS.
+    TODO: Wire to Sheets with columns we defined.
+    """
+    # Example payload shape:
+    payload = {
+        "ts_utc": _now_iso(),
+        "discord_id": str(discord_id),
+        "user_name": user_name,
+        "clan_tag": clan_tag,
+        "mystery": counts.get(ShardType.MYSTERY, 0),
+        "ancient": counts.get(ShardType.ANCIENT, 0),
+        "void":    counts.get(ShardType.VOID, 0),
+        "sacred":  counts.get(ShardType.SACRED, 0),
+        "primal":  counts.get(ShardType.PRIMAL, 0),
+        "source":  source,
+        "message_link": message_link or "",
+        "ocr_confidence": "",
+    }
+    # TODO wire: append payload
+    return
+
+def append_events(event_rows: List[Dict]) -> None:
+    """
+    Append many rows to SHARD_EVENTS. Each row carries:
+      ts_utc, actor_discord_id, target_discord_id, clan_tag,
+      type, shard_type, rarity, qty, note, origin, message_link,
+      guaranteed_flag, extra_legendary_flag,
+      batch_id, batch_size, index_in_batch, resets_pity
+    TODO: Wire to Sheets.
+    """
+    return
+
+# ---------- STATE (PITY + LAST SNAPSHOT CACHE) ----------
+def upsert_state(discord_id: int, clan_tag: str, *, pity: Dict[Tuple[ShardType,Rarity], int], inv: Dict[ShardType,int], last_resets: Dict[Tuple[ShardType,Rarity], str]) -> None:
+    """
+    Upsert MERCY_STATE row for this user.
+    TODO: Wire to Sheets with columns we defined (pity_*, inv_* , last_reset_* , updated_ts_utc).
+    """
+    return
+
+# Convenience: fetch last known inventory to compute diffs (optional)
+def get_last_inventory(discord_id: int) -> Optional[Dict[ShardType,int]]:
+    """
+    OPTIONAL helper. If easy in your stack, pull last SHARD_SNAPSHOTS row for this user.
+    Used to prefill diffs in confirm screen.
+    TODO: Wire or return None to skip.
+    """
+    return None
