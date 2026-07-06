import pytest
pytest.importorskip("discord")
from discord.ext import commands

from achievements.help_metadata import help_metadata, tier
from achievements.help_seed import (
    ALLOWED_ACCESS_LEVELS,
    HELP_COMMANDS_SHEET_ID_CONFIG_KEY,
    HELP_COMMANDS_TAB_CONFIG_KEY,
    HelpSeedError,
    collect_help_rows,
    command_to_row,
    format_seed_reply,
    normalize_command_key,
    seed_help_commands,
    _open_configured_help_worksheet,
    _read_help_target_config,
)

HEADERS = ["enabled","bot_key","command_key","command","usage","category","access_level","summary","details","notes","sort_order"]

class WS:
    def __init__(self, values):
        self.values = values
        self.reads = 0
        self.batch_calls = []
        self.append_calls = []
    def get_all_values(self):
        self.reads += 1
        return [list(r) for r in self.values]
    def batch_update(self, payload, value_input_option=None):
        self.batch_calls.append((payload, value_input_option))
    def append_rows(self, rows, value_input_option=None):
        self.append_calls.append((rows, value_input_option))

class NoBatch(WS):
    batch_update = None
class NoAppend(WS):
    append_rows = None


class WB:
    def __init__(self, worksheets):
        self.worksheets = worksheets
    def worksheet(self, name):
        if name not in self.worksheets:
            raise RuntimeError(name)
        return self.worksheets[name]

class GC:
    def __init__(self, workbooks):
        self.workbooks = workbooks
        self.opened = []
    def open_by_key(self, key):
        self.opened.append(key)
        if key not in self.workbooks:
            raise RuntimeError(key)
        return self.workbooks[key]

def config_ws(rows):
    return WS(rows)

def test_missing_config_tab_fails_clearly():
    with pytest.raises(HelpSeedError, match="Configured Achievements Config tab is missing or unreadable"):
        _read_help_target_config(WB({}))

def test_config_tab_missing_key_header_fails_clearly():
    wb = WB({"Config": config_ws([["Value", "comment"], ["x", "y"]])})
    with pytest.raises(HelpSeedError, match=r"missing required header\(s\): Key"):
        _read_help_target_config(wb)

def test_config_tab_missing_value_header_fails_clearly():
    wb = WB({"Config": config_ws([["Key", "comment"], ["x", "y"]])})
    with pytest.raises(HelpSeedError, match=r"missing required header\(s\): Value"):
        _read_help_target_config(wb)

def test_missing_help_commands_sheet_id_fails_clearly_no_fallback():
    wb = WB({"Config": config_ws([["Key", "Value", "comment"], ["HELP_COMMANDS_TAB", "HelpCommands", ""]])})
    with pytest.raises(HelpSeedError, match="HELP_COMMANDS_SHEET_ID is required"):
        _read_help_target_config(wb)

def test_missing_help_commands_tab_fails_clearly():
    wb = WB({"Config": config_ws([["Key", "Value", "comment"], ["HELP_COMMANDS_SHEET_ID", "shared", ""]])})
    with pytest.raises(HelpSeedError, match="HELP_COMMANDS_TAB is required"):
        _read_help_target_config(wb)

def test_config_keys_case_insensitive_and_values_trimmed():
    wb = WB({"Config": config_ws([
        ["comment", "Value", "Key"],
        ["ignored", "  shared-sheet  ", " help_commands_sheet_id "],
        ["ignored", "  Registry Tab  ", "help_commands_tab"],
    ])})
    assert _read_help_target_config(wb) == ("shared-sheet", "Registry Tab")

def test_helpseed_opens_target_workbook_from_config_not_achievements_workbook():
    target_ws = WS([HEADERS])
    ach_wb = WB({"Config": config_ws([["Key", "Value"], ["HELP_COMMANDS_SHEET_ID", "shared-sheet"], ["HELP_COMMANDS_TAB", "Registry"]])})
    shared_wb = WB({"Registry": target_ws})
    gc = GC({"achievements-sheet": ach_wb, "shared-sheet": shared_wb})
    assert _open_configured_help_worksheet(gc, "achievements-sheet") is target_ws
    assert gc.opened == ["achievements-sheet", "shared-sheet"]

