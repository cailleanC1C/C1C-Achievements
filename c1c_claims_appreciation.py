# c1c_claims_appreciation.py
# C1C Appreciation + Claims Bot — v1.0.1 (Phase 1)
# Web Service (Flask keep-alive) + config loader + review flow

import os, re, json, asyncio, logging, datetime, threading
from typing import Optional, List, Dict, Tuple
from functools import partial
from urllib.parse import urlparse

import discord
from discord.ext import commands
from flask import Flask
from aiohttp import ClientConnectorError

from core.prefix import get_prefix
from shared import config as shared_config

BOT_VERSION = "1.0.1"

# ---------------- keep-alive (Render web service) ----------------
app = Flask(__name__)

@app.route("/")
def health():
    return "ok", 200

def keep_alive():
    port = int(os.getenv("PORT", "10000"))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()

# ---------------- optional libs for config sources ----------------
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None

try:
    import pandas as pd
except Exception:
    pd = None

# ---------------- logging ----------------
log = logging.getLogger("c1c-claims")
logging.basicConfig(level=logging.INFO)

# ---------------- runtime telemetry ----------------
START_TIME = datetime.datetime.utcnow()
_LAST_EVENT_TS = START_TIME
BOT_CONNECTED = False


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or str(default))
    except Exception:
        return default


STRICT_PROBE = _env_truthy("STRICT_PROBE", default=False)
WATCHDOG_CHECK_SEC = _int_env("WATCHDOG_CHECK_SEC", 60)
WATCHDOG_MAX_DISCONNECT_SEC = _int_env("WATCHDOG_MAX_DISCONNECT_SEC", 600)


def _touch_event() -> None:
    global _LAST_EVENT_TS
    _LAST_EVENT_TS = datetime.datetime.utcnow()


def _last_event_age_s() -> int:
    try:
        return max(0, int((datetime.datetime.utcnow() - _LAST_EVENT_TS).total_seconds()))
    except Exception:
        return 0


def uptime_str() -> str:
    delta = datetime.datetime.utcnow() - START_TIME
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    parts.append(f"{hours:02}h")
    parts.append(f"{minutes:02}m")
    parts.append(f"{seconds:02}s")
    return " ".join(parts)
    
# ---------------- discord client ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix=get_prefix, intents=intents, strip_after_prefix=True)
# Ensure prefixes like "!sc" accept a space-separated command (e.g., "!sc health").

# disable default help so we can own !help behavior
try:
    bot.remove_command("help")
except Exception:
    pass

# ---------------- runtime config ----------------
CFG = {
    "public_claim_thread_id": None,
    "levels_channel_id": None,
    "audit_log_channel_id": None,
    "guardian_knights_role_id": None,
    "group_window_seconds": 60,
    "max_file_mb": 8,
    "allowed_mimes": {"image/png", "image/jpeg", "image/webp", "image/gif"},
    "locale": "en",
    "hud_language": "EN",
    "embed_author_name": None,         # blank disables the author row
    "embed_author_icon": None,
    "embed_footer_text": "C1C Achievements",
    "embed_footer_icon": None,
}
CATEGORIES: List[dict] = []
ACHIEVEMENTS: Dict[str, dict] = {}
LEVELS: List[dict] = []
REASONS: Dict[str, str] = {}
FEATURE_TOGGLE_DEFAULTS: Dict[str, bool] = {}
CONFIG_META = {"source": "—", "loaded_at": None, "status": "cold", "last_error": None}
CONFIG_READY = asyncio.Event()
_AUTO_REFRESH_TASK: Optional[asyncio.Task] = None
_INITIAL_CONFIG_TASK: Optional[asyncio.Task] = None

shared_config.configure_feature_toggles(defaults=FEATURE_TOGGLE_DEFAULTS)

# ---- claim lifecycle: first prompt message id -> "open" | "canceled" | "expired" | "closed"
CLAIM_STATE: Dict[int, str] = {}

