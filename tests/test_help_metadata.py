import pytest
pytest.importorskip("discord")
from discord.ext import commands

from achievements.help_metadata import (
    VALID_ACCESS_TIERS,
    VALID_TIERS,
    get_help_metadata,
    help_metadata,
    tier,
)


def make_command():
    async def callback(ctx):
        return None

    return commands.Command(callback, name="sample", extras={"kept": "value"})


@pytest.mark.parametrize("tier_name", sorted(VALID_TIERS))
def test_tier_stores_extras_and_private_tier(tier_name):
    cmd = tier(tier_name)(make_command())

    assert cmd.extras["tier"] == tier_name
    assert cmd._tier == tier_name
    assert cmd.extras["kept"] == "value"


def test_invalid_tier_raises_clearly():
    with pytest.raises(ValueError, match="Invalid tier"):
        tier("moderator")


def test_help_metadata_stores_expected_fields_and_preserves_extras():
    cmd = help_metadata(
        function_group="achievements",
        section="progress",
        access_tier="user",
        usage="!sample [arg]",
        flags=["diagnostic", "hidden"],
    )(make_command())

    assert cmd.extras["kept"] == "value"
    assert get_help_metadata(cmd) == {
        "function_group": "achievements",
        "help_section": "progress",
        "access_tier": "user",
        "help_usage": "!sample [arg]",
        "help_flags": ("diagnostic", "hidden"),
    }


def test_invalid_access_tier_raises_clearly():
    with pytest.raises(ValueError, match="Invalid access_tier"):
        help_metadata(function_group="x", section="y", access_tier="moderator")


def test_flags_normalize_to_stable_tuple_of_strings():
    cmd = help_metadata(function_group="x", section="y", access_tier="hidden", flags=["b", 7])(make_command())
    assert cmd.extras["help_flags"] == ("b", "7")


def test_tier_rejects_raw_function_with_clear_message():
    async def raw(ctx):
        return None

    with pytest.raises(TypeError, match="@tier must be applied above @commands.command"):
        tier("user")(raw)


def test_help_metadata_rejects_raw_function_with_clear_message():
    async def raw(ctx):
        return None

    decorator = help_metadata(function_group="x", section="y", access_tier="user")
    with pytest.raises(TypeError, match="@help_metadata must be applied above @commands.command"):
        decorator(raw)


def test_decorator_order_used_in_repo_with_command_then_permission_decorator():
    @help_metadata(function_group="diagnostics", section="diagnostics", access_tier="hidden", usage="!ordered")
    @tier("hidden")
    @commands.guild_only()
    @commands.command(name="ordered")
    async def ordered(ctx):
        return None

    assert ordered.extras["tier"] == "hidden"
    assert ordered.extras["access_tier"] == "hidden"
    assert ordered.extras["help_usage"] == "!ordered"
    assert ordered.checks  # guild_only check is preserved