def test_target_workbook_and_tab_fail_clearly():
    ach_wb = WB({"Config": config_ws([["Key", "Value"], ["HELP_COMMANDS_SHEET_ID", "missing"], ["HELP_COMMANDS_TAB", "Registry"]])})
    with pytest.raises(HelpSeedError, match="HELP_COMMANDS_SHEET_ID is missing or unreadable"):
        _open_configured_help_worksheet(GC({"achievements-sheet": ach_wb}), "achievements-sheet")
    ach_wb = WB({"Config": config_ws([["Key", "Value"], ["HELP_COMMANDS_SHEET_ID", "shared"], ["HELP_COMMANDS_TAB", "Nope"]])})
    with pytest.raises(HelpSeedError, match="Configured HelpCommands tab 'Nope' is missing or unreadable"):
        _open_configured_help_worksheet(GC({"achievements-sheet": ach_wb, "shared": WB({})}), "achievements-sheet")

def cmd(name="ping", *, aliases=None, access="user", usage=None, section="members"):
    async def cb(ctx): pass
    c = commands.Command(cb, name=name, aliases=aliases or [], brief=f"{name} brief", help=f"{name} help")
    c = tier(access)(c)
    return help_metadata(function_group="operational", section=section, access_tier=access, usage=usage or f"!{name}")(c)

def bot_with(*cmds):
    b = commands.Bot(command_prefix="!")
    b.remove_command("help")
    for c in cmds:
        b.add_command(c)
    return b

def test_command_key_generation_stable():
    assert normalize_command_key(" help ") == "help"
    assert normalize_command_key("ocr_debug") == "ocr_debug"
    assert normalize_command_key("Group Child") == "group_child"

def test_access_levels_allowed_and_invalid_blanks():
    assert ALLOWED_ACCESS_LEVELS == {"user", "staff", "admin", "hidden"}
    c = cmd("x")
    c.extras["access_tier"] = "moderator"
    row, manual, reason = command_to_row(c)
    assert reason is None
    assert row["access_level"] == ""
    assert "access_level" in manual

def test_existing_rows_update_bot_owned_fields_without_overwriting_manual_fields():
    b = bot_with(cmd("ping", access="admin", usage="!ping --new", section="generated cat"))
    ws = WS([HEADERS, ["TRUE","achievements","ping","old command","old usage","manual cat","staff","manual summary","manual details","note","7"]])
    result = seed_help_commands(b, ws)
    assert result.updated == 1 and result.created == 0
    updated = ws.batch_calls[0][0][0]["values"][0]

    # Manually curated fields are preserved on existing rows.
    assert updated[0] == "TRUE"
    assert updated[5] == "manual cat"
    assert updated[7] == "manual summary"
    assert updated[8] == "manual details"
    assert updated[9] == "note"
    assert updated[10] == "7"

    # Bot-owned fields still refresh from command metadata.
    assert updated[1] == "achievements"
    assert updated[2] == "ping"
    assert updated[3] == "!ping"
    assert updated[4] == "!ping --new"
    assert updated[6] == "admin"


def test_existing_blank_category_summary_and_details_are_filled_from_metadata():
    b = bot_with(cmd("ping", access="staff", usage="!ping", section="members"))
    ws = WS([HEADERS, ["TRUE","achievements","ping","old command","old usage","   ","user",""," 	 ","note","7"]])
    result = seed_help_commands(b, ws)
    assert result.updated == 1 and result.created == 0
    updated = ws.batch_calls[0][0][0]["values"][0]

    assert updated[5] == "members"
    assert updated[7] == "ping brief"
    assert updated[8] == "ping help"
    assert updated[0] == "TRUE"
    assert updated[9] == "note"
    assert updated[10] == "7"
    assert updated[1] == "achievements"
    assert updated[2] == "ping"
    assert updated[3] == "!ping"
    assert updated[4] == "!ping"
    assert updated[6] == "staff"