# ---------------- config loading ----------------
def _svc_creds():
    raw = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    data = json.loads(raw) if raw.startswith("{") else json.load(open(raw, "r", encoding="utf-8"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    return Credentials.from_service_account_info(data, scopes=scopes)

def _truthy(x) -> bool:
    if isinstance(x, bool): return x
    return str(x or "").strip().lower() in ("true", "yes", "y", "1", "wahr", "on", "enabled")

def _set_or_default(d: dict, key: str, default):
    val = d.get(key, default)
    if key == "allowed_mimes" and isinstance(val, str):
        return set(x.strip() for x in val.split(",") if x.strip())
    return val if val not in (None, "") else default

def _to_str(x) -> str:
    if x is None: return ""
    if isinstance(x, float): return str(int(x)) if x.is_integer() else str(x)
    if isinstance(x, int): return str(x)
    return str(x)

def _color_from_hex(hex_str: Optional[str]) -> Optional[discord.Color]:
    if hex_str in (None, ""): return None
    try:
        s = _to_str(hex_str).strip().lstrip("#")
        return discord.Color(int(s, 16))
    except Exception:
        return None

def _safe_icon(icon_val: Optional[str]) -> Optional[str]:
    s = _to_str(icon_val).strip()
    if not s:
        return None
    try:
        u = urlparse(s)
        if u.scheme in ("http", "https") and u.netloc:
            return s
    except Exception:
        pass
    return None

def _opt(row: dict, key: str, default=None):
    if key in row:
        val = row.get(key)
        s = _to_str(val).strip()
        return None if s == "" else val
    return default

def _clean(text: Optional[str]) -> str:
    s = _to_str(text)
    if not s:
        return ""
    s = s.replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    return s

def _rows_to_feature_toggles(rows: List[dict]) -> Dict[str, bool]:
    toggles: Dict[str, bool] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name: Optional[str] = None
        for key in ("name", "toggle", "feature", "key"):
            val = row.get(key)
            if val is not None:
                s = _to_str(val).strip()
                if s:
                    name = s
                    break
        if not name:
            continue
        state_val = None
        for key in ("enabled", "value", "on", "is_enabled", "enabled?"):
            if key in row:
                state_val = row.get(key)
                break
        toggles[name] = _truthy(state_val) if state_val is not None else False
    return toggles


def load_config():
    sid   = os.getenv("CONFIG_SHEET_ID", "").strip()
    local = os.getenv("LOCAL_CONFIG_XLSX", "").strip()
    global CFG, CATEGORIES, ACHIEVEMENTS, LEVELS, REASONS, CONFIG_META

    log.info(f"[boot] CONFIG_SHEET_ID set={bool(sid)} | LOCAL_CONFIG_XLSX set={bool(local)} | "
             f"gspread_loaded={gspread is not None} | pandas_loaded={pd is not None}")

    loaded = False
    source = "—"
    last_exc: Optional[Exception] = None

    CONFIG_META["status"] = "loading"
    CONFIG_META["last_error"] = None

    shared_config.configure_feature_toggles(overrides={})

    if sid and gspread:
        try:
            creds = _svc_creds()
            if not creds:
                raise RuntimeError("SERVICE_ACCOUNT_JSON missing/invalid")
            gc = gspread.authorize(creds)
            sh = gc.open_by_key(sid)

            row = sh.worksheet("General").get_all_records()[0]
            CFG.update({
                "public_claim_thread_id": int(row.get("public_claim_thread_id") or 0) or None,
                "levels_channel_id": int(row.get("levels_channel_id") or 0) or None,
                "audit_log_channel_id": int(row.get("audit_log_channel_id") or 0) or None,
                "guardian_knights_role_id": int(row.get("guardian_knights_role_id") or 0) or None,
                "group_window_seconds": int(row.get("group_window_seconds") or 60),
                "max_file_mb": int(row.get("max_file_mb") or 8),
                "allowed_mimes": _set_or_default(row, "allowed_mimes", CFG["allowed_mimes"]),
                "locale": row.get("locale") or "en",
                "hud_language": row.get("hud_language") or "EN",
                "embed_author_name": _opt(row, "embed_author_name", CFG["embed_author_name"]),
                "embed_author_icon": _opt(row, "embed_author_icon", CFG["embed_author_icon"]),
                "embed_footer_text": _opt(row, "embed_footer_text", CFG["embed_footer_text"]) or CFG["embed_footer_text"],
                "embed_footer_icon": _opt(row, "embed_footer_icon", CFG["embed_footer_icon"]),
            })
            CATEGORIES = sh.worksheet("Categories").get_all_records()
            ACHIEVEMENTS = {r["key"]: r for r in sh.worksheet("Achievements").get_all_records() if _truthy(r.get("Active", True))}
            try:
                LEVELS = [r for r in sh.worksheet("Levels").get_all_records() if _truthy(r.get("Active", True))]
            except Exception:
                LEVELS = []
            REASONS = {r["code"]: r["message"] for r in sh.worksheet("Reasons").get_all_records()}

            toggle_rows: List[dict] = []
            try:
                ws = sh.worksheet("FeatureToggles")
                toggle_rows = ws.get_all_records()
            except Exception as exc:
                if getattr(gspread, "WorksheetNotFound", None) and isinstance(exc, gspread.WorksheetNotFound):
                    toggle_rows = []
                else:
                    log.warning(f"Feature toggles load failed: {exc}", exc_info=True)
                    toggle_rows = []
            shared_config.configure_feature_toggles(overrides=_rows_to_feature_toggles(toggle_rows))

            loaded = True
            source = "Google Sheets"
            log.info("Config loaded from Google Sheets")
        except Exception as e:
            log.warning(f"GSheet load failed: {e}", exc_info=True)
            last_exc = e

    if not loaded and local and pd:
        try:
            if not os.path.isabs(local):
                local = os.path.join("/opt/render/project/src", local)
            xl = pd.ExcelFile(local)
            gen = pd.read_excel(xl, "General").to_dict("records")[0]
            CFG.update({
                "public_claim_thread_id": int(gen.get("public_claim_thread_id") or 0) or None,
                "levels_channel_id": int(gen.get("levels_channel_id") or 0) or None,
                "audit_log_channel_id": int(gen.get("audit_log_channel_id") or 0) or None,
                "guardian_knights_role_id": int(gen.get("guardian_knights_role_id") or 0) or None,
                "group_window_seconds": int(gen.get("group_window_seconds") or 60),
                "max_file_mb": int(gen.get("max_file_mb") or 8),
                "allowed_mimes": _set_or_default(gen, "allowed_mimes", CFG["allowed_mimes"]),
                "locale": gen.get("locale") or "en",
                "hud_language": gen.get("hud_language") or "EN",
                "embed_author_name": _opt(gen, "embed_author_name", CFG["embed_author_name"]),
                "embed_author_icon": _opt(gen, "embed_author_icon", CFG["embed_author_icon"]),
                "embed_footer_text": _opt(gen, "embed_footer_text", CFG["embed_footer_text"]) or CFG["embed_footer_text"],
                "embed_footer_icon": _opt(gen, "embed_footer_icon", CFG["embed_footer_icon"]),
            })
            CATEGORIES = pd.read_excel(xl, "Categories").to_dict("records")
            ACHIEVEMENTS = {r["key"]: r for r in pd.read_excel(xl, "Achievements").to_dict("records") if _truthy(r.get("Active", True))}
            try:
                LEVELS = [r for r in pd.read_excel(xl, "Levels").to_dict("records") if _truthy(r.get("Active", True))]
            except Exception:
                LEVELS = []
            REASONS = {r["code"]: r["message"] for r in pd.read_excel(xl, "Reasons").to_dict("records")}

            toggle_rows: List[dict] = []
            try:
                toggle_rows = pd.read_excel(xl, "FeatureToggles").to_dict("records")
            except ValueError:
                toggle_rows = []
            except Exception as exc:
                log.warning(f"Feature toggles load failed: {exc}", exc_info=True)
                toggle_rows = []
            shared_config.configure_feature_toggles(overrides=_rows_to_feature_toggles(toggle_rows))

            loaded = True
            source = "Excel file"
            log.info("Config loaded from Excel")
        except Exception as e:
            log.error(f"Excel load failed: {e}", exc_info=True)
            last_exc = e

    if not loaded:
        CONFIG_META["status"] = "error"
        CONFIG_META["last_error"] = str(last_exc) if last_exc else "no config source succeeded"
        raise RuntimeError("No config loaded. Set CONFIG_SHEET_ID (+SERVICE_ACCOUNT_JSON) or LOCAL_CONFIG_XLSX.")

    CONFIG_META["source"] = source
    CONFIG_META["loaded_at"] = datetime.datetime.utcnow()
    CONFIG_META["status"] = "ready"
    CONFIG_META["last_error"] = None
    CONFIG_READY.set()


async def _ensure_config_loaded(initial: bool = False) -> None:
    """Ensure configuration is present, retrying with backoff when booting."""
    if CONFIG_READY.is_set() and CONFIG_META.get("status") == "ready":
        return

    base_delay = 5
    attempt = 0

    while True:
        try:
            load_config()
            return
        except Exception as e:
            attempt += 1
            wait = min(300, base_delay * (2 ** (attempt - 1)))
            CONFIG_META["status"] = "error"
            CONFIG_META["last_error"] = str(e)
            CONFIG_READY.clear()

            level = logging.ERROR if attempt <= 3 else logging.WARNING
            log.log(level, f"[config] load failed (attempt {attempt}): {e}", exc_info=attempt <= 3)

            if not initial:
                raise

            await asyncio.sleep(wait)

# ---------- COG LOADER ----------
async def _load_ext(name: str) -> bool:
    try:
        # most modern cogs use async setup(bot)
        await bot.load_extension(name)
        log.info(f"[cogs] loaded {name}")
        return True
    except TypeError:
        # fallback for legacy sync setup(bot)
        bot.load_extension(name)
        log.info(f"[cogs] loaded (sync) {name}")
        return True
    except Exception as e:
        log.warning(f"[cogs] failed {name}: {e}")
        return False

@bot.event
async def setup_hook():
    async def _load(name: str) -> bool:
        try:
            try:
                await bot.load_extension(name)   # async extensions
            except TypeError:
                bot.load_extension(name)         # legacy sync
            log.info(f"[cogs] loaded {name}")
            return True
        except Exception as e:
            log.warning(f"[cogs] failed {name}: {e}")
            return False

    # Load the NEW help (not the old middleware one)
    await _load("claims.help")

    # CoreOps: prefer cogs/ops.py, fallback to claims/middleware/ops.py
    loaded_ops = await _load("cogs.ops")
    if not loaded_ops:
        await _load("claims.middleware.ops")

    # 🔹 Add the Shards & Mercy module
    await _load("cogs.shards")

# ---------------- helpers ----------------
def _is_image(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower().split(";")[0].strip()
    if ct in CFG["allowed_mimes"]:
        return True
    fn = att.filename.lower()
    return fn.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))

def _big_role_icon_url(role: discord.Role) -> Optional[str]:
    asset = getattr(role, "display_icon", None) or getattr(role, "icon", None)
    if asset:
        try: return asset.with_size(512).url
        except Exception: return asset.url
    return None

def _get_role_by_config(guild: discord.Guild, ach_row: dict) -> Optional[discord.Role]:
    rid = int(ach_row.get("role_id") or 0)
    if rid:
        r = guild.get_role(rid)
        if r: return r
    name = ach_row.get("display_name") or ach_row.get("key")
    return discord.utils.get(guild.roles, name=name)

def _category_by_key(cat_key: str) -> Optional[dict]:
    for c in CATEGORIES:
        if c.get("category") == cat_key:
            return c
    return None

EMOJI_TAG_RE = re.compile(r"^<a?:\w+:\d+>$")

def resolve_emoji_text(guild: discord.Guild, value: Optional[str], fallback: Optional[str]=None) -> str:
    v = _to_str(value).strip()
    if not v:
        v = _to_str(fallback).strip()
    if not v:
        return ""
    if EMOJI_TAG_RE.match(v):
        return v
    if v.isdigit():
        e = discord.utils.get(guild.emojis, id=int(v))
        return f"<{'a' if e.animated else ''}:{e.name}:{e.id}>" if e else ""
    e = discord.utils.get(guild.emojis, name=v)
    return f"<{'a' if e.animated else ''}:{e.name}:{e.id}>" if e else v

def _inject_tokens(text: str, *, user: discord.Member, role: discord.Role, emoji: str) -> str:
    return (text or "").replace("{user}", user.mention).replace("{role}", role.name).replace("{emoji}", emoji)

def _httpish(url: Optional[str]) -> Optional[str]:
    u = _to_str(url).strip()
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return None

def resolve_hero_image(guild: discord.Guild, role: discord.Role, ach_row: dict) -> Optional[str]:
    cat = _category_by_key(ach_row.get("category") or "")
    return _httpish(ach_row.get("HeroImageURL")) or _httpish((cat or {}).get("hero_image_url")) or _big_role_icon_url(role)

async def safe_send_embed(dest, embed: discord.Embed, *, ping_user: Optional[discord.abc.User] = None):
    try:
        content = ping_user.mention if ping_user else None
        am = discord.AllowedMentions(
            users=True, roles=False, everyone=False, replied_user=False
        ) if ping_user else None
        return await dest.send(content=content, embed=embed, allowed_mentions=am)
    except discord.Forbidden:
        return await dest.send(
            "I tried to send an embed here but I'm missing **Embed Links**.\n"
            "Ask an admin to enable that for me in this channel."
        )
    except Exception as e:
        return await dest.send(f"Couldn’t send embed: `{e}`")

def _resolve_target_channel(ctx: commands.Context, where: Optional[str]):
    if not where:
        ch = ctx.guild.get_channel(CFG.get("levels_channel_id") or 0)
        return ch or ctx.channel
    w = where.strip().lower()
    if w == "here":
        return ctx.channel
    if ctx.message.channel_mentions:
        return ctx.message.channel_mentions[0]
    digits = re.sub(r"[^\d]", "", where)
    if digits.isdigit():
        ch = ctx.guild.get_channel(int(digits))
        if ch: return ch
    return ctx.channel

def _match_levels_row_by_role(role: discord.Role) -> Optional[dict]:
    """Find the LEVELS row associated with a given role."""
    # Prefer explicit role_id if provided in the sheet
    for r in LEVELS:
        try:
            rid = int(r.get("role_id") or 0)
        except Exception:
            rid = 0
        if rid and rid == role.id:
            return r

    # Fallback: match by display_name or level_key to the role name
    rname = role.name.strip().lower()
    for r in LEVELS:
        dn = (r.get("display_name") or "").strip().lower()
        lk = (r.get("level_key") or "").strip().lower()
        if dn and dn == rname:
            return r
        if lk and lk == rname:
            return r
    return None

async def _fmt_chan_or_thread(guild: discord.Guild, chan_id: int | None) -> str:
    if not chan_id:
        return "—"
    obj = guild.get_channel(chan_id)
    if obj is None:
        try:
            obj = await guild.fetch_channel(chan_id)
        except Exception:
            obj = None
    if obj is None:
        return f"(unknown) `{chan_id}`"
    name = getattr(obj, "name", "unknown")
    mention = getattr(obj, "mention", f"`#{name}`")
    return f"{mention} — **{name}** `{chan_id}`"

def _fmt_role(guild: discord.Guild, role_id: int | None) -> str:
    if not role_id:
        return "—"
    r = guild.get_role(role_id)
    if not r:
        return f"(unknown role) `{role_id}`"
    return f"{r.mention} — **{r.name}** `{role_id}`"

# ---------------- embed builders ----------------
def build_achievement_embed(guild: discord.Guild, user: discord.Member, role: discord.Role, ach_row: dict) -> discord.Embed:
    cat = _category_by_key(ach_row.get("category") or "")
    emoji = resolve_emoji_text(guild, ach_row.get("EmojiNameOrId"), fallback=(cat or {}).get("emoji"))
    title  = _inject_tokens(_clean(ach_row.get("Title"))  or f"{role.name} unlocked!", user=user, role=role, emoji=emoji)
    body   = _inject_tokens(_clean(ach_row.get("Body"))   or f"{user.mention} just unlocked **{role.name}**.", user=user, role=role, emoji=emoji)
    footer = _inject_tokens(_clean(ach_row.get("Footer")) or "", user=user, role=role, emoji=emoji)
    color = _color_from_hex(ach_row.get("ColorHex")) or (role.color if getattr(role.color, "value", 0) else discord.Color.blurple())

    emb = discord.Embed(title=title, description=body, color=color, timestamp=datetime.datetime.utcnow())

    if CFG.get("embed_author_name"):
        icon = _safe_icon(CFG.get("embed_author_icon"))
        if icon: emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
        else:    emb.set_author(name=CFG["embed_author_name"])

    footer_text = footer or CFG.get("embed_footer_text")
    if footer_text:
        ficon = _safe_icon(CFG.get("embed_footer_icon"))
        if ficon: emb.set_footer(text=footer_text, icon_url=ficon)
        else:     emb.set_footer(text=footer_text)

    hero = resolve_hero_image(guild, role, ach_row)
    if hero:
        emb.set_thumbnail(url=hero)  # top-right
    return emb

def build_group_embed(guild: discord.Guild, user: discord.Member, items: List[Tuple[discord.Role, dict]]) -> discord.Embed:
    r0, a0 = items[0]
    color = _color_from_hex(a0.get("ColorHex")) or (r0.color if getattr(r0.color, "value", 0) else discord.Color.blurple())
    emb = discord.Embed(title=f"{user.display_name} unlocked {len(items)} achievements", color=color, timestamp=datetime.datetime.utcnow())

    if CFG.get("embed_author_name"):
        icon = _safe_icon(CFG.get("embed_author_icon"))
        if icon: emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
        else:    emb.set_author(name=CFG["embed_author_name"])

    lines = []
    for r, a in items:
        cat = _category_by_key(a.get("category") or "")
        emoji = resolve_emoji_text(guild, a.get("EmojiNameOrId"), fallback=(cat or {}).get("emoji"))
        body = _inject_tokens(_clean(a.get("Body")) or f"{user.mention} just unlocked **{r.name}**.", user=user, role=r, emoji=emoji)
        lines.append(f"• {body}")
    emb.description = "\n".join(lines)

    hero = resolve_hero_image(guild, r0, a0)
    if hero:
        emb.set_thumbnail(url=hero)  # top-right
    footer_text = CFG.get("embed_footer_text")
    if footer_text:
        ficon = _safe_icon(CFG.get("embed_footer_icon"))
        if ficon: emb.set_footer(text=footer_text, icon_url=ficon)
        else:     emb.set_footer(text=footer_text)
    return emb

def build_level_embed(guild: discord.Guild, user: discord.Member, row: dict) -> discord.Embed:
    emoji = resolve_emoji_text(guild, row.get("EmojiNameOrId"))
    role_for_tokens = user.top_role if user.top_role else user.guild.default_role
    title  = _inject_tokens(_clean(row.get("Title"))  or "Level up!", user=user, role=role_for_tokens, emoji=emoji)
    body   = _inject_tokens(_clean(row.get("Body"))   or "{user} leveled up!", user=user, role=role_for_tokens, emoji=emoji)
    footer = _inject_tokens(_clean(row.get("Footer")) or "", user=user, role=role_for_tokens, emoji=emoji)
    color = _color_from_hex(row.get("ColorHex")) or discord.Color.gold()

    emb = discord.Embed(title=title, description=body, color=color, timestamp=datetime.datetime.utcnow())

    if CFG.get("embed_author_name"):
        icon = _safe_icon(CFG.get("embed_author_icon"))
        if icon: emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
        else:    emb.set_author(name=CFG["embed_author_name"])

    footer_text = footer or CFG.get("embed_footer_text")
    if footer_text:
        ficon = _safe_icon(CFG.get("embed_footer_icon"))
        if ficon: emb.set_footer(text=footer_text, icon_url=ficon)
        else:     emb.set_footer(text=footer_text)
    return emb

# ---------------- grouping buffer ----------------
GROUP: Dict[int, Dict[int, dict]] = {}

async def _flush_group(guild: discord.Guild, user_id: int):
    entry = GROUP.get(guild.id, {}).pop(user_id, None)
    if not entry:
        return
    levels_ch = guild.get_channel(CFG.get("levels_channel_id") or 0) if CFG.get("levels_channel_id") else None
    items = (entry or {}).get("items") or []
    if not levels_ch:
        log.warning("[praise] levels_channel_id missing/unreachable; skipping.")
        await audit(guild, f"praise_failed: levels_channel_unavailable items={len(items)} user=<@{user_id}>")
        return
    user = guild.get_member(user_id) or await guild.fetch_member(user_id)
    if len(items) == 1:
        r, ach = items[0]
        await safe_send_embed(levels_ch, build_achievement_embed(guild, user, r, ach), ping_user=user)
    else:
        await safe_send_embed(levels_ch, build_group_embed(guild, user, items), ping_user=user)
    await audit(guild, f"praise_posted: items={len(items)} user=<@{user_id}>")

def _buffer_item(guild: discord.Guild, user_id: int, role: discord.Role, ach: dict):
    g = GROUP.setdefault(guild.id, {})
    e = g.get(user_id)
    if not e:
        e = g[user_id] = {"items": [], "task": None}
    e["items"].append((role, ach))
    asyncio.create_task(audit(guild, f"praise_enqueued: +1 user=<@{user_id}> ach=`{ach.get('key','?')}`"))

    delay = max(0, int(CFG.get("group_window_seconds") or 0))  # set 0 in sheet for instant mode
    if e["task"]:
        e["task"].cancel()

    async def _delay():
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await _flush_group(guild, user_id)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("[praise] flush failed")

    e["task"] = asyncio.create_task(_delay())

# ---------------- audit helper ----------------
async def audit(guild: discord.Guild, text: str):
    """Post a short line to the audit-log channel, if configured, and log to console."""
    try:
        ch_id = CFG.get("audit_log_channel_id") or 0
        ch = guild.get_channel(ch_id) if ch_id else None
        if ch:
            await ch.send(text)
        else:
            log.info("[AUDIT:%s] %s", guild.id, text)
    except Exception as e:
        log.warning("[audit] failed to send: %r | text=%s", e, text)

# ---------------- GK Review views ----------------

class TryAgainView(discord.ui.View):
    def __init__(self, owner_id: int, att: Optional[discord.Attachment], claim_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.att = att
        self.claim_id = claim_id

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        state = CLAIM_STATE.get(self.claim_id)
        if state and state != "open":
            try:
                await itx.response.send_message("This claim is already closed.", ephemeral=True)
            except Exception:
                pass
            return False
        if itx.user.id != self.owner_id:
            await itx.response.send_message("This belongs to someone else. Upload your own screenshot to claim.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Try again", style=discord.ButtonStyle.primary)
    async def try_again(self, itx: discord.Interaction, _btn: discord.ui.Button):
        await show_category_picker(itx, self.att, claim_id=self.claim_id)

class GKReview(discord.ui.View):
    def __init__(self, claimant_id: int, ach_key: str, att: Optional[discord.Attachment], claim_id: int):
        super().__init__(timeout=None)  # persist until acted upon
        self.claimant_id = claimant_id
        self.ach_key = ach_key
        self.att = att
        self.claim_id = claim_id

    async def _only_gk(self, itx: discord.Interaction) -> bool:
        rid = CFG.get("guardian_knights_role_id")
        mem = itx.guild.get_member(itx.user.id)
        if not rid or not mem or not any(r.id == rid for r in mem.roles):
            await itx.response.send_message("Guardian Knights only.", ephemeral=True)
            return False
        return True

    def _disable_all(self):
        for c in self.children:
            c.disabled = True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx):
            return
        self._disable_all()  # stop double-click races
        await itx.response.defer(ephemeral=True)

        ach = ACHIEVEMENTS.get(self.ach_key) or {}
        role = _get_role_by_config(itx.guild, ach)
        member = itx.guild.get_member(self.claimant_id) or await itx.guild.fetch_member(self.claimant_id)

        if role and member and role in member.roles:
            try:
                emb = discord.Embed(
                    title="Already has this role",
                    description=f"{member.mention} already has {role.mention}.",
                    color=discord.Color.yellow(),
                    timestamp=datetime.datetime.utcnow(),
                )
                await itx.message.edit(embed=emb, content=None, view=None)
                CLAIM_STATE[self.claim_id] = "closed"
            except Exception as e:
                log.warning("[approve already-has] edit failed: %r", e)
            return

        ok = await finalize_grant(itx.guild, self.claimant_id, self.ach_key)
        try:
            if ok:
                CLAIM_STATE[self.claim_id] = "closed"
                emb = discord.Embed(
                    title="Approved",
                    description=f"Granted {role.mention} to {member.mention}.",
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.utcnow(),
                )
                await itx.message.edit(embed=emb, content=None, view=None)
                await audit(itx.guild, f"gk_approved: role=`{self.ach_key}` user=<@{self.claimant_id}> by=<@{itx.user.id}>")
                await itx.followup.send("Granted.", ephemeral=True)
            else:
                emb = discord.Embed(
                    title="Approval failed",
                    description=("I couldn’t assign the role. Check **Manage Roles** and make sure my **top role** "
                                 "is above the target role, then try again."),
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.utcnow(),
                )
                await itx.message.edit(embed=emb, content=None, view=None)
                await audit(itx.guild, f"gk_approve_failed: role=`{self.ach_key}` user=<@{self.claimant_id}> by=<@{itx.user.id}>")
                await itx.followup.send("Couldn’t grant. See audit-log for details.", ephemeral=True)
        except Exception as e:
            log.warning("[approve] message edit failed: %r", e)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx):
            return

        # Build reason selector (up to 25 options)
        opts = []
        for code, text in REASONS.items():
            label = (text or code)[:100]
            opts.append(discord.SelectOption(label=label, value=code))
        if not opts:
            opts = [discord.SelectOption(label="Proof unclear. Please include the full result banner.", value="NEED_BANNER")]

        v = discord.ui.View(timeout=300)
        sel = discord.ui.Select(placeholder="Pick a denial reason…", options=opts)

        async def _on_pick(sel_itx: discord.Interaction):
            if not await self._only_gk(sel_itx):
                return
            code = (sel_itx.data.get("values") or [None])[0]
            reason = REASONS.get(code) or code or "No reason provided"
            try:
                emb = discord.Embed(
                    title="Denied",
                    description=f"Reason: **{reason}**\nPost a clearer screenshot and hit **Try Again**.",
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.utcnow(),
                )
                await itx.message.edit(embed=emb, content=None, view=TryAgainView(self.claimant_id, self.att, claim_id=self.claim_id))
                CLAIM_STATE[self.claim_id] = "closed"
                await audit(sel_itx.guild, f"gk_denied: role=`{self.ach_key}` user=<@{self.claimant_id}> reason={code} by=<@{sel_itx.user.id}>")
                await sel_itx.response.send_message(f"Denied with reason: {reason}", ephemeral=True)
            except Exception as e:
                log.warning("[deny] edit failed: %r", e)

        sel.callback = _on_pick
        v.add_item(sel)
        await itx.response.send_message("Pick a reason for denial:", view=v, ephemeral=True)

    @discord.ui.button(label="Grant different role…", style=discord.ButtonStyle.secondary)
    async def grant_other(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx):
            return

        base = ACHIEVEMENTS.get(self.ach_key) or {}
        base_cat = base.get("category")

        achs = [
            a for a in ACHIEVEMENTS.values()
            if a.get("category") == base_cat and a.get("key") != self.ach_key
        ]
        achs.sort(key=lambda a: (a.get("display_name") or a.get("key") or "").lower())
        if not achs:
            return await itx.response.send_message("No alternative roles in this category.", ephemeral=True)
        if len(achs) > 25:
            log.warning("[grant_other] trimmed options from %d to 25 in category=%s", len(achs), base_cat)
            achs = achs[:25]

        opts = []
        for a in achs:
            label = (a.get("display_name") or a.get("key") or "Unnamed")[:100]
            opts.append(discord.SelectOption(label=label, value=a["key"]))

        v = discord.ui.View(timeout=600)
        sel = discord.ui.Select(placeholder="Pick a role to grant instead…", options=opts)

        async def _on_pick(sel_itx: discord.Interaction):
            if not await self._only_gk(sel_itx):
                return
            key = (sel_itx.data.get("values") or [None])[0]
            if not key or key not in ACHIEVEMENTS:
                return await sel_itx.response.send_message("That selection isn’t available anymore. Try again.", ephemeral=True)
            await sel_itx.response.defer(ephemeral=True)
            ok = await finalize_grant(sel_itx.guild, self.claimant_id, key)
            try:
                if ok:
                    await itx.message.edit(embed=discord.Embed(
                        title="Approved (different role)",
                        description=f"Granted **{ACHIEVEMENTS[key].get('display_name') or key}** to <@{self.claimant_id}>.",
                        color=discord.Color.green(),
                        timestamp=datetime.datetime.utcnow(),
                    ), content=None, view=None)
                    await sel_itx.edit_original_response(content="✅ Granted.", view=None)
                    await audit(sel_itx.guild, f"gk_approved_other: role=`{key}` user=<@{self.claimant_id}> by=<@{sel_itx.user.id}>")
                    CLAIM_STATE[self.claim_id] = "closed"
                else:
                    await itx.message.edit(embed=discord.Embed(
                        title="Approval failed",
                        description=("I couldn’t assign the role. Check **Manage Roles** and make sure my **top role** "
                                     "is above the target role, then try again."),
                        color=discord.Color.red(),
                        timestamp=datetime.datetime.utcnow(),
                    ), content=None, view=None)
                    await sel_itx.edit_original_response(content="⚠️ Couldn’t grant the selected role.", view=None)
            except Exception as e:
                log.warning("[grant_other] edit failed: %r", e)

        sel.callback = _on_pick
        v.add_item(sel)
        await itx.response.send_message("Choose replacement role:", view=v, ephemeral=True)

