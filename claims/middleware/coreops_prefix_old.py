# claims/middleware/coreops_prefix.py
# CoreOps prefix router & guidance for multi-bot setups.
#
# This cog adds:
#   • !sc <command> … → routes to THIS bot’s command (Scribe)
#   • A compact picker message you can show users when they run a bare command
#     and should choose a bot prefix instead.
#
# Notes:
# - We only register the `!sc` router here so only Scribe responds to it.
#   Other bots should register their own router (!rem / !wc / !mm).
# - Ping is intentionally global (react-only in your main), so we don’t route it.

from __future__ import annotations

import importlib
import logging
from typing import Optional

import discord
from discord.ext import commands

log = logging.getLogger("c1c-claims")

# Access the running main module (the monolith) for helpers like _is_staff()
app = importlib.import_module("__main__")


PREFIXES = [  # display order matters
    ("sc",  "Scribe"),
    ("rem", "Reminder"),
    ("wc",  "Welcome Crew"),
    ("mm",  "Matchmaker"),
]
OUR_PREFIX = "sc"

# Commands we’re happy to route via !sc …
ROUTABLE = {
    # CoreOps
    "health", "digest", "reload", "checksheet", "env", "reboot",
    # Help should be prefixed for non-admins; allow via router too
    "help",
    # (keep ping global; no need to route)
}

ALIASES = {
    # Map common aliases to canonical names
    "restart": "reboot",
    "rb": "reboot",
}

def _canon(name: str) -> str:
    return ALIASES.get(name.lower(), name.lower())


def format_prefix_picker(command_word: str) -> str:
    """Rendered guidance when someone used a bare command and should pick a bot."""
    bullets = "\n".join(
        f"• `!{pfx} {command_word}` — {label}" for pfx, label in PREFIXES
    )
    return f"For which bot do you want to run **{command_word}**?\n{bullets}"


class CoreOpsPrefixCog(commands.Cog):
    """Registers the `!sc` router command to scope CoreOps to Scribe."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        log.info("CoreOpsPrefixCog loaded (router=!%s)", OUR_PREFIX)

    # Example:
    #   !sc health
    #   !sc help
    #   !sc help claims
    @commands.command(name=OUR_PREFIX)
    async def route_to_scribe(self, ctx: commands.Context, *, rest: Optional[str] = None):
        if not rest:
            # minimal usage hint
            pretty = ", ".join(sorted(f"`!{OUR_PREFIX} {c}`" for c in sorted(ROUTABLE)))
            return await ctx.reply(f"Try {pretty}", mention_author=False)

        parts = rest.strip().split(maxsplit=1)
        sub = _canon(parts[0])
        arg_tail = parts[1] if len(parts) > 1 else ""

        if sub not in ROUTABLE:
            return await ctx.reply(f"Unknown or unroutable: `{sub}`", mention_author=False)

        cmd = self.bot.get_command(sub)
        if not cmd:
            return await ctx.reply(f"Command not available on this bot: `{sub}`", mention_author=False)

        # Mark the context so any global gate can allow routed calls.
        setattr(ctx, "_coreops_via_router", True)

        # Dispatch with best-effort arg handling
        try:
            if sub == "help":
                # help(ctx, *, topic: str | None)
                await ctx.invoke(cmd, topic=(arg_tail or None))
            else:
                # CoreOps commands we route here do not take extra args
                await ctx.invoke(cmd)
        except commands.CommandError as e:
            # Let your global on_command_error print a friendly message,
            # but log for debugging.
            log.exception("Routed command failed: !%s %s (%r)", OUR_PREFIX, sub, e)

class CoreOpsPrefixCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    # … router code already present …

async def setup(bot: commands.Bot):
    await bot.add_cog(CoreOpsPrefixCog(bot))
