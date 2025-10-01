# c1c_claims_appreciation.py
# C1C Appreciation + Claims Bot — v1.0
# Web Service (Flask keep-alive) + config loader + review flow

import os, re, json, asyncio, logging, threading
import datetime as dt
from typing import Optional, List, Dict, Tuple
from functools import partial
from urllib.parse import urlparse

import discord
from discord.ext import commands
from flask import Flask, jsonify

STRICT_PROBE=0                # keep Render happy: / and /ready always 200
WATCHDOG_CHECK_SEC=60
WATCHDOG_MAX_DISCONNECT_SEC=600

import time, sys
from discord.ext import tasks
from cogs.ops import OpsCog
from claims.help import build_help_overview_embed, build_help_subtopic_embed

# ⬇️ CoreOps prefix router (handles !sc …) — non-staff must use prefixes
from claims.middleware.coreops_prefix import CoreOpsPrefixCog, format_prefix_picker

# ---------------- keep-alive (Render web service) ----------------
app = Flask(__name__)

@app.get("/")
def _root_ok():
    return "ok", 200

@app.get("/ready")
def _ready_ok():
    try:
        latency_ms = int(getattr(bot, "latency", 0) * 1000)
    except Exception:
        latency_ms = None
    return jsonify({
        "bot_ready": getattr(bot, "is_ready", lambda: False)(),
        "latency_ms": latency_ms,
        "uptime": uptime_str(),
    }), 200

@app.get("/healthz")
def _deep_health():
    connected = BOT_CONNECTED
    age = _last_event_age_s()
    try:
        latency = float(bot.latency) if bot.latency is not None else None
    except Exception:
        latency = None

    status = 200 if connected else 503
    if connected and age is not None and age > 600 and (latency is None or latency > 10):
        status = 206  # “zombie-ish”

    body = {
        "ok": connected,
        "connected": connected,
        "uptime": uptime_str(),
        "last_event_age_s": age,
        "latency_s": latency,
        "strict_probe": STRICT_PROBE,
    }
    return jsonify(body), (status if STRICT_PROBE else 200)

def keep_alive():
    port = int(os.getenv("PORT", "10000"))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()

BOT_CONNECTED: bool = False
_LAST_READY_TS: float = 0.0
_LAST_DISCONNECT_TS: float = 0.0
_LAST_EVENT_TS: float = 0.0

def _now() -> float: return time.time()
def _mark_event() -> None:
    global _LAST_EVENT_TS
    _LAST_EVENT_TS = _now()
def _last_event_age_s() -> int | None:
    return int(_now() - _LAST_EVENT_TS) if _LAST_EVENT_TS else None

STRICT_PROBE = (os.getenv("STRICT_PROBE", "0") == "1")
WATCHDOG_CHECK_SEC = int(os.getenv("WATCHDOG_CHECK_SEC", "60"))
WATCHDOG_MAX_DISCONNECT_SEC = int(os.getenv("WATCHDOG_MAX_DISCONNECT_SEC", "600"))

START_TS = time.time()
def uptime_str():
    s = int(time.time() - START_TS); h, s = divmod(s,3600); m, s = divmod(s,60)
    return f"{h:02d}:{m:02d}:{s:02d}"

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
BOT_VERSION = "1.0"

# ---------------- discord client ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class ScribeBot(commands.Bot):
    async def setup_hook(self):
        # register cogs before ready; idempotent on hot restarts
        try:
            if not self.get_cog("OpsCog"):
                await self.add_cog(OpsCog(self))
                logging.getLogger("c1c-claims").info("OpsCog added in setup_hook")
            else:
                logging.getLogger("c1c-claims").info("OpsCog already present in setup_hook")
        except Exception:
            logging.getLogger("c1c-claims").exception("OpsCog setup failed")

        # CoreOps prefix router (so !sc … works here; non-staff must use prefixes)
        try:
            if not self.get_cog("CoreOpsPrefixCog"):
                await self.add_cog(CoreOpsPrefixCog(self))
                logging.getLogger("c1c-claims").info("CoreOpsPrefixCog added in setup_hook")
            else:
                logging.getLogger("c1c-claims").info("CoreOpsPrefixCog already present")
        except Exception:
            logging.getLogger("c1c-claims").exception("CoreOpsPrefixCog setup failed")