# ---------------- Pickers with claim-state awareness ----------------
class BaseView(discord.ui.View):
    def __init__(self, owner_id: int, claim_id: int, timeout=600, announce: bool = False):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.claim_id = claim_id
        self.announce = announce
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        if not self.announce:
            return
        if CLAIM_STATE.get(self.claim_id) != "open":
            return
        CLAIM_STATE[self.claim_id] = "expired"
        try:
            if self.message:
                await self.message.channel.send(f"**Claim expired for <@{self.owner_id}>.** No action needed.")
        except Exception:
            pass

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        state = CLAIM_STATE.get(self.claim_id)
        if state and state != "open":
            try:
                await itx.response.send_message("This claim is already closed.", ephemeral=True)
            except Exception:
                pass
            return False
        if itx.user.id != self.owner_id:
            await itx.response.send_message("This claim belongs to someone else. Please upload your own screenshot.", ephemeral=True)
            return False
        return True

class MultiImageChoice(BaseView):
    def __init__(self, owner_id: int, atts: List[discord.Attachment], claim_id: int, announce: bool = False):
        super().__init__(owner_id, claim_id, announce=announce)
        self.atts = [a for a in atts if _is_image(a)]

    @discord.ui.button(label="Proceed with one role", style=discord.ButtonStyle.primary)
    async def proceed_one(self, itx: discord.Interaction, _btn: discord.ui.Button):
        # Let the user choose exactly one screenshot to continue with
        view = ImageSelect(self.owner_id, self.atts, self.claim_id)
        await itx.response.edit_message(content="Pick a single screenshot to claim one role:", view=view)
        view.message = await itx.edit_original_response()

    @discord.ui.button(label="I want multiple roles", style=discord.ButtonStyle.secondary)
    async def want_multiple(self, itx: discord.Interaction, _btn: discord.ui.Button):
        # Explain policy and close the claim so they can re-post
        CLAIM_STATE[self.claim_id] = "closed"
        self.stop()
        try:
            await itx.response.edit_message(
                content=("For multiple roles, please upload **one screenshot per message** in this thread. "
                         "This claim is closed so you can re-post them one by one."),
                view=None
            )
        except discord.InteractionResponded:
            await itx.followup.send(
                "For multiple roles, upload **one screenshot per message** in this thread. "
                "This claim is closed so you can re-post them one by one.",
                ephemeral=True
            )
        try:
            await itx.channel.send(
                f"{itx.user.mention} wants multiple roles — please upload each screenshot as a separate post."
            )
        except Exception:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, itx: discord.Interaction, _btn: discord.ui.Button):
        try:
            await itx.message.delete()
        except Exception:
            pass
        CLAIM_STATE[self.claim_id] = "canceled"
        self.stop()
        await itx.channel.send(f"**Claim canceled by {itx.user.mention}.** No action needed.")

