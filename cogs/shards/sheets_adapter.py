"""
Sheets adapter for Shards & Mercy — uses your EXISTING Google Sheet.

Env vars expected (already present in your setup):
- SERVICE_ACCOUNT_JSON (preferred) or GOOGLE_SERVICE_ACCOUNT_JSON  → service account JSON
- GSHEET_ID (preferred) or CONFIG_SHEET_ID                         → spreadsheet key of your existing sheet

This adapter NEVER creates a new spreadsheet. It reads/writes only the tabs you created:
  CONFIG_SHARDS, CONFIG_CLANS, SHARD_SNAPSHOTS, SHARD_EVENTS, MERCY_STATE, SUMMARY_MSGS
"""

from __future__ import annotations
import os, json
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from .constants import ShardType, Rarity

UTC = timezone.utc
now_iso = lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------- auth + open your existing workbook ----------
_SA_JSON = os.environ.get("SERVICE_ACCOUNT_JSON") or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
if not _SA_JSON:
    raise RuntimeError("Missing SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_JSON env var.")

_SHEET_ID = os.environ.get("GSHEET_ID") or os.environ.get("CONFIG_SHEET_ID")
if not _SHEET_ID:
    raise RuntimeError("Missing GSHEET_ID or CONFIG_SHEET_ID env var (spreadsheet key).")

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_creds = Credentials.from_service_account_info(json.loads(_SA_JSON), scopes=_SCOPES)
_gc = gspread.authorize(_creds)
_WB = _gc.open_by_key(_SHEET_ID)

def _ws_required(name: str):
    """Return an existing worksheet or raise with a helpful message."""
    try:
        return _WB.worksheet(name)
    except gspread.WorksheetNotFound:
        raise RuntimeError(
            f"Worksheet '{name}' not found. Please create it in the existing sheet: {_SHEET_ID}"
        )

# ---------- dataclasses ----------
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

# ---------- helpers ----------
def _toi(val, default=0) -> int:
    try:
        return int(str(val).strip())
    except Exception:
        return default

def _tob(val) -> bool:
    s = str(val).strip().lower()
    return s in {"true", "1", "yes", "y"}

# ---------- CONFIG ----------
def load_config() -> Tuple[ShardsConfig, Dict[str, ClanConfig]]:
    cfg_ws = _ws_required("CONFIG_SHARDS")
    rows = cfg_ws.get_all_records()
    if not rows:
        raise RuntimeError("CONFIG_SHARDS has no rows.")

    r0 = rows[0]
    cfg = ShardsConfig(
        server_id=_toi(r0.get("server_id", 0)),
        display_timezone=str(r0.get("display_timezone", "UTC")),
        page_size=_toi(r0.get("page_size", 10)),
        emoji={
            ShardType.MYSTERY: str(r0.get("emoji_mystery", "🟩")),
            ShardType.ANCIENT: str(r0.get("emoji_ancient", "🟦")),
            ShardType.VOID:    str(r0.get("emoji_void", "🟪")),
            ShardType.PRIMAL:  str(r0.get("emoji_primal", "🟥")),
            ShardType.SACRED:  str(r0.get("emoji_sacred", "🟨")),
        },
        roles_staff_override=[_toi(x) for x in str(r0.get("roles_staff_override", "")).replace(" ", "").split(",") if x],
    )

    clans_ws = _ws_required("CONFIG_CLANS")
    clan_rows = clans_ws.get_all_records()
    clans: Dict[str, ClanConfig] = {}
    for r in clan_rows:
        if not _tob(r.get("is_enabled", True)):
            continue
        clans[str(r["clan_tag"])] = ClanConfig(
            clan_tag=str(r["clan_tag"]),
            clan_name=str(r["clan_name"]),
            role_id=_toi(r["role_id"]),
            channel_id=_toi(r["channel_id"]),
            thread_id=_toi(r["thread_id"]),
            pinned_message_id=_toi(r.get("pinned_message_id") or 0) or None,
            is_enabled=True,
        )
    return cfg, clans

# ---------- SUMMARY MSG TRACKING ----------
def get_summary_msg(clan_tag: str) -> Tuple[Optional[int], Optional[int]]:
    # Prefer SUMMARY_MSGS; fallback to CONFIG_CLANS.pinned_message_id
    try:
        ws = _ws_required("SUMMARY_MSGS")
        for r in ws.get_all_records():
            if str(r.get("clan_tag")) == clan_tag:
                tid = _toi(r.get("thread_id") or 0) or None
                mid = _toi(r.get("pinned_message_id") or 0) or None
                return tid, mid
    except RuntimeError:
        pass  # If the worksheet doesn't exist yet, fall back below.

    ws2 = _ws_required("CONFIG_CLANS")
    for r in ws2.get_all_records():
        if str(r.get("clan_tag")) == clan_tag:
            tid = _toi(r.get("thread_id") or 0) or None
            mid = _toi(r.get("pinned_message_id") or 0) or None
            return tid, mid
    return None, None

def set_summary_msg(clan_tag: str, thread_id: int, message_id: int, page_size: int, page_count: int) -> None:
    ws = _ws_required("SUMMARY_MSGS")
    rows = ws.get_all_records()
    target_idx = None
    for i, r in enumerate(rows, start=2):  # header at row 1
        if str(r.get("clan_tag")) == clan_tag:
            target_idx = i
            break

    payload = [
        clan_tag,
        str(thread_id),
        str(message_id),
        now_iso(),
        str(page_count),
        str(page_size),
    ]

    if target_idx:
        ws.update(f"A{target_idx}:F{target_idx}", [payload], value_input_option="RAW")
    else:
        ws.append_row(
            ["clan_tag", "thread_id", "pinned_message_id", "last_edit_ts_utc", "page_count", "page_size"]
            if not rows else []
        )
        ws.append_row(payload, value_input_option="RAW")