bot = ScribeBot(command_prefix="!", intents=intents)

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
    "embed_author_name": None,
    "embed_author_icon": None,
    "embed_footer_text": "C1C Achievements",
    "embed_footer_icon": None,
}
from typing import Dict  # for runtime-typed globals below
CATEGORIES: List[dict] = []
ACHIEVEMENTS: Dict[str, dict] = {}
LEVELS: List[dict] = []
REASONS: Dict[str, str] = {}
CONFIG_META = {"source": "—", "loaded_at": None}
_AUTO_REFRESH_TASK: Optional[asyncio.Task] = None

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
    return str(x or "").strip().lower() in ("true", "yes", "y", "1", "wahr")

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

def load_config():
    sid   = os.getenv("CONFIG_SHEET_ID", "").strip()
    local = os.getenv("LOCAL_CONFIG_XLSX", "").strip()
    global CFG, CATEGORIES, ACHIEVEMENTS, LEVELS, REASONS, CONFIG_META

    log.info(f"[boot] CONFIG_SHEET_ID set={bool(sid)} | LOCAL_CONFIG_XLSX set={bool(local)} | "
             f"gspread_loaded={gspread is not None} | pandas_loaded={pd is not None}")

    loaded = False
    source = "—"

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

            loaded = True
            source = "Google Sheets"
            log.info("Config loaded from Google Sheets")
        except Exception as e:
            log.warning(f"GSheet load failed: {e}", exc_info=True)

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

            loaded = True
            source = "Excel file"
            log.info("Config loaded from Excel")
        except Exception as e:
            log.error(f"Excel load failed: {e}", exc_info=True)

    if not loaded:
        raise RuntimeError("No config loaded. Set CONFIG_SHEET_ID (+SERVICE_ACCOUNT_JSON) or LOCAL_CONFIG_XLSX.")

    CONFIG_META["source"] = source
    CONFIG_META["loaded_at"] = dt.datetime.utcnow()

# ---------------- helpers ----------------
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
    for r in LEVELS:
        try:
            rid = int(r.get("role_id") or 0)
        except Exception:
            rid = 0
        if rid and rid == role.id:
            return r
    rname = role.name.strip().lower()
    for r in LEVELS:
        dn = (r.get("display_name") or "").strip().lower()
        lk = (r.get("level_key") or "").strip().lower()
        if dn and dn == rname:
            return r
        if lk and lk == rname:
            return r
    return None

# ---------------- embed builders ----------------
def build_achievement_embed(guild: discord.Guild, user: discord.Member, role: discord.Role, ach_row: dict) -> discord.Embed:
    cat = _category_by_key(ach_row.get("category") or "")
    emoji = resolve_emoji_text(guild, ach_row.get("EmojiNameOrId"), fallback=(cat or {}).get("emoji"))
    title  = _inject_tokens(_clean(ach_row.get("Title"))  or f"{role.name} unlocked!", user=user, role=role, emoji=emoji)
    body   = _inject_tokens(_clean(ach_row.get("Body"))   or f"{user.mention} just unlocked **{role.name}**.", user=user, role=role, emoji=emoji)
    footer = _inject_tokens(_clean(ach_row.get("Footer")) or "", user=user, role=role, emoji=emoji)
    color = _color_from_hex(ach_row.get("ColorHex")) or (role.color if getattr(role.color, "value", 0) else discord.Color.blurple())

    emb = discord.Embed(title=title, description=body, color=color, timestamp=dt.datetime.utcnow())

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
        emb.set_thumbnail(url=hero)
    return emb

def build_group_embed(guild: discord.Guild, user: discord.Member, items: List[Tuple[discord.Role, dict]]) -> discord.Embed:
    r0, a0 = items[0]
    color = _color_from_hex(a0.get("ColorHex")) or (r0.color if getattr(r0.color, "value", 0) else discord.Color.blurple())
    emb = discord.Embed(title=f"{user.display_name} unlocked {len(items)} achievements", color=color, timestamp=dt.datetime.utcnow())

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
        emb.set_thumbnail(url=hero)
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

    emb = discord.Embed(title=title, description=body, color=color, timestamp=dt.datetime.utcnow())

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
    if not levels_ch:
        log.warning("[praise] levels_channel_id not configured or not found; skipping praise. cfg=%s", CFG.get("levels_channel_id"))
        return
    items = entry["items"]
    user = guild.get_member(user_id) or await guild.fetch_member(user_id)
    if len(items) == 1:
        r, ach = items[0]
        await safe_send_embed(levels_ch, build_achievement_embed(guild, user, r, ach), ping_user=user)
    else:
        await safe_send_embed(levels_ch, build_group_embed(guild, user, items), ping_user=user)