class ImageSelect(BaseView):
    def __init__(self, owner_id: int, atts: List[discord.Attachment], claim_id: int, announce: bool = False):
        super().__init__(owner_id, claim_id, announce=announce)
        self.atts = atts
        opts = [discord.SelectOption(label=f"#{i} – {a.filename}", value=str(i-1)) for i,a in enumerate(atts, start=1)]
        sel = discord.ui.Select(placeholder="Choose a screenshot…", options=opts)
        sel.callback = self._on_pick
        self.add_item(sel)

    async def _on_pick(self, itx: discord.Interaction):
        idx = int(itx.data["values"][0])
        await show_category_picker(itx, self.atts[idx], claim_id=self.claim_id)

class CategoryPicker(BaseView):
    def __init__(self, owner_id: int, att: Optional[discord.Attachment],
                 batch_list: Optional[List[discord.Attachment]], claim_id: int, announce: bool = False):
        super().__init__(owner_id, claim_id, announce=announce)
        self.att = att
        self.batch = batch_list
        for c in [c for c in CATEGORIES if _truthy(c.get("enabled", True))]:
            btn = discord.ui.Button(label=c["label"], style=discord.ButtonStyle.primary, custom_id=f"cat::{c['category']}")
            btn.callback = partial(self._pick_cat, cat_key=c["category"])
            self.add_item(btn)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _cancel(self, itx: discord.Interaction):
        try: await itx.message.delete()
        except Exception: pass
        CLAIM_STATE[self.claim_id] = "canceled"
        self.stop()
        await itx.channel.send(f"**Claim canceled by {itx.user.mention}.** No action needed.")

    async def _pick_cat(self, itx: discord.Interaction, cat_key: str):
        await show_role_picker(itx, cat_key, self.att, self.batch, claim_id=self.claim_id)

