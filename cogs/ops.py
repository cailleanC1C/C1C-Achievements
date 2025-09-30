# cogs/ops.py
# Registers CoreOps commands via a cog, delegating rendering to claims/ops.py.

import os, json
import importlib
import discord
from discord.ext import commands

from claims.ops import (
    build_health_embed,
    build_digest_line,
    build_env_embed,
    build_checksheet_embed,
    build_reload_embed,
    build_rebooting_embed,
)

# Access the running main module (the monolith) for data/functions.
app = importlib.import_module("__main__")

class OpsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- core ops commands (staff-only) ----------------
    @commands.command(name="health")
    async def health_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")

        try:
            latency_ms = int(getattr(self.bot, "latency", 0.0) * 1000)
        except Exception:
            latency_ms = None
        last_age = app._last_event_age_s()

        summary = {
            "runtime": {
                "uptime": app.uptime_str(),
                "ready": getattr(self.bot, "is_ready", lambda: False)(),
                "latency_ms": latency_ms,
                "last_event_age_s": last_age,
            },
            "gateway": {"connected": app.BOT_CONNECTED},
            "config": {
                "source": app.CONFIG_META.get("source") or "—",
                "loaded_at": app.CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M UTC")
                if app.CONFIG_META.get("loaded_at")
                else "—",
            },
            "counts": {
                "ach": len(app.ACHIEVEMENTS),
                "cat": len(app.CATEGORIES),
                "lvls": len(app.LEVELS),
                "reasons": len(app.REASONS),
            },
            "targets": {
                "claims": await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("public_claim_thread_id")),
                "levels": await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("levels_channel_id")),
                "audit": await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("audit_log_channel_id")),
                "gk_role": app._fmt_role(ctx.guild, app.CFG.get("guardian_knights_role_id")),
            },
            "settings": {
                "auto_refresh": int(os.getenv("CONFIG_AUTO_REFRESH_MINUTES", "0") or "0"),
                "strict_probe": app.STRICT_PROBE,
                "watchdog_check": app.WATCHDOG_CHECK_SEC,
                "watchdog_max_disc": app.WATCHDOG_MAX_DISCONNECT_SEC,
            },
        }
        emb = build_health_embed(app.BOT_VERSION, summary)
        await app.safe_send_embed(ctx, emb)

    @commands.command(name="digest")
    async def digest_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")

        try:
            latency_ms = int(getattr(self.bot, "latency", 0.0) * 1000)
        except Exception:
            latency_ms = None
        last_age = app._last_event_age_s()

        # destinations + ok/— flags
        claims_txt = await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("public_claim_thread_id"))
        levels_txt = await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("levels_channel_id"))
        audit_txt  = await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("audit_log_channel_id"))
        gk_txt     = app._fmt_role(ctx.guild, app.CFG.get("guardian_knights_role_id"))
        def _ok(s: str) -> str:
            s = str(s or "")
            return "ok" if (s and "unknown" not in s and s != "—") else "—"

        summary = {
            "runtime": {
                "uptime": app.uptime_str(),
                "ready": getattr(self.bot, "is_ready", lambda: False)(),
                "latency_ms": latency_ms,
                "last_event_age_s": last_age,
            },
            "gateway": {"connected": app.BOT_CONNECTED},
            "config": {
                "source": app.CONFIG_META.get("source") or "—",
                "loaded_at": app.CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M UTC")
                if app.CONFIG_META.get("loaded_at") else "—",
            },
            "counts": {
                "ach": len(app.ACHIEVEMENTS),
                "cat": len(app.CATEGORIES),
                "lvls": len(app.LEVELS),
                "reasons": len(app.REASONS),
            },
            "flags": {
                "claims": _ok(claims_txt),
                "levels": _ok(levels_txt),
                "audit": _ok(audit_txt),
                "gk_role": _ok(gk_txt),
            },
        }
        line = build_digest_line(summary)
        await ctx.send(line)

    @commands.command(name="reload")
    async def reload_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")
        try:
            try:
                await ctx.message.add_reaction("🔁")
            except Exception:
                pass

            app.load_config()
            loaded_at = app.CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
            counts = {
                "ach": len(app.ACHIEVEMENTS),
                "cat": len(app.CATEGORIES),
                "lvls": len(app.LEVELS),
                "reasons": len(app.REASONS),
            }
            emb = build_reload_embed(app.BOT_VERSION, app.CONFIG_META['source'], loaded_at, counts)
            await app.safe_send_embed(ctx, emb)
        except Exception as e:
            await ctx.send(f"Reload failed: `{e}`")

    @commands.command(name="checksheet")
    async def checksheet_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")
        backend = app.CONFIG_META.get("source") or "—"

        def headers_from_rows(rows):
            if not rows:
                return []
            keys = set()
            for r in rows:
                try:
                    keys.update(list(r.keys()))
                except Exception:
                    pass
            return sorted(keys)

        items = [
            {"name": "General", "ok": True, "rows": 1, "headers": []},
            {"name": "Achievements", "ok": len(app.ACHIEVEMENTS) > 0,
             "rows": len(app.ACHIEVEMENTS), "headers": headers_from_rows(app.ACHIEVEMENTS.values())},
            {"name": "Categories", "ok": len(app.CATEGORIES) > 0,
             "rows": len(app.CATEGORIES), "headers": headers_from_rows(app.CATEGORIES)},
            {"name": "Levels", "ok": app.LEVELS is not None,
             "rows": len(app.LEVELS) if app.LEVELS is not None else 0, "headers": headers_from_rows(app.LEVELS)},
            {"name": "Reasons", "ok": len(app.REASONS) > 0,
             "rows": len(app.REASONS), "headers": ["code", "message"] if app.REASONS else []},
        ]

        emb = build_checksheet_embed(app.BOT_VERSION, backend, items)
        await app.safe_send_embed(ctx, emb)

@commands.command(name="reboot")
async def reboot_cmd(self, ctx: commands.Context):
    if not app._is_staff(ctx.author):
        return await ctx.send("Staff only.")

    # react immediately so callers see liveness
    try:
        await ctx.message.add_reaction("🔁")
    except Exception:
        pass

    # show "Rebooting…" then perform a soft restart (reload config)
    emb = build_rebooting_embed(app.BOT_VERSION)
    ack = await app.safe_send_embed(ctx, emb)

    try:
        app.load_config()
        loaded_at = app.CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if app.CONFIG_META.get("loaded_at") else "—"
        counts = {
            "ach": len(app.ACHIEVEMENTS),
            "cat": len(app.CATEGORIES),
            "lvls": len(app.LEVELS),
            "reasons": len(app.REASONS),
        }
        done = build_reload_embed(app.BOT_VERSION, app.CONFIG_META.get("source","—"), loaded_at, counts)
        # edit the previous message to a success state (Reminder-style)
        try:
            await ack.edit(content="🔄 Reloaded config. Ready.", embed=done)
        except Exception:
            # if edit fails, just post a fresh message
            await app.safe_send_embed(ctx, done)
    except Exception as e:
        await ctx.send(f"Reboot failed: `{e}`")

