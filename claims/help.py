# claims/help.py
# Help embed builders for C1C Appreciation & Claims

import discord
from datetime import datetime

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

HELP_COLOR = discord.Color.blurple()


def _vienna_now_str() -> str:
    """Return 'YYYY-MM-DD HH:MM Europe/Vienna' (fallback to UTC on any issue)."""
    try:
        if ZoneInfo is not None:
            tz = ZoneInfo("Europe/Vienna")
            return datetime.now(tz).strftime("%Y-%m-%d %H:%M Europe/Vienna")
    except Exception:
        pass
    # Fallback (should rarely happen)
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def build_help_overview_embed(bot_version: str) -> discord.Embed:
    """Overview help page – reflects current live commands."""
    e = discord.Embed(
        title="🏆 C1C Appreciation & Claims — Help",
        color=HELP_COLOR,
        description=(
            "Post your screenshot **in the public claims thread** to start a claim. "
            "I’ll prompt you to pick a category and achievement; some claims auto-grant, "
            "others summon **Guardian Knights** for review.\n\n"
            "**Staff** can use the ops & testing commands below."
        ),
    )

    e.add_field(
        name="How to claim (players)",
        value=(
            "1) Post a screenshot in the configured claims thread.\n"
            "2) Use the buttons to choose category ➜ achievement.\n"
            "3) If review is needed, GK will approve/deny or grant a different role."
        ),
        inline=False,
    )

    e.add_field(
        name="Ops (staff only)",
        value=(
            "• `!health` — detailed health & config snapshot (embed)\n"
            "• `!digest` — one-line heartbeat for quick/scheduled checks\n"
            "• `!env` — effective environment config (masked where needed)\n"
            "• `!checksheet` — sheet tabs status, row counts, headers\n"
            "• `!reload` — reload configuration (🔁 reacts, styled result)\n"
            "• `!reboot` — soft reboot: show *Rebooting…*, then edited reload result"
        ),
        inline=False,
    )

    e.add_field(
        name="Testing (staff only)",
        value=(
            "• `!listach [filter]` — list loaded achievements\n"
            "• `!findach <text>` — search achievements\n"
            "• `!testach <key> [where]` — preview an achievement embed\n"
            "• `!testlevel [query] [where]` — preview a level embed"
        ),
        inline=False,
    )

    e.add_field(
        name="Utilities",
        value="• `!ping` — liveness check (reacts with 🏓)",
        inline=False,
    )

    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e


def build_help_subtopic_embed(bot_version: str, topic: str) -> discord.Embed | None:
    """Subpage for !help <topic>. Returns None for unknown topics (caller stays silent)."""
    pages = {
        # ops
        "health":   "`!health`\nEmbed with runtime (uptime, latency, last event age), gateway, config source/loaded time, target channels/roles, and row counts.",
        "digest":   "`!digest`\nOne-line heartbeat: uptime, latency, last event age, counts, and OK/— flags for channels/roles.",
        "env":      "`!env`\nShow relevant environment variables used by the bot (safely summarized).",
        "checksheet": "`!checksheet`\nSummarize tabs loaded from the sheet (General, Achievements, Categories, Levels, Reasons) with row counts and visible headers.",
        "reload":   "`!reload`\nReload configuration from Google Sheets or Excel. Adds a 🔁 reaction and returns a styled result embed.",
        "reboot":   "`!reboot`\nSoft reboot UX: reacts 🔁, posts *Rebooting…*, then edits with the reload result embed.",
        # testing
        "listach":  "`!listach [filter]`\nList loaded achievement keys (optionally filter by substring).",
        "findach":  "`!findach <text>`\nSearch achievements by key/name/category/text.",
        "testach":  "`!testach <key> [where]`\nPreview a single achievement embed (optionally to another channel).",
        "testlevel":"`!testlevel [query] [where]`\nPreview a level-up embed (optionally to another channel).",
        # utilities
        "ping":     "`!ping`\nSimple liveness check — reacts to your message with 🏓.",
        # player-facing aliases
        "claim":    "Post your screenshot **in the configured claims thread**. I’ll guide you via buttons.",
        "claims":   "Same as `!help claim`.",
        "gk":       "Guardian Knights review claims that need verification. They can approve/deny or grant a different role.",
    }
    txt = pages.get(topic)
    if not txt:
        return None
    e = discord.Embed(title=f"!help {topic}", description=txt, color=HELP_COLOR)
    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e