class RolePicker(BaseView):
    PAGE_SIZE = 25  # Discord hard limit per select

    def __init__(self, owner_id: int, cat_key: str, att: Optional[discord.Attachment],
                 batch_list: Optional[List[discord.Attachment]], claim_id: int, announce: bool = False, page: int = 0):
        super().__init__(owner_id, claim_id, announce=announce)
        self.cat_key = cat_key
        self.att = att
        self.batch = batch_list
        self.page = page

        achs = [a for a in ACHIEVEMENTS.values() if a.get("category") == cat_key]
        achs.sort(key=lambda r: (r.get("display_name") or r.get("key") or "").lower())

        start = self.page * self.PAGE_SIZE
        chunk = achs[start:start + self.PAGE_SIZE]
        if not chunk:
            chunk = achs[:self.PAGE_SIZE]
            self.page = 0

        opts = []
        for a in chunk:
            label = a.get("display_name") or a.get("key") or "Unnamed"
            label = (label or "Unnamed")[:100]
            opts.append(discord.SelectOption(label=label, value=a["key"]))

        sel = discord.ui.Select(placeholder="Choose the exact achievement…", options=opts, min_values=1, max_values=1)
        sel.callback = self._on_pick
        self.add_item(sel)

        # nav + basics
        prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=(self.page == 0))
        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary,
                                     disabled=(start + self.PAGE_SIZE >= len(achs)))
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)

        async def _prev(itx: discord.Interaction):
            await show_role_picker(itx, self.cat_key, self.att, self.batch, claim_id=self.claim_id, page=self.page - 1)

        async def _next(itx: discord.Interaction):
            await show_role_picker(itx, self.cat_key, self.att, self.batch, claim_id=self.claim_id, page=self.page + 1)

        async def _back(itx: discord.Interaction):
            await show_category_picker(itx, self.att, self.batch, claim_id=self.claim_id)

        async def _cancel(itx: discord.Interaction):
            try: await itx.message.delete()
            except Exception: pass
            CLAIM_STATE[self.claim_id] = "canceled"
            self.stop()
            await itx.channel.send(f"**Claim canceled by {itx.user.mention}.** No action needed.")

        prev_btn.callback = _prev
        next_btn.callback = _next
        back.callback = _back
        cancel.callback = _cancel

        self.add_item(prev_btn)
        self.add_item(next_btn)
        self.add_item(back)
        self.add_item(cancel)

    async def _on_pick(self, itx: discord.Interaction):
        await itx.response.defer()
        key = (itx.data.get("values") or [None])[0]
        if not key:
            return await itx.followup.send("No selection received. Please try again.", ephemeral=True)
        await process_claim(itx, key, self.att, self.batch, claim_id=self.claim_id)

