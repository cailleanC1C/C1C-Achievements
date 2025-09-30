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
    """Return 'YYYY-MM-DD HH:MM Europe/Vienna' (fallback to UTC on any issue)."""
    try:
        if ZoneInfo is not None:
            tz = ZoneInfo("Europe/Vienna")
            return datetime.now(tz).strftime("%Y-%m-%d %H:%M Europe/Vienna")
    except Exception:
        pass
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def build_health_embed(bot_version: str, summary: dict) -> discord.Embed:
    """
    summary keys:
      runtime: {uptime:str, ready:bool, latency_ms:int|None, last_event_age_s:int|None}
      gateway: {connected:bool}
      config:  {source:str, loaded_at:str}
      counts:  {ach:int, cat:int, lvls:int, reasons:int}
      targets: {claims:str, levels:str, audit:str, gk_role:str}
      settings:{auto_refresh:int, strict_probe:bool, watchdog_check:int, watchdog_max_disc:int}
    """
    e = discord.Embed(
        title="🏆 Appreciation & Claims — Health",
        color=discord.Color.blurple(),
    )

    rt = summary.get("runtime", {})
    gw = summary.get("gateway", {})
    cfg = summary.get("config", {})
    cnt = summary.get("counts", {})
    tgt = summary.get("targets", {})
    stg = summary.get("settings", {})

    runtime_lines = [
        f"Uptime: **{rt.get('uptime','—')}**",
        f"Ready: **{rt.get('ready', False)}**",
        f"Latency: **{rt.get('latency_ms','—')} ms**" if rt.get("latency_ms") is not None else "Latency: **—**",
        f"Last event age: **{rt.get('last_event_age_s','—')} s**" if rt.get("last_event_age_s") is not None else "Last event age: **—**",
        f"Connected: **{gw.get('connected', False)}**",
    ]
    e.add_field(name="Runtime", value="\n".join(runtime_lines), inline=False)

    config_lines = [
        f"Source: **{cfg.get('source','—')}**",
        f"Loaded at: **{cfg.get('loaded_at','—')}**",
        f"Achievements: **{cnt.get('ach',0)}** • Categories: **{cnt.get('cat',0)}** • Levels: **{cnt.get('lvls',0)}** • Reasons: **{cnt.get('reasons',0)}**",
    ]
    e.add_field(name="Config", value="\n".join(config_lines), inline=False)

    targets_lines = [
        f"Claims thread: {tgt.get('claims','—')}",
        f"Levels channel: {tgt.get('levels','—')}",
        f"Audit-log channel: {tgt.get('audit','—')}",
        f"GK role: {tgt.get('gk_role','—')}",
    ]
    e.add_field(name="Destinations", value="\n".join(targets_lines), inline=False)

    settings_lines = [
        f"Auto-refresh (min): **{stg.get('auto_refresh',0)}**",
        f"STRICT_PROBE: **{stg.get('strict_probe', False)}**",
        f"Watchdog check (s): **{stg.get('watchdog_check',0)}**",
        f"Max disconnect (s): **{stg.get('watchdog_max_disc',0)}**",
    ]
    e.add_field(name="Settings", value="\n".join(settings_lines), inline=False)

    e.set_footer(text=f"Bot v{bot_version} • CoreOps v1 • {_vienna_now_str()}")
    return e


def build_digest_embed(bot_version: str, summary: dict, legacy_commands: list[str]) -> discord.Embed:
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
    """
    config_snapshot:
      source:str, loaded_at:str
      claims:str, levels:str, audit:str, gk_role:str
      counts:{ach:int, cat:int, lvls:int}
    """
    e = discord.Embed(title="Current configuration", color=discord.Color.blurple())
    e.add_field(name="Claims thread", value=config_snapshot.get("claims","—"), inline=False)
    e.add_field(name="Levels channel", value=config_snapshot.get("levels","—"), inline=False)
    e.add_field(name="Audit-log channel", value=config_snapshot.get("audit","—"), inline=False)
    e.add_field(name="Guardian Knights role", v_
