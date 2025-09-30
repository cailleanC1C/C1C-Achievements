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
    """Overview help page (same content as before; new standardized footer)."""
    e = discord.Embed(
        title="🏆 C1C Appreciation & Claims — Help",
        color=HELP_COLOR,
        description=(
            "Post your screenshot **in the public claims thread** to start a claim. "
            "I’ll prompt you to pick a category and achievement; some claims auto-grant, "
            "others summon **Guardian Knights** for review.\n\n"
            "**Staff** can use the commands below for config and testing."
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
        name="Staff commands",
        value=(
            "• `!testconfig` — show current config & sources\n"
            "• `!configstatus` — short config summary\n"
            "• `!reloadconfig` — reload Sheets/Excel config\n"
            "• `!listach [filter]` — list loaded achievements\n"
            "• `!findach <text>` — search achievements\n"
            "• `!testach <key> [where]` — preview an achievement embed\n"
            "• `!testlevel [query] [where]` — preview a level embed\n"
            "• `!ping` — bot alive check"
        ),
        inline=False,
    )
    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e


def build_help_subtopic_embed(bot_version: str, topic: str) -> discord.Embed | None:
    """Subpage for !help <topic>. Returns None for unknown topics (caller stays silent)."""
    pages = {
        "testconfig":     "`!testconfig`\nShow current configuration: targets, role ids, source & row counts.",
        "configstatus":   "`!configstatus`\nShort one-line status: source, loaded time, counts.",
        "reloadconfig":   "`!reloadconfig`\nReload configuration from Google Sheets or Excel.",
        "listach":        "`!listach [filter]`\nList loaded achievement keys (optionally filtered).",
        "findach":        "`!findach <text>`\nSearch achievements by key/name/category/text.",
        "testach":        "`!testach <key> [where]`\nPreview a single achievement embed (optionally to another channel).",
        "testlevel":      "`!testlevel [query] [where]`\nPreview a level-up embed (optionally to another channel).",
        "ping":           "`!ping`\nSimple liveness check.",
        # player-facing hints (aliases)
        "claim":          "Post your screenshot **in the configured claims thread**. I’ll guide you via buttons.",
        "claims":         "Same as `!help claim`.",
        "gk":             "Guardian Knights review claims that need verification. They can approve/deny or grant a different role.",
    }
    txt = pages.get(topic)
    if not txt:
        return None
    e = discord.Embed(title=f"!help {topic}", description=txt, color=HELP_COLOR)
    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e
