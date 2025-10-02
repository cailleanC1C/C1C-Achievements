"""
Sheets adapter for Shards & Mercy.
Wire the TODOs to your existing Google Sheets helpers using the tabs we defined:
  - CONFIG_SHARDS, CONFIG_CLANS, SHARD_SNAPSHOTS, SHARD_EVENTS, MERCY_STATE, SUMMARY_MSGS
This file ships with safe no-ops so the bot can load before you connect Sheets.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timezone

from .constants import ShardType, Rarity

UTC = timezone.utc
now_iso = lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

@dataclass
class ShardsConfig:
    server_id: int
    display_timezone: str
    page_size: int
    emoji: Dict[ShardType, str]
    roles_staff_override: List[int]

@dataclass
class ClanConfig:
    clan_tag: str
    clan_name: str
    role_id: int
    channel_id: int
    thread_id: int
    pinned_message_id: Optional[int]
    is_enabled: bool

# --------- LOAD CONFIG ---------
def load_config() -> Tuple[ShardsConfig, Dict[str, ClanConfig]]:
    """
    TODO: Replace placeholders with SELECTs from CONFIG_SHARDS / CONFIG_CLANS.
    """
    cfg = ShardsConfig(
        server_id=0,
        display_timezone="UTC",
        page_size=10,
        emoji={
            ShardType.MYSTERY: "🟩",
            ShardType.ANCIENT: "🟦",
            ShardType.VOID:    "🟪",
            ShardType.PRIMAL:  "🟥",
            ShardType.SACRED:  "🟨",
        },
        roles_staff_override=[],
    )
    clans: Dict[str, ClanConfig] = {}  # TODO: populate from CONFIG_CLANS
    return cfg, clans

# --------- SUMMARY MSG TRACKING ---------
def get_summary_msg(clan_tag: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Return (thread_id, pinned_message_id) from SUMMARY_MSGS/CONFIG_CLANS.
    TODO: Wire to Sheets.
    """
    return None, None

def set_summary_msg(clan_tag: str, thread_id: int, message_id: int, page_size: int, page_count: int) -> None:
    """
    Upsert SUMMARY_MSGS row for this clan.
    TODO: Wire to Sheets.
    """
    return

# --------- SNAPSHOTS & EVENTS ---------
def append_snapshot(discord_id: int, user_name: str, clan_tag: str,
                    counts: Dict[ShardType, int], source: str, message_link: Optional[str]) -> None:
    """
    Append one row to SHARD_SNAPSHOTS.
    TODO: Wire to Sheets with the agreed columns.
    """
    payload = {
        "ts_utc": now_iso(),
        "discord_id": str(discord_id),
        "user_name": user_name,
        "clan_tag": clan_tag,
        "mystery": counts.get(ShardType.MYSTERY, 0),
        "ancient": counts.get(ShardType.ANCIENT, 0),
        "void":    counts.get(ShardType.VOID, 0),
        "sacred":  counts.get(ShardType.SACRED, 0),
        "primal":  counts.get(ShardType.PRIMAL, 0),
        "source":  source,
        "message_link": message_link or "",
        "ocr_confidence": "",
    }
    # TODO: append payload to SHARD_SNAPSHOTS
    return

def append_events(event_rows: List[Dict]) -> None:
    """
    Append many rows to SHARD_EVENTS. Each row carries at least:
      ts_utc, actor_discord_id, target_discord_id, clan_tag,
      type, shard_type, rarity, qty, note, origin, message_link,
      guaranteed_flag, extra_legendary_flag,
      batch_id, batch_size, index_in_batch, resets_pity
    TODO: Wire to Sheets.
    """
    return

# --------- STATE (PITY + LAST SNAPSHOT CACHE) ---------
def upsert_state(discord_id: int, clan_tag: str, *,
                 pity: Dict[Tuple[ShardType, Rarity], int],
                 inv: Dict[ShardType, int],
                 last_resets: Dict[Tuple[ShardType, Rarity], str]) -> None:
    """
    Upsert MERCY_STATE row for this user.
    TODO: Wire to Sheets with columns (pity_*, inv_*, last_reset_*, updated_ts_utc).
    """
    return

# Optional helper to prefill diffs
def get_last_inventory(discord_id: int) -> Optional[Dict[ShardType, int]]:
    """
    If easy in your stack, return last snapshot's inventory for this user.
    Used only to prefill a form; safe to leave as None.
    """
    return None
