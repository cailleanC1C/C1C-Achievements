"""Passive Woadkeeper-compatible command help metadata helpers.

This metadata is for future shared HelpCommands export and Woadkeeper-owned
help rendering. It is intentionally passive and does not drive Achievements'
current local help output yet.

Supported decorator order keeps ``@commands.command(...)`` directly below the
metadata decorators so Python applies it first::

    @help_metadata(...)
    @tier("user")
    @commands.command(...)
    async def command(...):
        ...
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar

from discord.ext import commands

VALID_TIERS = frozenset({"user", "staff", "admin", "hidden"})
VALID_ACCESS_TIERS = frozenset({"user", "staff", "admin", "hidden"})

T = TypeVar("T", bound=commands.Command)


def _require_command(obj: Any, decorator_name: str) -> commands.Command:
    if not isinstance(obj, commands.Command):
        raise TypeError(
            f"@{decorator_name} must be applied above @commands.command "
            "so it receives a discord.py Command object."
        )
    return obj


def _validate(value: str, valid: frozenset[str], label: str) -> str:
    if value not in valid:
        allowed = ", ".join(sorted(valid))
        raise ValueError(f"Invalid {label} {value!r}; expected one of: {allowed}")
    return value


def _normalize_flags(flags: Iterable[str] | None) -> tuple[str, ...]:
    if flags is None:
        return ()
    normalized = tuple(str(flag) for flag in flags)
    if any(not flag for flag in normalized):
        raise ValueError("help metadata flags must be non-empty strings")
    return normalized


def tier(value: str):
    """Mark a discord.py command with an RBAC/help tier."""
    checked = _validate(value, VALID_TIERS, "tier")

    def decorator(command: T) -> T:
        checked_command = _require_command(command, "tier")
        checked_command.extras["tier"] = checked
        setattr(checked_command, "_tier", checked)
        return command

    return decorator


def help_metadata(
    *,
    function_group: str,
    section: str,
    access_tier: str,
    usage: str | None = None,
    flags: Iterable[str] | None = None,
):
    """Attach passive shared-help metadata to a discord.py command."""
    checked_access = _validate(access_tier, VALID_ACCESS_TIERS, "access_tier")
    normalized_flags = _normalize_flags(flags)

    def decorator(command: T) -> T:
        checked_command = _require_command(command, "help_metadata")
        checked_command.extras["function_group"] = function_group
        checked_command.extras["help_section"] = section
        checked_command.extras["access_tier"] = checked_access
        checked_command.extras["help_usage"] = usage
        checked_command.extras["help_flags"] = normalized_flags
        return command

    return decorator


def get_help_metadata(command: commands.Command) -> dict[str, Any]:
    """Return only the helper-owned shared-help metadata fields."""
    checked_command = _require_command(command, "get_help_metadata")
    extras = checked_command.extras
    return {
        key: extras.get(key)
        for key in ("function_group", "help_section", "access_tier", "help_usage", "help_flags")
    }