# ---------------- Flow helpers ----------------
async def show_category_picker(itx: discord.Interaction, attachment: Optional[discord.Attachment],
                               batch_list: Optional[List[discord.Attachment]] = None, claim_id: int = 0):
    v = CategoryPicker(itx.user.id, attachment, batch_list=batch_list, claim_id=claim_id)
    try:
        await itx.response.edit_message(content="**Claim your achievement** — tap a category:", view=v)
        v.message = await itx.edit_original_response()
    except discord.InteractionResponded:
        m = await itx.followup.send("**Claim your achievement** — tap a category:", view=v)
        v.message = m

async def show_role_picker(itx: discord.Interaction, cat_key: str, attachment: Optional[discord.Attachment],
                           batch_list: Optional[List[discord.Attachment]] = None, claim_id: int = 0, page: int = 0):
    v = RolePicker(itx.user.id, cat_key, attachment, batch_list, claim_id=claim_id, page=page)
    try:
        await itx.response.edit_message(content=f"**{cat_key}** — choose the exact achievement:", view=v)
        v.message = await itx.edit_original_response()
    except discord.InteractionResponded:
        m = await itx.followup.send(f"**{cat_key}** — choose the exact achievement:", view=v)
        v.message = m

# ---------------- Claim processing ----------------
async def finalize_grant(guild: discord.Guild, user_id: int, ach_key: str) -> bool:
    """
    Try to grant the achievement role.
    Returns True on success, False if anything prevents assignment.
    """
    ach = ACHIEVEMENTS.get(ach_key)
    if not ach:
        log.warning("[grant] unknown ach_key=%s", ach_key)
        await audit(guild, f"grant_fail: unknown_ach key=`{ach_key}` user=<@{user_id}>")
        return False

    role = _get_role_by_config(guild, ach)
    if not role:
        log.warning("[grant] role not found for ach_key=%s (role_id=%s, display_name=%s)",
                    ach_key, ach.get("role_id"), ach.get("display_name"))
        await audit(guild, f"grant_fail: role_not_found key=`{ach_key}` user=<@{user_id}>")
        return False

    member = guild.get_member(user_id) or await guild.fetch_member(user_id)

    me = guild.me
    if (not me.guild_permissions.manage_roles) or (role.position >= me.top_role.position):
        log.error("[grant] cannot assign role '%s' (%d). Check Manage Roles + role hierarchy (bot top role above).",
                  role.name, role.id)
        ch = guild.get_channel(CFG.get("audit_log_channel_id") or 0)
        if ch:
            await ch.send(
                f"⚠️ I can’t assign **{role.mention}** to {member.mention}. "
                f"Please move my top role above **{role.name}** and ensure I have **Manage Roles**."
            )
        await audit(guild, f"grant_fail: hierarchy_perm role=`{role.id}` user=<@{user_id}>")
        return False

    if role in member.roles:
        log.info("[grant] %s already has %s", member, role)
        await audit(guild, f"grant_skip: already_has role=`{role.id}` user=<@{user_id}>")
        return False

    try:
        await member.add_roles(role, reason=f"claim:{ach_key}")
    except Exception as e:
        log.error("[grant] add_roles failed for '%s' -> %s: %r", role.name, member, e)
        ch = guild.get_channel(CFG.get("audit_log_channel_id") or 0)
        if ch:
            await ch.send(
                f"⚠️ Tried to assign {role.mention} to {member.mention} but got "
                f"`{type(e).__name__}: {e}`. Check permissions/role hierarchy and try again."
            )
        await audit(guild, f"grant_fail: exception role=`{role.id}` user=<@{user_id}> type={type(e).__name__}")
        return False

    if CFG.get("audit_log_channel_id"):
        ch = guild.get_channel(CFG["audit_log_channel_id"])
        if ch:
            emb = discord.Embed(
                title="Achievement Claimed",
                description=f"**User:** {member.mention}\n**Role:** {role.mention}\n**Key:** `{ach_key}`",
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            try:
                await ch.send(embed=emb)
            except Exception:
                pass

    await audit(guild, f"grant_ok: role=`{role.id}` key=`{ach_key}` user=<@{user_id}>")
    _buffer_item(guild, user_id, role, ach)
    return True

async def process_claim(itx: discord.Interaction, ach_key: str,
                        att: Optional[discord.Attachment],
                        batch_list: Optional[List[discord.Attachment]],
                        claim_id: int):
    guild = itx.guild
    ach = ACHIEVEMENTS.get(ach_key)
    if not ach:
        log.warning("[claim] selection key missing from ACHIEVEMENTS: %s", ach_key)
        await itx.followup.send("That selection isn’t in my config. Try again or ping a Guardian Knight.", ephemeral=True)
        return

    role = _get_role_by_config(guild, ach)
    if not role:
        log.warning("[claim] role not configured for ach_key=%s (role_id=%s, display_name=%s)",
                    ach_key, ach.get("role_id"), ach.get("display_name"))
        await itx.followup.send("Role not configured for this achievement. Ping an admin.", ephemeral=True)
        return

    mode = (ach.get("mode") or "AUTO_GRANT").upper()

    async def _one(a: Optional[discord.Attachment]):
        if a:
            if not _is_image(a):
                await itx.channel.send(f"**Not processed for {itx.user.mention}.** Reason: wrong file type.")
                return
            if a.size and a.size > CFG["max_file_mb"] * 1024 * 1024:
                await itx.channel.send(f"**Not processed for {itx.user.mention}.** Reason: file too large.")
                return

        if mode == "AUTO_GRANT":
            try:
                member_roles = itx.user.roles
            except AttributeError:
                member = itx.guild.get_member(itx.user.id) or await itx.guild.fetch_member(itx.user.id)
                member_roles = member.roles

            if role in member_roles:
                await itx.channel.send(f"ℹ️ {itx.user.mention} already has **{role.name}**.")
                try:
                    await itx.message.edit(content=f"ℹ️ Already had **{role.name}**.", view=None)
                except Exception:
                    pass
                CLAIM_STATE[claim_id] = "closed"
                return

            ok = await finalize_grant(guild, itx.user.id, ach_key)
            if ok:
                try:
                    await itx.message.edit(content=f"✅ **{role.name}** granted to {itx.user.mention}.", view=None)
                except Exception as e:
                    log.warning("[auto_grant] edit failed: %r", e)
                await itx.channel.send(f"✨ **{role.name}** unlocked for {itx.user.mention}!")
                CLAIM_STATE[claim_id] = "closed"
            else:
                try:
                    await itx.message.edit(content=f"⚠️ Couldn’t grant **{role.name}**. A GK/Admin needs to adjust permissions.", view=None)
                except Exception:
                    pass
                await itx.channel.send(
                    f"⚠️ Couldn’t grant **{role.name}** to {itx.user.mention}. "
                    f"An admin may need to move my top role above that role or give me **Manage Roles**."
                )
                CLAIM_STATE[claim_id] = "closed"
            return

        # REVIEW MODE (GK)
        rid = CFG.get("guardian_knights_role_id")
        ping = f"<@&{rid}>" if rid else "**Guardian Knights**"
        emb = discord.Embed(
            title="Verification needed",
            description=f"{itx.user.mention} requested **{role.name}**",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.utcnow(),
        )
        thumb = resolve_hero_image(guild, role, ach)
        if thumb:
            emb.set_thumbnail(url=thumb)
        v = GKReview(itx.user.id, ach_key, a, claim_id=claim_id)
        await itx.channel.send(content=f"{ping}, please review.", embed=emb, view=v)
        await audit(guild, f"claim_routed_to_gk: key=`{ach_key}` user=<@{itx.user.id}>")

        # Lock the user's selector and show a clear “sent for review” note
        try:
            await itx.message.edit(content="🛡 Sent for **Guardian Knight** review — hang tight. You’ll be pinged after a decision.", view=None)
        except Exception as e:
            log.warning("[route_to_gk] user panel edit failed: %r", e)
        CLAIM_STATE[claim_id] = "closed"

    if batch_list:
        for a in batch_list:
            await _one(a)
    else:
        await _one(att)

# ---------------- staff guard ----------------
def _is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild:
        return True
    rid = CFG.get("guardian_knights_role_id")
    return bool(rid and any(r.id == rid for r in member.roles))

# ---------------- help ----------------
@bot.command(name="help")
async def help_cmd(ctx: commands.Context, *, topic: str = None):
    topic = (topic or "").strip().lower()

    # show overview if no topic given
    if not topic:
        return await ctx.reply(embed=_mk_help_embed_claims(ctx.guild), mention_author=False)

    pages = {
        "testconfig":     "`!testconfig`\nShow current configuration: targets, role ids, source & row counts.",
        "configstatus":   "`!configstatus`\nShort one-line status: source, loaded time, counts.",
        "reloadconfig":   "`!reloadconfig`\nReload configuration from Google Sheets or Excel.",
        "listach":        "`!listach [filter]`\nList loaded achievement keys (optionally filtered).",
        "findach":        "`!findach <text>`\nSearch achievements by key/name/category/text.",
        "testach":        "`!testach <key> [where]`\nPreview a single achievement embed (optionally to another channel).",
        "testlevel":      "`!testlevel [query] [where]`\nPreview a level-up embed (optionally to another channel).",
        "flushpraise":    "`!flushpraise`\nForce-post any buffered praise in this server.",
        "ping":           "`!ping`\nSimple liveness check.",
        "claim":          "Post your screenshot **in the configured claims thread**. I’ll guide you via buttons.",
        "claims":         "Same as `!help claim`.",
        "gk":             "Guardian Knights review claims that need verification. They can approve/deny or grant a different role.",
    }

    txt = pages.get(topic)
    if not txt:
        logging.getLogger("c1c-claims").warning("Unknown help topic requested: %s", topic)
        return

    e = discord.Embed(title=f"!help {topic}", description=txt, color=HELP_COLOR)
    e.set_footer(text=CFG.get("embed_footer_text", "C1C Achievements") or "C1C Achievements")
    await ctx.reply(embed=e, mention_author=False)

# ---------------- admin/test commands ----------------
@bot.command(name="testconfig")
async def testconfig(cmdx: commands.Context):
    if not _is_staff(cmdx.author):
        return await cmdx.send("Staff only.")

    thread_txt = await _fmt_chan_or_thread(cmdx.guild, CFG.get("public_claim_thread_id"))
    levels_txt = await _fmt_chan_or_thread(cmdx.guild, CFG.get("levels_channel_id"))
    audit_txt  = await _fmt_chan_or_thread(cmdx.guild, CFG.get("audit_log_channel_id"))
    gk_txt     = _fmt_role(cmdx.guild, CFG.get("guardian_knights_role_id"))
    loaded_at = CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if CONFIG_META["loaded_at"] else "—"

    emb = discord.Embed(title="Current configuration", color=discord.Color.blurple())
    if CFG.get("embed_author_name"):
        icon = _safe_icon(CFG.get("embed_author_icon"))
        if icon: emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
        else:    emb.set_author(name=CFG["embed_author_name"])
    emb.add_field(name="Claims thread", value=thread_txt, inline=False)
    emb.add_field(name="Levels channel", value=levels_txt, inline=False)
    emb.add_field(name="Audit-log channel", value=audit_txt, inline=False)
    emb.add_field(name="Guardian Knights role", value=gk_txt, inline=False)
    emb.add_field(name="Source", value=f"{CONFIG_META['source']} — {loaded_at}", inline=False)
    emb.add_field(
        name="Loaded rows",
        value=f"Achievements: **{len(ACHIEVEMENTS)}**\nCategories: **{len(CATEGORIES)}**\nLevels: **{len(LEVELS)}**",
        inline=False,
    )
    await safe_send_embed(cmdx, emb)

@bot.command(name="configstatus")
async def configstatus(ctx: commands.Context):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    loaded_at = CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if CONFIG_META["loaded_at"] else "—"
    await ctx.send(f"Source: **{CONFIG_META['source']}** | Loaded: **{loaded_at}** | Ach={len(ACHIEVEMENTS)} Cat={len(CATEGORIES)} Lvls={len(LEVELS)}")

@bot.command(name="reloadconfig")
async def reloadconfig(ctx: commands.Context):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    try:
        load_config()
        loaded_at = CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
        await ctx.send(f"🔁 Reloaded from **{CONFIG_META['source']}** at **{loaded_at}**. Ach={len(ACHIEVEMENTS)} Cat={len(CATEGORIES)} Lvls={len(LEVELS)}")
    except Exception as e:
        await ctx.send(f"Reload failed: `{e}`")

@bot.command(name="listach")
async def listach(ctx: commands.Context, filter_text: str = ""):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    keys = sorted(ACHIEVEMENTS.keys())
    if filter_text:
        f = filter_text.lower()
        keys = [k for k in keys if f in k.lower() or f in (ACHIEVEMENTS[k].get("display_name","").lower())]
    if not keys:
        return await ctx.send("No achievements match.")
    chunk = ", ".join(keys[:60])
    await ctx.send(f"**Loaded achievements ({len(keys)}):** {chunk}{' …' if len(keys) > 60 else ''}")

@bot.command(name="findach")
async def findach(ctx: commands.Context, *, text: str):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    t = text.lower()
    hits = []
    for k, r in ACHIEVEMENTS.items():
        hay = " ".join([(r.get("key","") or ""), (r.get("display_name","") or ""), (r.get("category","") or ""), (r.get("Title","") or ""), (r.get("Body","") or "")]).lower()
        if t in hay:
            hits.append(f"`{k}` — {r.get('display_name','')}")
    if not hits:
        return await ctx.send("No matches.")
    await ctx.send("\n".join(hits[:20]))

@bot.command(name="testach")
async def testach(ctx: commands.Context, key: str, where: Optional[str] = None):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    ach = ACHIEVEMENTS.get(key)
    if not ach:
        close = [k for k in ACHIEVEMENTS.keys() if key.lower() in k.lower()]
        hint = ", ".join(close[:10]) or "no similar keys"
        return await ctx.send(f"Unknown achievement key `{key}`. Try: {hint}")
    role = _get_role_by_config(ctx.guild, ach) or ctx.guild.default_role
    emb = build_achievement_embed(ctx.guild, ctx.author, role, ach)
    target = _resolve_target_channel(ctx, where)
    await safe_send_embed(target, emb)
    if target.id != ctx.channel.id:
        await ctx.reply(f"Preview sent to {target.mention}", mention_author=False)

@bot.command(name="testlevel")
async def testlevel(ctx: commands.Context, *, args: str = ""):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    parts = args.rsplit(" ", 1) if args else []
    query = parts[0] if parts else ""
    where = parts[1] if len(parts) == 2 else None
    row = None
    if query:
        q = query.lower()
        for r in LEVELS:
            hay = (r.get("level_key","") + " " + r.get("Title","") + " " + r.get("Body","")).lower()
            if q in hay:
                row = r; break
    row = row or (LEVELS[0] if LEVELS else None)
    if not row:
        return await ctx.send("No Levels rows loaded.")
    emb = build_level_embed(ctx.guild, ctx.author, row)
    target = _resolve_target_channel(ctx, where)
    await safe_send_embed(target, emb)
    if target.id != ctx.channel.id:
        await ctx.reply(f"Preview sent to {target.mention}", mention_author=False)

@bot.command(name="flushpraise")
async def flushpraise(ctx: commands.Context):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    g = GROUP.get(ctx.guild.id, {})
    if not g:
        return await ctx.send("Nothing to flush.")
    for uid in list(g.keys()):
        await _flush_group(ctx.guild, uid)
    await ctx.send("Flushed pending praise for this server.")

@bot.command(name="ping")
async def ping(ctx: commands.Context):
    # react-only liveness check
    try:
        await ctx.message.add_reaction("🏓")
    except Exception:
        pass

# ---------------- help (overview + subtopics, silent on unknown) ----------------
HELP_COLOR = discord.Color.blurple()

def _mk_help_embed_claims(guild: discord.Guild | None = None) -> discord.Embed:
    e = discord.Embed(
        title="🏆 C1C Appreciation & Claims — Help",
        color=HELP_COLOR,
        description=(
            "Post your screenshot **in the public claims thread** to start a claim. "
            "I’ll prompt you to pick a category and achievement; some claims auto-grant, "
            "others summon **Guardian Knights** for review.\n\n"
            "**Staff** can use the commands below for config and testing."
        )
    )
    e.add_field(
        name="How to claim (players)",
        value=(
            "1) Post a screenshot in the configured claims thread.\n"
            "2) Use the buttons to choose category ➜ achievement.\n"
            "3) If review is needed, GK will approve/deny or grant a different role."
        ),
        inline=False
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
            "• `!testlevel [query] [where]` — preview a level-up embed (optionally to another channel)\n"
            "• `!flushpraise` — force-post any buffered praise\n"
            "• `!ping` — bot alive check"
        ),
        inline=False
    )
    e.set_footer(text=CFG.get("embed_footer_text", "C1C Achievements") or "C1C Achievements")
    return e

