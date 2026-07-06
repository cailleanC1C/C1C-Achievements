"""Quota-safe HelpCommands seed/export support for Achievements."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from discord.ext import commands

BOT_KEY = "achievements"
HELP_COMMANDS_SHEET_ID_CONFIG_KEY = "HELP_COMMANDS_SHEET_ID"
HELP_COMMANDS_TAB_CONFIG_KEY = "HELP_COMMANDS_TAB"
REQUIRED_HEADERS = [
    "enabled",
    "bot_key",
    "command_key",
    "command",
    "usage",
    "category",
    "access_level",
    "summary",
    "details",
    "notes",
    "sort_order",
]
ALLOWED_ACCESS_LEVELS = {"user", "staff", "admin", "hidden"}
REQUIRED_METADATA = {"function_group", "help_section", "access_tier", "tier"}
LOCAL_HELP_TOPICS = ("claim", "claims", "gk")

log = logging.getLogger("c1c-claims")


class HelpSeedError(RuntimeError):
    """Clear operator-facing help seed failure."""


@dataclass
class SeedResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    manual_review: dict[str, int] = field(default_factory=lambda: {
        "category": 0,
        "access_level": 0,
        "summary": 0,
        "details": 0,
        "sort_order": 0,
    })
    local_help_only: list[str] = field(default_factory=list)
    rows_filled: int = 0
    rows_appended: int = 0

    @property
    def needs_manual_review(self) -> int:
        return sum(self.manual_review.values())


def normalize_command_key(qualified_name: str) -> str:
    return "_".join(str(qualified_name or "").strip().lower().split())


def _cell(row: list[Any], idx: int) -> str:
    return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ""


def _a1(row: int, col: int) -> str:
    name = ""
    while col:
        col, rem = divmod(col - 1, 26)
        name = chr(65 + rem) + name
    return f"{name}{row}"


def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "response", None) is not None and getattr(exc.response, "status_code", None) == 429:
        return True
    return "429" in str(exc) or "rate limit" in str(exc).lower() or "quota" in str(exc).lower()


def _first_line(text: Any) -> str:
    s = str(text or "").strip()
    return s.splitlines()[0].strip() if s else ""


def command_to_row(command: commands.Command) -> tuple[dict[str, str] | None, list[str], str | None]:
    extras = getattr(command, "extras", {}) or {}
    missing_meta = sorted(k for k in REQUIRED_METADATA if not extras.get(k))
    if missing_meta:
        return None, [], f"missing metadata: {', '.join(missing_meta)}"

    key = normalize_command_key(command.qualified_name)
    if key == "helpseed":
        return None, [], "seed command is not exported"

    category = str(extras.get("help_section") or extras.get("function_group") or "").strip()
    access = str(extras.get("access_tier") or "").strip().lower()
    if access not in ALLOWED_ACCESS_LEVELS:
        access = ""

    usage = str(extras.get("help_usage") or "").strip()
    if not usage:
        signature = str(getattr(command, "signature", "") or "").strip()
        usage = f"!{command.qualified_name}" + (f" {signature}" if signature else "")

    summary = str(getattr(command, "brief", None) or "").strip()
    if not summary:
        summary = str(getattr(command, "short_doc", None) or "").strip()
    if not summary:
        summary = _first_line(getattr(command, "help", None))

    details = str(getattr(command, "help", None) or "").strip() or summary

    manual = []
    if not category:
        manual.append("category")
    if not access:
        manual.append("access_level")
    if not summary:
        manual.append("summary")
    if not details:
        manual.append("details")
    manual.append("sort_order")

    return {
        "enabled": "FALSE",
        "bot_key": BOT_KEY,
        "command_key": key,
        "command": f"!{command.qualified_name}",
        "usage": usage,
        "category": category,
        "access_level": access,
        "summary": summary,
        "details": details,
        "notes": "",
        "sort_order": "",
    }, manual, None


def collect_help_rows(bot: commands.Bot) -> tuple[list[tuple[dict[str, str], list[str]]], list[tuple[str, str]], list[str]]:
    real_names = {normalize_command_key(c.qualified_name) for c in bot.walk_commands()}
    rows, skipped = [], []
    for command in bot.walk_commands():
        key = normalize_command_key(command.qualified_name)
        if key == "helpseed":
            skipped.append((key, "seed command is not exported"))
            continue
        row, manual, reason = command_to_row(command)
        if reason:
            skipped.append((key, reason))
            continue
        rows.append((row, manual))
    local_only = [topic for topic in LOCAL_HELP_TOPICS if topic not in real_names]
    return rows, skipped, local_only


def _read_help_target_config(achievements_workbook) -> tuple[str, str]:
    try:
        config_ws = achievements_workbook.worksheet("Config")
    except Exception as exc:
        raise HelpSeedError("Configured Achievements Config tab is missing or unreadable.") from exc

    rows = config_ws.get_all_values()
    headers = [str(h).strip() for h in (rows[0] if rows else [])]
    header_lookup = {header.lower(): idx for idx, header in enumerate(headers) if header}
    missing_headers = [name for name in ("Key", "Value") if name.lower() not in header_lookup]
    if missing_headers:
        raise HelpSeedError("Achievements Config tab is missing required header(s): " + ", ".join(missing_headers))

    key_idx = header_lookup["key"]
    value_idx = header_lookup["value"]
    config: dict[str, str] = {}
    for row in rows[1:]:
        key = _cell(row, key_idx).strip().upper()
        if not key:
            continue
        config[key] = _cell(row, value_idx).strip()

    sheet_id = config.get(HELP_COMMANDS_SHEET_ID_CONFIG_KEY, "").strip()
    tab = config.get(HELP_COMMANDS_TAB_CONFIG_KEY, "").strip()
    if not sheet_id:
        raise HelpSeedError("Config key HELP_COMMANDS_SHEET_ID is required and must not be empty.")
    if not tab:
        raise HelpSeedError("Config key HELP_COMMANDS_TAB is required and must not be empty.")
    return sheet_id, tab


def _open_configured_help_worksheet(gc, achievements_sheet_id: str):
    achievements_wb = gc.open_by_key(achievements_sheet_id)
    target_sheet_id, target_tab = _read_help_target_config(achievements_wb)
    try:
        target_wb = gc.open_by_key(target_sheet_id)
    except Exception as exc:
        raise HelpSeedError("Configured HelpCommands sheet HELP_COMMANDS_SHEET_ID is missing or unreadable.") from exc
    try:
        return target_wb.worksheet(target_tab)
    except Exception as exc:
        raise HelpSeedError(f"Configured HelpCommands tab {target_tab!r} is missing or unreadable.") from exc


def open_help_worksheet(gspread_module=None):
    achievements_sid = os.getenv("CONFIG_SHEET_ID", "").strip()
    if not achievements_sid:
        raise HelpSeedError("CONFIG_SHEET_ID is missing; cannot open the Achievements config workbook.")
    raw = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise HelpSeedError("SERVICE_ACCOUNT_JSON is missing; cannot open the Achievements config workbook.")
    if gspread_module is None:
        import gspread as gspread_module
        from google.oauth2.service_account import Credentials
    else:
        from google.oauth2.service_account import Credentials
    data = json.loads(raw) if raw.startswith("{") else json.load(open(raw, "r", encoding="utf-8"))
    creds = Credentials.from_service_account_info(data, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread_module.authorize(creds)
    return _open_configured_help_worksheet(gc, achievements_sid)


def seed_help_commands(bot: commands.Bot, worksheet) -> SeedResult:
    rows_to_seed, skipped, local_only = collect_help_rows(bot)
    result = SeedResult(skipped=len(skipped), local_help_only=local_only)
    values = worksheet.get_all_values()
    physical_rows = len(values)
    if not values:
        raise HelpSeedError("HelpCommands sheet is empty; required headers are missing.")
    headers = [str(h).strip() for h in values[0]]
    col = {h: i for i, h in enumerate(headers) if h}
    missing = [h for h in REQUIRED_HEADERS if h not in col]
    if missing:
        raise HelpSeedError("HelpCommands sheet missing required headers: " + ", ".join(missing))

    existing, blank_rows = {}, []
    schema_idxs = [col[h] for h in REQUIRED_HEADERS]
    for offset, row in enumerate(values[1:], start=2):
        bot_key, command_key = _cell(row, col["bot_key"]), _cell(row, col["command_key"])
        if bot_key and command_key:
            existing[(bot_key, command_key)] = (offset, row)
        elif all(not _cell(row, idx) for idx in schema_idxs):
            blank_rows.append(offset)

    updates, fill_rows, append_rows = [], [], []
    for row_map, manual in rows_to_seed:
        key = row_map["command_key"]
        for field_name in manual:
            result.manual_review[field_name] += 1
        match = existing.get((BOT_KEY, key))
        if match:
            rownum, old = match
            new = [_cell(old, i) for i in range(len(headers))]
            for h in ("bot_key", "command_key", "command", "usage"):
                new[col[h]] = row_map[h]
            if row_map["access_level"]:
                new[col["access_level"]] = row_map["access_level"]
            for h in ("category", "summary", "details"):
                if not new[col[h]]:
                    new[col[h]] = row_map[h]
            updates.append({"range": f"A{rownum}:{_a1(rownum, len(headers))}", "values": [new]})
            result.updated += 1
            log.info("[helpseed] command=%s action=updated missing_manual=%s", key, manual)
        else:
            new = [""] * len(headers)
            for h in REQUIRED_HEADERS:
                new[col[h]] = row_map[h]
            if blank_rows:
                rownum = blank_rows.pop(0)
                fill_rows.append({"range": f"A{rownum}:{_a1(rownum, len(headers))}", "values": [new]})
                result.rows_filled += 1
            else:
                append_rows.append(new)
                result.rows_appended += 1
            result.created += 1
            log.info("[helpseed] command=%s action=created missing_manual=%s", key, manual)

    if updates or fill_rows:
        if not callable(getattr(worksheet, "batch_update", None)):
            raise HelpSeedError("HelpCommands worksheet.batch_update is required for updates/fills but is unavailable.")
        worksheet.batch_update(updates + fill_rows, value_input_option="RAW")
    if append_rows:
        if not callable(getattr(worksheet, "append_rows", None)):
            raise HelpSeedError("HelpCommands worksheet.append_rows is required for appends but is unavailable.")
        worksheet.append_rows(append_rows, value_input_option="RAW")

    log.info(
        "[helpseed] physical_rows_read=%s real_existing_rows=%s blank_rows_available=%s rows_filled=%s rows_appended=%s rows_updated=%s skipped=%s",
        physical_rows, len(existing), len(blank_rows) + result.rows_filled, result.rows_filled, result.rows_appended, result.updated, result.skipped,
    )
    for key, reason in skipped:
        log.info("[helpseed] command=%s action=skipped reason=%s", key, reason)
    return result


def format_seed_reply(result: SeedResult) -> str:
    lines = [
        "Help registry seed complete.",
        f"Created: {result.created}",
        f"Updated: {result.updated}",
        f"Skipped: {result.skipped}",
        f"Needs manual review: {result.needs_manual_review}",
        "",
        "Manual review:",
        f"- missing category: {result.manual_review['category']}",
        f"- missing access_level: {result.manual_review['access_level']}",
        f"- missing summary: {result.manual_review['summary']}",
        f"- missing details: {result.manual_review['details']}",
        f"- missing sort_order: {result.manual_review['sort_order']}",
    ]
    if result.local_help_only:
        lines.append("")
        lines.append("Local help topics not exported:")
        lines.extend(f"- {topic} is local help guidance, not a registered command." for topic in result.local_help_only)
    return "\n".join(lines)


__all__ = [
    "ALLOWED_ACCESS_LEVELS", "BOT_KEY", "HELP_COMMANDS_SHEET_ID_CONFIG_KEY", "HELP_COMMANDS_TAB_CONFIG_KEY", "HelpSeedError", "REQUIRED_HEADERS",
    "SeedResult", "collect_help_rows", "command_to_row", "format_seed_reply", "normalize_command_key",
    "open_help_worksheet", "seed_help_commands", "_read_help_target_config", "_open_configured_help_worksheet", "_is_rate_limit",
]
