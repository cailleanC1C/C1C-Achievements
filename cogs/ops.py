# cogs/ops.py
# Registers CoreOps commands via a cog, delegating rendering to claims/ops.py.

import os, json, pathlib, hashlib, time, platform
import importlib, inspect
import discord
from discord.ext import commands
from achievements.help_metadata import help_metadata, tier
import logging

from core.prefix import SCOPED_PREFIXES, get_prefix

log = logging.getLogger("c1c-claims")

from claims.ops import (
    build_health_embed,
    build_digest_line,
    build_env_embed,
    build_checksheet_embed,
    build_reload_embed,
    build_rebooting_embed,
)

# ⬇️ NEW: prefix guidance helper
from claims.middleware.coreops_prefix import format_prefix_picker

# Access the running main module (the monolith) for data/functions.
app = importlib.import_module("__main__")

SCOPED_PREFIX_SET = {p.lower() for p in SCOPED_PREFIXES}


def _coreops_guard(ctx: commands.Context) -> tuple[bool, str]:
    """Return (allowed, msg) for admin-only CoreOps commands."""
    if app._is_admin(ctx.author):
        return True, ""
    return False, "Admin only."


class OpsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            log.info("OpsCog loaded: commands=%s", ", ".join(sorted(bot.all_commands.keys())))
        except Exception:
            pass

    # ---------------- core ops commands (admin-only) ----------------
    @help_metadata(function_group="operational", section="admin_maintenance", access_tier="admin", usage="!health", flags=('diagnostic',))
    @tier("admin")
    @commands.command(name="health")
    async def health_cmd(self, ctx: commands.Context):
        ok, msg = _coreops_guard(ctx)
        if not ok:
            return await ctx.send(msg)

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
                "status": app.CONFIG_META.get("status", "—"),
                "ready": app.CONFIG_READY.is_set(),
                "last_error": app.CONFIG_META.get("last_error"),
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

    @help_metadata(function_group="operational", section="admin_maintenance", access_tier="admin", usage="!digest", flags=('diagnostic',))
    @tier("admin")
    @commands.command(name="digest")
    async def digest_cmd(self, ctx: commands.Context):
        ok, msg = _coreops_guard(ctx)
        if not ok:
            return await ctx.send(msg)

        try:
            latency_ms = int(getattr(self.bot, "latency", 0.0) * 1000)
        except Exception:
            latency_ms = None
        last_age = app._last_event_age_s()

        # destinations + ok/— flags
        claims_txt = await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("public_claim_thread_id"))
        levels_txt = await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("levels_channel_id"))
        audit_txt = await app._fmt_chan_or_thread(ctx.guild, app.CFG.get("audit_log_channel_id"))
        gk_txt = app._fmt_role(ctx.guild, app.CFG.get("guardian_knights_role_id"))

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
                if app.CONFIG_META.get("loaded_at")
                else "—",
                "status": app.CONFIG_META.get("status", "—"),
                "ready": app.CONFIG_READY.is_set(),
                "last_error": app.CONFIG_META.get("last_error"),
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

    @help_metadata(function_group="operational", section="admin_maintenance", access_tier="admin", usage="!reload")
    @tier("admin")
    @commands.command(name="reload")
    async def reload_cmd(self, ctx: commands.Context):
        ok, msg = _coreops_guard(ctx)
        if not ok:
            return await ctx.send(msg)
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
            emb = build_reload_embed(app.BOT_VERSION, app.CONFIG_META["source"], loaded_at, counts)
            await app.safe_send_embed(ctx, emb)
        except Exception as e:
            await ctx.send(f"Reload failed: `{e}`")

    @help_metadata(function_group="operational", section="admin_maintenance", access_tier="admin", usage="!checksheet", flags=('diagnostic',))
    @tier("admin")
    @commands.command(name="checksheet")
    async def checksheet_cmd(self, ctx: commands.Context):
        ok, msg = _coreops_guard(ctx)
        if not ok:
            return await ctx.send(msg)

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
            {
                "name": "Achievements",
                "ok": len(app.ACHIEVEMENTS) > 0,
                "rows": len(app.ACHIEVEMENTS),
                "headers": headers_from_rows(app.ACHIEVEMENTS.values()),
            },
            {
                "name": "Categories",
                "ok": len(app.CATEGORIES) > 0,
                "rows": len(app.CATEGORIES),
                "headers": headers_from_rows(app.CATEGORIES),
            },
            {
                "name": "Levels",
                "ok": app.LEVELS is not None,
                "rows": len(app.LEVELS) if app.LEVELS is not None else 0,
                "headers": headers_from_rows(app.LEVELS),
            },
            {
                "name": "Reasons",
                "ok": len(app.REASONS) > 0,
                "rows": len(app.REASONS),
                "headers": ["code", "message"] if app.REASONS else [],
            },
        ]

        emb = build_checksheet_embed(app.BOT_VERSION, backend, items)
        await app.safe_send_embed(ctx, emb)

    @help_metadata(function_group="operational", section="admin_maintenance", access_tier="admin", usage="!env", flags=('diagnostic',))
    @tier("admin")
    @commands.command(name="env")
    async def env_cmd(self, ctx: commands.Context):
        ok, msg = _coreops_guard(ctx)
        if not ok:
            return await ctx.send(msg)

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

    @help_metadata(function_group="operational", section="admin_maintenance", access_tier="admin", usage="!build", flags=('diagnostic', 'hidden'))
    @tier("admin")
    @commands.command(name="build")
    async def build_cmd(self, ctx: commands.Context):
        ok, msg = _coreops_guard(ctx)
        if not ok:
            return await ctx.send(msg)

        def _hash_for(path: pathlib.Path) -> str:
            try:
                with path.open("rb") as handle:
                    return hashlib.md5(handle.read()).hexdigest()[:10]
            except Exception:
                return "missing"

        def _describe(label: str, path: pathlib.Path) -> str:
            if not path.exists():
                return f"- {label}: missing"
            digest = _hash_for(path)
            try:
                mtime = time.ctime(path.stat().st_mtime)
            except Exception:
                mtime = "?"
            return f"- {label}: `{digest}` @ {mtime}"

        root = pathlib.Path(__file__).resolve().parents[1]
        lr_path = root / "modules" / "achievements" / "locators" / "left_rail.py"
        ocr_pipeline_path = root / "modules" / "achievements" / "ocr_pipeline.py"
        icons_dir = root / "modules" / "achievements" / "assets" / "ocr" / "icons"
        git_sha = os.getenv("GIT_SHA", "unknown")

        lines = [
            "**Build**",
            f"- Python: {platform.python_version()}",
            f"- GIT_SHA: `{git_sha}`",
            _describe("left_rail.py", lr_path),
            _describe("ocr_pipeline.py", ocr_pipeline_path),
            f"- icons dir: `{icons_dir}` exists={icons_dir.exists()}",
        ]

        try:
            lr_mod = importlib.import_module("modules.achievements.locators.left_rail")
            has_corner = hasattr(lr_mod, "match_corners") and hasattr(lr_mod, "corners_to_number_rois")
            if has_corner:
                try:
                    src_line = inspect.getsourcelines(lr_mod.match_corners)[1]
                except Exception:
                    src_line = "?"
            else:
                src_line = "-"
            lines.append(f"- corner-match present: **{has_corner}** (def line {src_line})")
        except Exception as exc:
            lines.append(f"- import left_rail failed: {exc.__class__.__name__}: {exc}")

        await ctx.reply("\n".join(lines), mention_author=False)

    @help_metadata(function_group="operational", section="admin_maintenance", access_tier="admin", usage="!reboot")
    @tier("admin")
    @commands.command(name="reboot", aliases=["restart", "rb"])
    async def reboot_cmd(self, ctx: commands.Context):
        ok, msg = _coreops_guard(ctx)
        if not ok:
            return await ctx.send(msg)

        # react immediately so callers see liveness
        try:
            await ctx.message.add_reaction("🔁")
        except Exception:
            pass

        # show "Rebooting…" then perform a soft restart (reload config)
        ack = None
        try:
            emb = build_rebooting_embed(app.BOT_VERSION)
            ack = await app.safe_send_embed(ctx, emb)
        except Exception:
            # last-resort: plain text
            try:
                ack = await ctx.send("Rebooting…")
            except Exception:
                pass

        try:
            app.load_config()
            loaded_at = app.CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if app.CONFIG_META.get("loaded_at") else "—"
            counts = {
                "ach": len(app.ACHIEVEMENTS),
                "cat": len(app.CATEGORIES),
                "lvls": len(app.LEVELS),
                "reasons": len(app.REASONS),
            }
            done = build_reload_embed(app.BOT_VERSION, app.CONFIG_META.get("source", "—"), loaded_at, counts)

            if ack:
                try:
                    await ack.edit(content="🔄 Reloaded config. Ready.", embed=done)
                except Exception:
                    await app.safe_send_embed(ctx, done)
            else:
                await app.safe_send_embed(ctx, done)
        except Exception as e:
            await ctx.send(f"Reboot failed: `{e}`")


