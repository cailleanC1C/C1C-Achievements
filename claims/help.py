# Help embed builders for C1C Appreciation & Claims

import os
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

def _prefixes_str() -> str:
    """Show available CoreOps prefixes (env COREOPS_PREFIXES or defaults)."""
    raw = os.getenv("COREOPS_PREFIXES", "sc,rem,wc,mm")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        parts = ["sc", "rem", "wc", "mm"]
    return ", ".join(parts)

def build_help_overview_embed(bot_version: str) -> discord.Embed:
    """Overview help page, updated for prefix policy."""
    e = discord.Embed(
        title="🏆 C1C Appreciation & Claims — Help",
        color=HELP_COLOR,
        description=(
            "Post your screenshot **in the public claims thread** to start a claim. "
            "I’ll prompt you to pick a category and achievement; some claims auto-grant, "
            "others summon **Guardian Knights** for review.\n\n"
            "**Admins** can run CoreOps with plain commands. **Everyone else** must use a **prefix**."
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
        name="CoreOps (admins: plain `!cmd`, others: use a prefix)",
        value=(
            f"Prefixes: `{_prefixes_str()}` — e.g., `!sc health`\n"
            "• `health` — runtime + config status (embed)\n"
            "• `digest` — short one-line status\n"
            "• `checksheet` — sheets/files sanity check (embed)\n"
            "• `reload` — reload config (embed)\n"
            "• `reboot` (`restart`, `rb`) — ‘reboot’ message then reload + edit (embed)\n"
            "• `env` — environment snapshot (embed)\n"
            "• `ping` — global react-only liveness check (no prefix needed)"
        ),
        inline=False,
    )
    e.add_field(
        name="Staff / testing tools",
        value=(
            "• `!testconfig` — show current config & sources\n"
            "• `!configstatus` — short config summary\n"
            "• `!reloadconfig` — reload Sheets/Excel config\n"
            "• `!listach [filter]` — list loaded achievements\n"
            "• `!findach <text>` — search achievements\n"
            "• `!testach <key> [where]` — preview an achievement embed\n"
            "• `!testlevel [query] [where]` — preview a level embed"
        ),
        inline=False,
    )
    e.add_field(
        name="GK notes",
        value="**Guardian Knights** can approve/deny or grant a different role during verification.",
        inline=False,
    )
    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e

def build_help_subtopic_embed(bot_version: str, topic: str) -> discord.Embed | None:
    """Subpage for !help <topic>. Returns None for unknown topics (caller stays silent)."""
    px = _prefixes_str().split(",")[0].strip() or "sc"  # sample prefix for examples

    pages = {
        # CoreOps
        "health":      f"`!health` (admin) or `!{px} health`\nShow runtime & config status in an embed.",
        "digest":      f"`!digest` (admin) or `!{px} digest`\nConcise one-liner status.",
        "checksheet":  f"`!checksheet` (admin) or `!{px} checksheet`\nSanity check of config sheets/files.",
        "reload":      f"`!reload` (admin) or `!{px} reload`\nReload configuration and report counts.",
        "reboot":      f"`!reboot` (admin) or `!{px} reboot`\nPost ‘Rebooting…’ then edit with reload result.",
        "restart":     f"Alias of **reboot**. Use `!reboot` / `!{px} reboot`.",
        "rb":          f"Alias of **reboot**. Use `!reboot` / `!{px} reboot`.",
        "env":         f"`!env` (admin) or `!{px} env`\nShow environment snapshot (safe subset).",
        "ping":        "`!ping` — Reacts with 🏓 to confirm liveness (global, no prefix needed).",

        # Staff/testing
        "testconfig":  "`!testconfig`\nShow current configuration: targets, role ids, source & row counts.",
        "configstatus":"`!configstatus`\nShort one-line status: source, loaded time, counts.",
        "reloadconfig":"`!reloadconfig`\nReload configuration from Google Sheets or Excel.",
        "listach":     "`!listach [filter]`\nList loaded achievement keys (optionally filtered).",
        "findach":     "`!findach <text>`\nSearch achievements by key/name/category/text.",
        "testach":     "`!testach <key> [where]`\nPreview a single achievement embed (optionally to another channel).",
        "testlevel":   "`!testlevel [query] [where]`\nPreview a level-up embed (optionally to another channel).",

        # Player-facing hints
        "claim":  "Post your screenshot **in the configured claims thread**. I’ll guide you via buttons.",
        "claims": "Same as `!help claim`.",
        "gk":     "Guardian Knights review claims that need verification. They can approve/deny or grant a different role.",
    }
    txt = pages.get(topic)
    if not txt:
        return None
    e = discord.Embed(title=f"!help {topic}", description=txt, color=HELP_COLOR)
    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e

async def setup(bot):
    # ensure we own !help
    try:
        bot.remove_command("help")
    except Exception:
        pass

    import os

    @bot.command(name="help")
    async def help_cmd(ctx, *, topic: str | None = None):
        ver = os.getenv("BOT_VERSION", "dev")
        topic_norm = (topic or "").strip().lower()
        if topic_norm:
            e = build_help_subtopic_embed(ver, topic_norm)
            if e:
                return await ctx.reply(embed=e, mention_author=False)
            return  # silent on unknown
        await ctx.reply(embed=build_help_overview_embed(ver), mention_author=False)