# ---------------- error reporter ----------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # ignore silently
    try:
        await ctx.reply(f"⚠️ Command error: `{type(error).__name__}: {error}`")
    except:
        pass

# ---------------- message listeners ----------------
@bot.event
async def on_member_ban(guild, user):
    _touch_event()
    # defensive: clear any pending group flush for banned users
    GROUP.get(guild.id, {}).pop(getattr(user, "id", None), None)

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    _touch_event()
    """When a level role is added by any source, post the praise embed to #levels."""
    try:
        if not LEVELS:
            return
        levels_ch = after.guild.get_channel(CFG.get("levels_channel_id") or 0) if CFG.get("levels_channel_id") else None
        if not levels_ch:
            return

        before_ids = {r.id for r in before.roles}
        for role in after.roles:
            if role.id not in before_ids:
                row = _match_levels_row_by_role(role)
                if row:
                    emb = build_level_embed(after.guild, after, row)
                    await safe_send_embed(levels_ch, emb, ping_user=after)
    except Exception:
        log.exception("[levels] on_member_update failed")

@bot.event
async def on_message(msg: discord.Message):
    _touch_event()
    # Ignore ourselves and other bots for commands
    if msg.author.bot:
        return

    # --- run commands first, then exit if it looks like one ---
    try:
        prefixes = await bot.get_prefix(msg)
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        else:
            try:
                prefixes = list(prefixes)
            except TypeError:
                prefixes = [str(prefixes)]

        content = msg.content or ""
        if any(content.startswith(p) for p in prefixes):
            await bot.process_commands(msg)
            return
    except Exception:
        # fall back to processing anyway
        await bot.process_commands(msg)
        return
    # ----------------------------------------------------------

    # (Optional) still let non-command messages reach command parser (aliases etc.)
    await bot.process_commands(msg)

    # Level-up trigger watcher (leave as-is)
    try:
        m = re.search(r"has\s+reached\s+Level\s+(\d+)", msg.content or "", re.IGNORECASE)
        if m:
            level_num = int(m.group(1))
            user = msg.mentions[0] if msg.mentions else msg.author
            key = f"lvl_{level_num}"
            row = next((r for r in LEVELS if (r.get("key","").lower() == key)), None)
            if not row:
                def norm(s): return (s or "").strip().lower().replace(" ", "").replace("_", "")
                for r in LEVELS:
                    if norm(r.get("level_key")) == norm(key) or norm(r.get("display_name")) == norm(f"Level {level_num}"):
                        row = r
                        break

            if row:
                ch = msg.guild.get_channel(CFG.get("levels_channel_id") or 0) if CFG.get("levels_channel_id") else None
                if ch:
                    emb = build_level_embed(msg.guild, user, row)
                    await safe_send_embed(ch, emb, ping_user=user)
                    await audit(msg.guild, f"level_praise: matched {row.get('key','?')} for <@{user.id}> (src_msg={msg.id})")
                else:
                    await audit(msg.guild, f"level_praise_failed: no levels_channel for <@{user.id}> (src_msg={msg.id})")
    except Exception:
        log.exception("[levels] watcher failed")

    # Claims thread gating
    if not CFG.get("public_claim_thread_id") or msg.channel.id != CFG.get("public_claim_thread_id"):
        return
    images = [a for a in msg.attachments if _is_image(a)]
    if not images:
        return

    if len(images) == 1:
        view = CategoryPicker(msg.author.id, images[0], batch_list=None, claim_id=0, announce=True)
        m = await msg.reply(
            "**Claim your achievement**\nTap a category to continue. (Only you can use these buttons.)",
            view=view, mention_author=False)
        view.message = m
        view.claim_id = m.id
        CLAIM_STATE[m.id] = "open"
        await audit(msg.guild, f"claim_opened: user=<@{msg.author.id}> images=1 msg={msg.id}")
    else:
        view = MultiImageChoice(msg.author.id, images, claim_id=0, announce=True)
        m = await msg.reply(
            f"**I found {len(images)} screenshots.**\n"
            "Do you want multiple roles? If yes, upload **one screenshot per message** and claim each separately.\n"
            "Otherwise, proceed to claim **one role** for a single screenshot.",
            view=view, mention_author=False
        )
        view.message = m
        view.claim_id = m.id
        CLAIM_STATE[m.id] = "open"
        await audit(msg.guild, f"claim_opened: user=<@{msg.author.id}> images={len(images)} msg={msg.id}")

