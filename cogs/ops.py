# cogs/ops.py
# Registers CoreOps commands via a cog, delegating rendering to claims/ops.py.

import os
import importlib
import discord
from discord.ext import commands

from claims.ops import (
    build_health_embed,
    build_digest_embed,
    build_config_embed,
    build_env_embed,
    build_checksheet_embed,
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
        legacy = []
        if "testconfig" in app.bot.all_commands:
            legacy.append("testconfig")
        if "configstatus" in app.bot.all_commands:
            legacy.append("configstatus")
        if "reloadconfig" in app.bot.all_commands:
            legacy.append("reloadconfig")
        emb = build_digest_embed(app.BOT_VERSION, summary, legacy)
        await app.safe_send_embed(ctx, emb)

    @commands.command(name="reload")
    async def reload_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")
        try:
            app.load_config()
            loaded_at = app.CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
            await ctx.send(
                f"🔁 Reloaded from **{app.CONFIG_META['source']}** at **{loaded_at}**. "
                f"Ach={len(app.ACHIEVEMENTS)} Cat={len(app.CATEGORIES)} Lvls={len(app.LEVELS)}"
            )
        except Exception as e:
            await ctx.send(f"Reload failed: `{e}`")

    @commands.command(name="checksheet")
    async def checksheet_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")
        backend = app.CONFIG_META.get("source") or "—"
        tabs = [
            ("General", True, "loaded"),
            ("Achievements", len(app.ACHIEVEMENTS) > 0, f"{len(app.ACHIEVEMENTS)} rows"),
            ("Categories", len(app.CATEGORIES) > 0, f"{len(app.CATEGORIES)} rows"),
            ("Levels", True if app.LEVELS is not None else False, f"{len(app.LEVELS)} rows" if app.LEVELS is not None else "missing"),
            ("Reasons", len(app.REASONS) > 0, f"{len(app.REASONS)} rows"),
        ]
        status = {"backend": backend, "tabs": tabs}
        emb = build_checksheet_embed(app.BOT_VERSION, status)
        await app.safe_send_embed(ctx, emb)

    @commands.command(name="env")
    async def env_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")
        local = os.getenv("LOCAL_CONFIG_XLSX", "").strip()
        env_info = {
            "CONFIG_SHEET_ID": "set" if os.getenv("CONFIG_SHEET_ID") else "not set",
            "SERVICE_ACCOUNT_JSON": "set" if os.getenv("SERVICE_ACCOUNT_JSON") else "not set",
            "LOCAL_CONFIG_XLSX": (os.path.basename(local) if local else "not set"),
            "CONFIG_AUTO_REFRESH_MINUTES": os.getenv("CONFIG_AUTO_REFRESH_MINUTES", "0"),
            "STRICT_PROBE": "1" if app.STRICT_PROBE else "0",
            "WATCHDOG_CHECK_SEC": str(app.WATCHDOG_CHECK_SEC),
            "WATCHDOG_MAX_DISCONNECT_SEC": str(app.WATCHDOG_MAX_DISCONNECT_SEC),
        }
        emb = build_env_embed(app.BOT_VERSION, env_info)
        await app.safe_send_embed(ctx, emb)

    @commands.command(name="config")
    async def config_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")
        loaded_at = app.CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if app.CONFIG_META.get("loaded_at") else "—"
        snap = {
            "source": app.CONFIG_META.get("source") or "—",
            "loaded_at": loaded_at,
            "claims": await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("public_claim_thread_id")),
            "levels": await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("levels_channel_id")),
            "audit": await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("audit_log_channel_id")),
            "gk_role": app._fmt_role(ctx.guild, app.CFG.get("guardian_knights_role_id")),
            "counts": {"ach": len(app.ACHIEVEMENTS), "cat": len(app.CATEGORIES), "lvls": len(app.LEVELS)},
        }
        emb = build_config_embed(app.BOT_VERSION, snap)
        await app.safe_send_embed(ctx, emb)

    @commands.command(name="reboot")
    async def reboot_cmd(self, ctx: commands.Context):
        if not app._is_staff(ctx.author):
            return await ctx.send("Staff only.")
        await ctx.send("♻️ Rebooting…")
        await app._maybe_restart("manual reboot")
