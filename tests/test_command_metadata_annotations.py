import pytest
pytest.importorskip("discord")
import importlib

from achievements.help_metadata import VALID_ACCESS_TIERS
from achievements.help_seed import collect_help_rows

METADATA_KEYS = {"function_group", "help_section", "access_tier", "help_usage", "help_flags", "tier"}
REMOVED_COMMANDS = {"help", "ocr", "ocrdebug", "ocrdiag", "mercy", "shards"}
ADMIN_COMMANDS = {
    "build", "checksheet", "configstatus", "digest", "env", "findach",
    "flushpraise", "health", "listach", "reboot", "reload", "reloadconfig",
    "testach", "testconfig", "testlevel",
}
MONOLITH_ADMIN_COMMANDS = {
    "configstatus", "findach", "flushpraise", "listach", "reloadconfig",
    "testach", "testconfig", "testlevel",
}
OPS_COMMANDS = {
    "health": "health_cmd",
    "digest": "digest_cmd",
    "reload": "reload_cmd",
    "checksheet": "checksheet_cmd",
    "env": "env_cmd",
    "build": "build_cmd",
    "reboot": "reboot_cmd",
}


def assert_metadata(command, access_tier=None):
    missing = [key for key in METADATA_KEYS if key not in command.extras]
    assert not missing, f"{command.qualified_name} missing metadata keys: {missing}"
    assert command.extras["access_tier"] in VALID_ACCESS_TIERS
    assert command.extras["tier"] in VALID_ACCESS_TIERS
    if access_tier:
        assert command.extras["access_tier"] == access_tier
        assert command.extras["tier"] == access_tier


def test_monolith_removed_commands_are_not_registered_and_remaining_commands_have_metadata():
    app = importlib.import_module("c1c_claims_appreciation")
    names = {command.name for command in app.bot.commands}
    walked = {command.name for command in app.bot.walk_commands()}

    assert not (REMOVED_COMMANDS & names)
    assert not (REMOVED_COMMANDS & walked)

    expected = MONOLITH_ADMIN_COMMANDS | {"ping", "helpseed"}
    assert expected.issubset(names)

    for name in MONOLITH_ADMIN_COMMANDS:
        command = app.bot.get_command(name)
        assert_metadata(command, "admin")
        assert command.extras["help_usage"]
        assert command.brief
        assert command.help
        assert command.help != command.brief

    assert_metadata(app.bot.get_command("ping"), "staff")
    assert app.bot.get_command("ping").extras["function_group"] == "operational"
    assert app.bot.get_command("ping").extras["help_section"] == "members"
    assert app.bot.get_command("ping").extras["help_usage"] == "!ping"
    assert app.bot.get_command("ping").brief
    assert app.bot.get_command("ping").help
    assert_metadata(app.bot.get_command("helpseed"), "hidden")
    assert app.bot.get_command("helpseed").extras["help_flags"] == ("hidden", "maintenance")
    assert app.bot.get_command("helpseed").help


def test_admin_staff_monolith_commands_keep_runtime_admin_checks_and_ping_staff_check():
    app = importlib.import_module("c1c_claims_appreciation")
    for name in MONOLITH_ADMIN_COMMANDS:
        cmd = app.bot.get_command(name)
        assert_metadata(cmd, "admin")
        names = set(cmd.callback.__code__.co_names)
        assert "_is_admin" in names
        assert "_is_staff" not in names

    ping = app.bot.get_command("ping")
    assert_metadata(ping, "staff")
    assert "_is_staff" in set(ping.callback.__code__.co_names)


def test_cog_command_objects_have_admin_metadata_aliases_and_descriptions():
    ops = importlib.import_module("cogs.ops")
    for attr in OPS_COMMANDS.values():
        command = getattr(ops.OpsCog, attr)
        assert_metadata(command, "admin")
        assert command.extras["help_usage"]
        assert command.brief
        assert command.help
        assert command.help != command.brief
    assert ops.OpsCog.reboot_cmd.aliases == ["restart", "rb"]


def test_helpseed_export_skips_removed_commands_and_itself():
    app = importlib.import_module("c1c_claims_appreciation")
    rows, skipped, _ = collect_help_rows(app.bot)
    exported = {row["command_key"] for row, _manual in rows}
    skipped_keys = {key for key, _reason in skipped}

    assert not (REMOVED_COMMANDS & exported)
    assert "helpseed" not in exported
    assert "helpseed" in skipped_keys
    assert "ping" in exported
    for name in MONOLITH_ADMIN_COMMANDS:
        assert name in exported


def test_help_only_topics_do_not_create_fake_commands():
    app = importlib.import_module("c1c_claims_appreciation")
    runnable = {command.name for command in app.bot.commands}

    assert "claim" not in runnable
    assert "claims" not in runnable
    assert "gk" not in runnable
    assert "helpseed" in runnable

class _Perms:
    def __init__(self, *, administrator=False, manage_guild=False):
        self.administrator = administrator
        self.manage_guild = manage_guild


class _Role:
    def __init__(self, role_id):
        self.id = role_id


class _Member:
    def __init__(self, *, administrator=False, manage_guild=False, roles=()):
        self.guild_permissions = _Perms(administrator=administrator, manage_guild=manage_guild)
        self.roles = list(roles)


def test_runtime_permission_helpers_distinguish_admin_staff_and_normal_users():
    app = importlib.import_module("c1c_claims_appreciation")
    app.CFG["guardian_knights_role_id"] = 42

    normal = _Member()
    staff = _Member(roles=[_Role(42)])
    admin = _Member(administrator=True)
    manager = _Member(manage_guild=True)

    assert not app._is_admin(normal)
    assert not app._is_staff(normal)
    assert not app._is_admin(staff)
    assert app._is_staff(staff)
    assert app._is_admin(admin)
    assert app._is_staff(admin)
    assert app._is_admin(manager)
    assert app._is_staff(manager)