def _document_ops_command(command: commands.Command, brief: str, help_text: str) -> None:
    command.brief = brief
    command.help = help_text


_document_ops_command(OpsCog.health_cmd, "Shows Achievements runtime health.", "Admin diagnostic that replies with an embed summarizing bot uptime, gateway readiness, latency, last event age, config status, loaded row counts, and configured Discord targets. Use it to troubleshoot whether Achievements is connected and reading expected data.")
_document_ops_command(OpsCog.digest_cmd, "Posts a compact Achievements health digest.", "Admin diagnostic that replies with a one-line status digest covering runtime, gateway, config, row counts, and target availability. Use it when you need a concise operational snapshot without the full health embed.")
_document_ops_command(OpsCog.reload_cmd, "Reloads Achievements config and reports counts.", "Admin operation that reacts to the invoking message, reloads Achievements configuration from the configured source, and replies with an embed showing source, reload time, and loaded row counts. Use it after changing Achievements data or config.")
_document_ops_command(OpsCog.checksheet_cmd, "Checks loaded Achievements sheet sections.", "Admin diagnostic that replies with an embed showing the configured backend and row/header status for General, Achievements, Categories, Levels, and Reasons data. Use it to confirm required sheet sections are populated and readable.")
_document_ops_command(OpsCog.env_cmd, "Shows safe Achievements environment status.", "Admin diagnostic that replies with an embed showing whether key runtime environment variables are set, along with auto-refresh and watchdog settings. It avoids printing secret values and is useful for deployment troubleshooting.")
_document_ops_command(OpsCog.build_cmd, "Shows Achievements build/runtime fingerprint.", "Admin diagnostic that replies with Python version, configured git SHA, and selected local file fingerprints used for runtime troubleshooting. Use it to confirm which code build is running in the deployed Achievements process.")
_document_ops_command(OpsCog.reboot_cmd, "Performs a soft Achievements reboot.", "Admin operation that acknowledges with a rebooting message, reloads Achievements config, and edits or posts a ready embed with current source and row counts. Aliases !restart and !rb invoke the same soft reload behavior.")


async def setup(bot: commands.Bot):
    bot.command_prefix = get_prefix
    await bot.add_cog(OpsCog(bot))
