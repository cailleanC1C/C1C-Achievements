import pytest
pytest.importorskip("discord")
import importlib

from achievements.help_metadata import VALID_ACCESS_TIERS

METADATA_KEYS = {"function_group", "help_section", "access_tier", "help_usage", "help_flags", "tier"}


def assert_metadata(command, access_tier=None):
    missing = [key for key in METADATA_KEYS if key not in command.extras]
    assert not missing, f"{command.qualified_name} missing metadata keys: {missing}"
    assert command.extras["access_tier"] in VALID_ACCESS_TIERS
    assert command.extras["tier"] in VALID_ACCESS_TIERS
    if access_tier:
        assert command.extras["access_tier"] == access_tier
        assert command.extras["tier"] == access_tier


def test_monolith_registered_commands_have_metadata_and_help_remains():
    app = importlib.import_module("c1c_claims_appreciation")
    names = {command.name for command in app.bot.commands}

    expected = {
        "help", "testconfig", "configstatus", "reloadconfig", "listach",
        "findach", "testach", "testlevel", "flushpraise", "ping",
    }
    assert expected.issubset(names)
    assert "helpseed" in names

    for command in app.bot.commands:
        if command.name in expected:
            assert_metadata(command)

    assert_metadata(app.bot.get_command("help"), "user")
    assert_metadata(app.bot.get_command("ping"), "user")
    assert app.bot.get_command("ping").extras["function_group"] == "operational"
    assert app.bot.get_command("ping").extras["help_section"] == "members"
    assert app.bot.get_command("help").extras["help_flags"] == ("local_help", "transitional")
    assert_metadata(app.bot.get_command("helpseed"), "hidden")
    assert app.bot.get_command("helpseed").extras["help_flags"] == ("hidden", "maintenance")


def test_admin_staff_monolith_commands_keep_runtime_staff_checks():
    app = importlib.import_module("c1c_claims_appreciation")
    staff_commands = ["testconfig", "configstatus", "reloadconfig", "listach", "findach", "testach", "testlevel", "flushpraise"]
    for name in staff_commands:
        cmd = app.bot.get_command(name)
        assert_metadata(cmd, "staff")
        names = set(cmd.callback.__code__.co_names)
        assert "_is_staff" in names


def test_cog_command_objects_have_metadata_aliases_and_hidden_diagnostics():
    ops = importlib.import_module("cogs.ops")
    shards = importlib.import_module("cogs.shards.cog")

    ops_commands = {
        "health": ops.OpsCog.health_cmd,
        "digest": ops.OpsCog.digest_cmd,
        "reload": ops.OpsCog.reload_cmd,
        "checksheet": ops.OpsCog.checksheet_cmd,
        "env": ops.OpsCog.env_cmd,
        "build": ops.OpsCog.build_cmd,
        "reboot": ops.OpsCog.reboot_cmd,
    }
    for command in ops_commands.values():
        assert_metadata(command, "staff")
    assert ops.OpsCog.reboot_cmd.aliases == ["restart", "rb"]

    assert_metadata(shards.ShardsCog.ocr_debug_cmd, "hidden")
    assert_metadata(shards.ShardsCog.ocr_diag_cmd, "hidden")
    assert_metadata(shards.ShardsCog.ocr_cmd, "staff")
    assert_metadata(shards.ShardsCog.shards_cmd, "user")
    assert_metadata(shards.ShardsCog.mercy_cmd, "user")


def test_help_only_topics_do_not_create_fake_commands():
    app = importlib.import_module("c1c_claims_appreciation")
    runnable = {command.name for command in app.bot.commands}

    assert "claim" not in runnable
    assert "claims" not in runnable
    assert "gk" not in runnable
    assert "helpseed" in runnable