# ---------- SNAPSHOTS & EVENTS ----------
def append_snapshot(discord_id: int, user_name: str, clan_tag: str,
                    counts: Dict[ShardType, int], source: str, message_link: Optional[str]) -> None:
    ws = _ws_required("SHARD_SNAPSHOTS")
    # assume header already exists (you created tabs)
    row = [
        now_iso(),
        str(discord_id),
        user_name,
        clan_tag,
        str(counts.get(ShardType.MYSTERY, 0)),
        str(counts.get(ShardType.ANCIENT, 0)),
        str(counts.get(ShardType.VOID, 0)),
        str(counts.get(ShardType.SACRED, 0)),
        str(counts.get(ShardType.PRIMAL, 0)),
        source,
        message_link or "",
        "",  # ocr_confidence (kept for later)
    ]
    ws.append_row(row, value_input_option="RAW")

def append_events(event_rows: List[Dict]) -> None:
    ws = _ws_required("SHARD_EVENTS")
    ordered = []
    for r in event_rows:
        ordered.append([
            r.get("ts_utc", now_iso()),
            str(r.get("actor_discord_id", "")),
            str(r.get("target_discord_id", "")),
            str(r.get("clan_tag", "")),
            str(r.get("type", "")),
            str(r.get("shard_type", "")),
            str(r.get("rarity", "")),
            str(r.get("qty", 0)),
            str(r.get("note", "")),
            str(r.get("origin", "")),
            str(r.get("message_link", "")),
            "TRUE" if r.get("guaranteed_flag") else "FALSE",
            "TRUE" if r.get("extra_legendary_flag") else "FALSE",
            str(r.get("batch_id", "")),
            str(r.get("batch_size", "")),
            str(r.get("index_in_batch", "")),
            "TRUE" if r.get("resets_pity") else "FALSE",
            str(r.get("undo_of_event_id", "")),
        ])
    if ordered:
        ws.append_rows(ordered, value_input_option="RAW")

# ---------- STATE (materialized current pity + last inv cache) ----------
def upsert_state(discord_id: int, clan_tag: str, *,
                 pity: Dict[Tuple[ShardType, Rarity], int],
                 inv: Dict[ShardType, int],
                 last_resets: Dict[Tuple[ShardType, Rarity], str]) -> None:
    ws = _ws_required("MERCY_STATE")
    rows = ws.get_all_records()
    idx = None
    for i, r in enumerate(rows, start=2):
        if str(r.get("discord_id")) == str(discord_id) and str(r.get("clan_tag")) == clan_tag:
            idx = i
            break

    def pit(st: ShardType, ra: Rarity) -> int:
        return int(pity.get((st, ra), 0))

    def last(st: ShardType, ra: Rarity) -> str:
        return str(last_resets.get((st, ra), ""))

    payload = [
        str(discord_id), clan_tag,
        str(pit(ShardType.ANCIENT, Rarity.LEGENDARY)),
        str(pit(ShardType.ANCIENT, Rarity.EPIC)),
        str(pit(ShardType.VOID,    Rarity.LEGENDARY)),
        str(pit(ShardType.VOID,    Rarity.EPIC)),
        str(pit(ShardType.SACRED,  Rarity.LEGENDARY)),
        str(pit(ShardType.PRIMAL,  Rarity.LEGENDARY)),
        str(pit(ShardType.PRIMAL,  Rarity.MYTHICAL)),
        str(inv.get(ShardType.MYSTERY, 0)),
        str(inv.get(ShardType.ANCIENT, 0)),
        str(inv.get(ShardType.VOID,    0)),
        str(inv.get(ShardType.SACRED,  0)),
        str(inv.get(ShardType.PRIMAL,  0)),
        last(ShardType.ANCIENT, Rarity.LEGENDARY),
        last(ShardType.ANCIENT, Rarity.EPIC),
        last(ShardType.VOID,    Rarity.LEGENDARY),
        last(ShardType.VOID,    Rarity.EPIC),
        last(ShardType.SACRED,  Rarity.LEGENDARY),
        last(ShardType.PRIMAL,  Rarity.LEGENDARY),
        last(ShardType.PRIMAL,  Rarity.MYTHICAL),
        now_iso(),
    ]

    if idx:
        ws.update(f"A{idx}:U{idx}", [payload], value_input_option="RAW")
    else:
        ws.append_row(payload, value_input_option="RAW")

# Optional helper for prefill UIs (safe to leave unused)
def get_last_inventory(discord_id: int, clan_tag: Optional[str] = None) -> Optional[Dict[ShardType, int]]:
    try:
        ws = _ws_required("SHARD_SNAPSHOTS")
        rows = ws.get_all_records()
        rows = [r for r in rows if str(r.get("discord_id")) == str(discord_id)]
        if clan_tag:
            rows = [r for r in rows if str(r.get("clan_tag")) == str(clan_tag)]
        if not rows:
            return None
        r = rows[-1]
        return {
            ShardType.MYSTERY: _toi(r.get("mystery", 0)),
            ShardType.ANCIENT: _toi(r.get("ancient", 0)),
            ShardType.VOID:    _toi(r.get("void", 0)),
            ShardType.SACRED:  _toi(r.get("sacred", 0)),
            ShardType.PRIMAL:  _toi(r.get("primal", 0)),
        }
    except Exception:
        return None
