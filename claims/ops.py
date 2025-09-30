# claims/ops.py
# Core Ops embed builders for C1C Appreciation & Claims (Health/Digest/Config/Env/Checksheet)

import os
import discord
from datetime import datetime

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None


def _vienna_now_str() -> str:
    """Return 'YYYY-MM-DD HH:MM Europe/Vienna' (fallback to UTC)."""
    try:
        if ZoneInfo is not None:
            tz = ZoneInfo("Europe/Vienna")
            return datetime.now(tz).strftime("%Y-%m-%d %H:%M Europe/Vienna")
    except Exception:
        pass
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def build_health_embed(bot_version: str, summary: dict) -> discord.Embed:
    # summary keys:
    #   runtime: {uptime, ready, latency_ms, last_event_age_s}
    #   gateway: {connected}
    #   config:  {source, loaded_at}
    #   counts:  {ach, cat, lvls, reasons}
    #   targets: {claims, levels, audit, gk_role}
    #   settings:{auto_refresh, strict_probe, watchdog_check, watchdog_max_disc}
    e = discord.Embed(title="🏆 Appreciation & Claims — Health", color=discord.Color.blurple())

    rt = summary.get("runtime", {})
    gw = summary.get("gateway", {})
    cfg = summary.get("config", {})
    cnt = summary.get("counts", {})
    tgt = summary.get("targets", {})
    stg = summary.get("settings", {})

    runtime_lines = [
        f"Uptime: **{rt.get('uptime', '—')}**",
        f"Ready: **{rt.get('ready', False)}**",
        (f"Latency: **{rt.get('latency_ms', '—')} ms**" if rt.get("latency_ms") is not None else "Latency: **—**"),
        (f"Last event age: **{rt.get('last_event_age_s', '—')} s**" if rt.get("last_event_age_s") is not None else "Last event age: **—**"),
        f"Connected: **{gw.get('connected', False)}**",
    ]
    e.add_field(name="Runtime", value="\n".join(runtime_lines), inline=False)

    config_lines = [
        f"Source: **{cfg.get('source', '—')}**",
        f"Loaded at: **{cfg.get('loaded_at', '—')}**",
        f"Achievements: **{cnt.get('ach', 0)}** • Categories: **{cnt.get('cat', 0)}** • Levels: **{cnt.get('lvls', 0)}** • Reasons: **{cnt.get('reasons', 0)}**",
    ]
    e.add_field(name="Config", value="\n".join(config_lines), inline=False)

    targets_lines = [
        f"Claims thread: {tgt.get('claims', '—')}",
        f"Levels channel: {tgt.get('levels', '—')}",
        f"Audit-log channel: {tgt.get('audit', '—')}",
        f"Guardian Knights role: {tgt.get('gk_role', '—')}",
    ]
    e.add_field(name="Destinations", value="\n".join(targets_lines), inline=False)

    settings_lines = [
        f"Auto-refresh (min): **{stg.get('auto_refresh', 0)}**",
        f"STRICT_PROBE: **{stg.get('strict_probe', False)}**",
        f"Watchdog check (s): **{stg.get('watchdog_check', 0)}**",
        f"Max disconnect (s): **{stg.get('watchdog_max_disc', 0)}**",
    ]
    e.add_field(name="Settings", value="\n".join(settings_lines), inline=False)

    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e


def build_digest_embed(bot_version: str, summary: dict, legacy_commands: list) -> discord.Embed:
    e = build_health_embed(bot_version, summary)
    if legacy_commands:
        e.add_field(
            name="Legacy staff commands present",
            value=", ".join(legacy_commands),
            inline=False,
        )
    e.title = "🏆 Appreciation & Claims — Digest"
    return e


def build_config_embed(bot_version: str, config_snapshot: dict) -> discord.Embed:
    # config_snapshot: {source, loaded_at, claims, levels, audit, gk_role, counts:{ach,cat,lvls}}
    e = discord.Embed(title="Current configuration", color=discord.Color.blurple())
    e.add_field(name="Claims thread", value=config_snapshot.get("claims", "—"), inline=False)
    e.add_field(name="Levels channel", value=config_snapshot.get("levels", "—"), inline=False)
    e.add_field(name="Audit-log channel", value=config_snapshot.get("audit", "—"), inline=False)
    e.add_field(name="Guardian Knights role", value=config_snapshot.get("gk_role", "—"), inline=False)
    e.add_field(
        name="Source",
        value=f"{config_snapshot.get('source', '—')} — {config_snapshot.get('loaded_at', '—')}",
        inline=False,
    )
    counts = config_snapshot.get("counts", {})
    e.add_field(
        name="Loaded rows",
        value=(
            f"Achievements: **{counts.get('ach', 0)}**\n"
            f"Categories: **{counts.get('cat', 0)}**\n"
            f"Levels: **{counts.get('lvls', 0)}**"
        ),
        inline=False,
    )
    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e


def build_env_embed(bot_version: str, env_info: dict) -> discord.Embed:
    lines = [f"• {k}: **{v}**" for k, v in env_info.items()]
    e = discord.Embed(title="Environment (sanitized)", description="\n".join(lines) or "—", color=discord.Color.blurple())
    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e


def build_checksheet_embed(bot_version: str, status: dict) -> discord.Embed:
    # status: backend, tabs=[(name, ok, note), ...]
    e = discord.Embed(title="Config check", color=discord.Color.blurple())
    e.add_field(name="Backend", value=f"**{status.get('backend', '—')}**", inline=False)

    tabs = status.get("tabs") or []
    if tabs:
        lines = []
        for name, ok, note in tabs:
            mark = "✅" if ok else "⚠️"
            lines.append(f"{mark} **{name}** — {note}")
        e.add_field(name="Worksheets", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Worksheets", value="—", inline=False)

    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e