# ---------------- startup ----------------
async def _auto_refresh_loop(minutes: int):
    interval = max(1, minutes) * 60
    await CONFIG_READY.wait()
    while True:
        try:
            await asyncio.sleep(interval)
            load_config()
            log.info(f"Auto-refreshed config from {CONFIG_META['source']} at {CONFIG_META['loaded_at']}")
        except Exception:
            log.exception("Auto-refresh failed; keeping previous config")

@bot.event
async def on_connect():
    global BOT_CONNECTED
    BOT_CONNECTED = True
    _touch_event()
    log.info("[gateway] connected")


@bot.event
async def on_resumed():
    global BOT_CONNECTED
    BOT_CONNECTED = True
    _touch_event()
    log.info("[gateway] resumed session")


@bot.event
async def on_disconnect():
    global BOT_CONNECTED
    BOT_CONNECTED = False
    _touch_event()
    log.warning("[gateway] disconnected")


@bot.event
async def on_ready():
    global BOT_CONNECTED
    BOT_CONNECTED = True
    _touch_event()
    log.info(f"Logged in as {bot.user} ({bot.user.id})")
    global _INITIAL_CONFIG_TASK
    if CONFIG_READY.is_set() and CONFIG_META.get("status") == "ready":
        log.info("Configuration already loaded.")
    else:
        if _INITIAL_CONFIG_TASK is None or _INITIAL_CONFIG_TASK.done():
            _INITIAL_CONFIG_TASK = asyncio.create_task(_ensure_config_loaded(initial=True))
            log.info("Scheduled initial config load with backoff")
        else:
            log.info("Initial config load already scheduled (status=%s)", CONFIG_META.get("status"))

    mins = int(os.getenv("CONFIG_AUTO_REFRESH_MINUTES", "0") or "0")
    global _AUTO_REFRESH_TASK
    if mins > 0 and _AUTO_REFRESH_TASK is None:
        _AUTO_REFRESH_TASK = asyncio.create_task(_auto_refresh_loop(mins))
        log.info(f"Auto-refresh enabled: every {mins} minutes")
    try:
        prefix_cmds = sorted(c.name for c in bot.commands)
        slash_cmds  = sorted(c.name for c in bot.tree.get_commands())
        log.info(f"Registered prefix commands: {prefix_cmds}")
        log.info(f"Registered slash commands:  {slash_cmds}")
    except Exception:
        pass


async def _run_bot(token: str) -> None:
    base_delay = 5
    attempt = 0

    while True:
        try:
            await bot.login(token)
            attempt = 0
            await bot.connect(reconnect=True)
            log.info("Bot connection closed gracefully; exiting run loop")
            break
        except discord.LoginFailure as e:
            log.error("Login failed: %s", e)
            raise
        except ClientConnectorError as e:
            attempt += 1
            wait = min(600, base_delay * (2 ** (attempt - 1)))
            log.warning("[startup] Network connect error: %s — retrying in %ss", e, wait)
            await asyncio.sleep(wait)
        except discord.HTTPException as e:
            attempt += 1
            wait = min(600, base_delay * (2 ** (attempt - 1)))
            status = getattr(e, "status", None)
            message = str(e)
            if status in {429, 503} or "rate limited" in message.lower() or "banned" in message.lower():
                log.warning(
                    "[startup] Discord refused the connection (status=%s). Cooling down for %ss before retry.",
                    status,
                    wait,
                )
            else:
                log.exception("[startup] discord.HTTPException (status=%s)", status)
            await asyncio.sleep(wait)
        except Exception as e:
            attempt += 1
            wait = min(600, base_delay * (2 ** (attempt - 1)))
            log.exception("[startup] Unexpected exception: %s — retrying in %ss", e, wait)
            await asyncio.sleep(wait)
        finally:
            if not bot.is_closed():
                try:
                    await bot.close()
                except Exception:
                    pass


if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN")
    keep_alive()
    asyncio.run(_run_bot(token))