def _buffer_item(guild: discord.Guild, user_id: int, role: discord.Role, ach: dict):
    g = GROUP.setdefault(guild.id, {})
    e = g.get(user_id)
    if not e:
        e = g[user_id] = {"items": [], "task": None}
    e["items"].append((role, ach))

    delay = max(0, int(CFG.get("group_window_seconds") or 0))
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

# ---------------- GK Review views ----------------
class TryAgainView(discord.ui.View):
    def __init__(self, owner_id: int, att: Optional[discord.Attachment], claim_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.att = att
        self.claim_id = claim_id

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.owner_id:
            await itx.response.send_message("This belongs to someone else. Upload your own screenshot to claim.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Try again", style=discord.ButtonStyle.primary)
    async def try_again(self, itx: discord.Interaction, _btn: discord.ui.Button):
        await show_category_picker(itx, self.att, claim_id=self.claim_id)

class GKReview(discord.ui.View):
    def __init__(self, claimant_id: int, ach_key: str, att: Optional[discord.Attachment], claim_id: int):
        super().__init__(timeout=1800)
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

    async def _only_claimant(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.claimant_id:
            await itx.response.send_message("Only the claimant can cancel this request.", ephemeral=True)
            return False
        return True

    def _disable_all(self):
        for c in self.children:
            c.disabled = True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx):
            return
        ach = ACHIEVEMENTS.get(self.ach_key) or {}
        role = _get_role_by_config(itx.guild, ach)
        member = itx.guild.get_member(self.claimant_id) or await itx.guild.fetch_member(self.claimant_id)
        if role and member and role in member.roles:
            try:
                await itx.response.edit_message(content="**Already has this role.** No action needed.", view=None)
            except Exception:
                pass
            return
        await itx.response.defer()
        ok = await finalize_grant(itx.guild, self.claimant_id, self.ach_key)
        try:
            if ok:
                await itx.message.edit(content="**Approved.**", view=None)
            else:
                await itx.message.edit(
                    content=("**Approval attempted but the role couldn’t be assigned.**\n"
                             "Please check my **Manage Roles** permission and ensure my **top role is above** the target role, then try again."),
                    view=None
                )
        except Exception:
            pass

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx):
            return
        reason = REASONS.get("NEED_BANNER", "Proof unclear. Please include the full result banner.")
        try:
            await itx.response.edit_message(
                content=f"**Not approved.** Reason: **{reason}**\nPost a clearer screenshot and hit **Try Again**.",
                view=TryAgainView(self.claimant_id, self.att, claim_id=self.claim_id)
            )
            if self.claim_id:
                CLAIM_STATE[self.claim_id] = "closed"
        except Exception:
            pass

    @discord.ui.button(label="Grant different role…", style=discord.ButtonStyle.secondary)
    async def grant_other(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx):
            return

        base = ACHIEVEMENTS.get(self.ach_key) or {}
        base_cat = base.get("category")
        achs = [a for a in ACHIEVEMENTS.values() if a.get("category") == base_cat and a.get("key") != self.ach_key]
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
            await sel_itx.response.defer()
            ok = await finalize_grant(sel_itx.guild, self.claimant_id, key)
            try:
                if ok:
                    await itx.message.edit(content="**Approved with different role.**", view=None)
                    await sel_itx.edit_original_response(content="✅ Granted.", view=None)
                else:
                    await itx.message.edit(
                        content=("**Attempted alternate grant, but the role couldn’t be assigned.**\n"
                                 "Please check my **Manage Roles** permission and ensure my **top role is above** the target role, then try again."),
                        view=None
                    )
                    await sel_itx.edit_original_response(content="⚠️ Couldn’t grant the selected role.", view=None)
            except Exception:
                pass

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
        if itx.user.id != self.owner_id:
            await itx.response.send_message("This claim belongs to someone else. Please upload your own screenshot.", ephemeral=True)
            return False
        return True