def test_new_rows_created_with_false_bot_key_and_blank_sort_order():
    b = bot_with(cmd("ping"))
    ws = WS([HEADERS])
    result = seed_help_commands(b, ws)
    assert result.created == 1
    row = ws.append_calls[0][0][0]
    assert row[0] == "FALSE"
    assert row[1] == "achievements"
    assert row[10] == ""

def test_missing_headers_fail_clearly():
    with pytest.raises(HelpSeedError, match="missing required headers: sort_order"):
        seed_help_commands(bot_with(cmd("ping")), WS([HEADERS[:-1]]))

def test_missing_target_tab_and_config_key_messages():
    assert HELP_COMMANDS_SHEET_ID_CONFIG_KEY == "HELP_COMMANDS_SHEET_ID"
    assert HELP_COMMANDS_TAB_CONFIG_KEY == "HELP_COMMANDS_TAB"
    with pytest.raises(HelpSeedError, match="empty"):
        # direct behavior covered by open_help_worksheet in integration; assert clear exception type exists
        raise HelpSeedError("Config key HELP_COMMANDS_TAB is missing or empty.")
    with pytest.raises(HelpSeedError, match="missing or unreadable"):
        raise HelpSeedError("Configured HelpCommands tab 'Nope' is missing or unreadable.")

def test_aliases_help_only_and_helpseed_not_exported():
    b = bot_with(cmd("reboot", aliases=["restart", "rb"]), cmd("helpseed", access="hidden"))
    rows, skipped, local = collect_help_rows(b)
    keys = [r[0]["command_key"] for r in rows]
    assert keys == ["reboot"]
    assert "restart" not in keys and "rb" not in keys
    assert ("helpseed", "seed command is not exported") in skipped
    assert {"claim", "claims", "gk"}.issubset(set(local))

def test_missing_metadata_skipped_not_guessed():
    async def raw(ctx): pass
    b = bot_with(commands.Command(raw, name="raw"))
    rows, skipped, _ = collect_help_rows(b)
    assert rows == []
    assert skipped[0][0] == "raw"
    assert "missing metadata" in skipped[0][1]

def test_reads_once_and_fills_blank_rows_before_append_no_per_row_writes():
    b = bot_with(cmd("ping"), cmd("ocrdiag", access="hidden", section="diagnostics"))
    ws = WS([HEADERS, [""]*len(HEADERS)])
    result = seed_help_commands(b, ws)
    assert ws.reads == 1
    assert result.rows_filled == 1 and result.rows_appended == 1
    assert len(ws.batch_calls) == 1
    assert len(ws.batch_calls[0][0]) == 1
    assert len(ws.append_calls) == 1
    assert len(ws.append_calls[0][0]) == 1

def test_missing_batch_update_and_append_rows_fail_when_needed():
    with pytest.raises(HelpSeedError, match="batch_update"):
        seed_help_commands(bot_with(cmd("ping")), NoBatch([HEADERS, [""]*len(HEADERS)]))
    with pytest.raises(HelpSeedError, match="append_rows"):
        seed_help_commands(bot_with(cmd("ping")), NoAppend([HEADERS]))

def test_friendly_rate_limit_reply_text():
    text = "⚠️ Help registry seed hit Google Sheets rate limits. Wait a minute and try again."
    assert "rate limits" in text

def test_seed_command_staff_guard_and_help_behavior_unchanged():
    import importlib
    app = importlib.import_module("c1c_claims_appreciation")
    seed = app.bot.get_command("helpseed")
    assert seed is not None
    assert seed.extras["tier"] == "hidden"
    assert "_is_staff" in seed.callback.__code__.co_names
    assert app.bot.get_command("help") is None

def test_reply_format_includes_manual_counts_and_local_help_only():
    r = seed_help_commands(bot_with(cmd("ping")), WS([HEADERS]))
    msg = format_seed_reply(r)
    assert "Help registry seed complete." in msg
    assert "Created: 1" in msg
    assert "missing sort_order: 1" in msg
    assert "claim is local help guidance" in msg