class MultiImageChoice(BaseView):
    def __init__(self, owner_id: int, atts: List[discord.Attachment], claim_id: int, announce: bool = False):
        super().__init__(owner_id, claim_id, announce=announce)
        self.atts = [a for a in atts if _is_image(a)]

    @discord.ui.button(label="Use first", style=discord.ButtonStyle.primary)
    async def use_first(self, itx: discord.Interaction, _btn: discord.ui.Button):
        await show_category_picker(itx, self.atts[0], claim_id=self.claim_id)

    @discord.ui.button(label="Choose image", style=discord.ButtonStyle.secondary)
    async def choose_image(self, itx: discord.Interaction, _btn: discord.ui.Button):
        view = ImageSelect(self.owner_id, self.atts, self.claim_id)
        await itx.response.edit_message(content="Pick one screenshot:", view=view)
        view.message = await itx.edit_original_response()

    @discord.ui.button(label="Use all", style=discord.ButtonStyle.success)
    async def use_all(self, itx: discord.Interaction, _btn: discord.ui.Button):
        await itx.response.edit_message(content=f"Apply one achievement to all **{len(self.atts)}** screenshots from this post. Pick the achievement once.", view=None)
        await show_category_picker(itx, None, batch_list=self.atts, claim_id=self.claim_id)

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
    PAGE_SIZE = 25

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

        prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=(self.page == 0))
        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=(start + self.PAGE_SIZE >= len(achs)))
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
    ach = ACHIEVEMENTS.get(ach_key)
    if not ach:
        log.warning("[grant] unknown ach_key=%s", ach_key)
        return False

    role = _get_role_by_config(guild, ach)
    if not role:
        log.warning("[grant] role not found for ach_key=%s (role_id=%s, display_name=%s)",
                    ach_key, ach.get("role_id"), ach.get("display_name"))
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
        return False

    if role in member.roles:
        log.info("[grant] %s already has %s", member, role)
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
        return False

    if CFG.get("audit_log_channel_id"):
        ch = guild.get_channel(CFG["audit_log_channel_id"])
        if ch:
            emb = discord.Embed(
                title="Achievement Claimed",
                description=f"**User:** {member.mention}\n**Role:** {role.mention}\n**Key:** `{ach_key}`",
                color=discord.Color.green(),
                timestamp=dt.datetime.utcnow()
            )
            await ch.send(embed=emb)

    _buffer_item(guild, user_id, role, ach)
    return True

async def process_claim(itx: discord.Interaction, ach_key: str,
                        att: Optional[discord.Attachment],
                        batch_list: Optional[List[discord.Attachment]],
                        claim_id: int):
    if claim_id:
        CLAIM_STATE[claim_id] = "closed"

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
                return

            ok = await finalize_grant(guild, itx.user.id, ach_key)
            if ok:
                await itx.channel.send(f"✨ **{role.name}** unlocked for {itx.user.mention}!")
            else:
                await itx.channel.send(
                    f"⚠️ Couldn’t grant **{role.name}** to {itx.user.mention}. "
                    f"An admin may need to move my top role above that role or give me **Manage Roles**."
                )
            return

        rid = CFG.get("guardian_knights_role_id")
        ping = f"<@&{rid}>" if rid else "**Guardian Knights**"
        emb = discord.Embed(
            title="Verification needed",
            description=f"{itx.user.mention} requested **{role.name}**",
            color=discord.Color.orange(),
            timestamp=dt.datetime.utcnow(),
        )
        thumb = resolve_hero_image(guild, role, ach)
        if thumb:
            emb.set_thumbnail(url=thumb)
        v = GKReview(itx.user.id, ach_key, a, claim_id=claim_id)
        await itx.channel.send(content=f"{ping}, please review.", embed=emb, view=v)

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
        await ctx.send(f"🔁 Reloaded from **{CONFIG_META['source']}** at **{loaded_at}**. Ach={len(ACHIEVEMENTS)} Cat={len(C
