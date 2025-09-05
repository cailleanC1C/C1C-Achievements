# C1C Appreciation + Claims Bot — Web Service (Flask keep-alive) + boot diagnostics
# ---------------------------------------------------------------------------------
# Config sources (choose ONE):
#   • Google Sheets (live):   CONFIG_SHEET_ID + SERVICE_ACCOUNT_JSON
#   • Local Excel fallback:   LOCAL_CONFIG_XLSX = /opt/render/project/src/C1C_Claims_Config_reminderStyle.xlsx
#
# Env:
#   DISCORD_BOT_TOKEN=...
#   CONFIG_SHEET_ID=...                # optional
#   SERVICE_ACCOUNT_JSON=...           # optional (inline JSON or path to JSON)
#   LOCAL_CONFIG_XLSX=/opt/render/project/src/C1C_Claims_Config_reminderStyle.xlsx   # optional
#   CONFIG_AUTO_REFRESH_MINUTES=0      # optional (0 disables; e.g., 15 to auto-refresh every 15 min)
#
# Deps (requirements.txt):
#   discord.py==2.3.2
#   Flask==3.0.3
#   pandas==2.2.2
#   openpyxl==3.1.5
#   gspread==6.1.2
#   google-auth==2.31.0
#
# Commands:
#   !ping
#   !testconfig         (pretty names + mentions + IDs)
#   !configstatus       (source + last loaded)
#   !reloadconfig       (re-fetch from sheet/xlsx)
#   !listach [filter]   (show loaded achievement keys)
#   !findach <text>     (search achievement rows)
#   !testach <key> [here|#channel|channel_id]
#   !testlevel <query> [here|#channel|channel_id]
#
# Flow:
#   Proof thread → [Use first / Choose image / Use all / Cancel] → Category → Role → AUTO_GRANT or GK review
#   Big role icon pulled from the Discord role's icon, embeds use Title/Body/Footer from sheet, tokens {user}/{role}/{emoji}

import os, re, json, asyncio, logging, datetime, threading, traceback
from typing import Optional, List, Dict, Tuple
from functools import partial

import discord
from discord.ext import commands

# ---------- tiny keep-alive web server for Render Web Service ----------
from flask import Flask
app = Flask(__name__)

@app.route("/")
def health():
    return "ok", 200

def keep_alive():
    port = int(os.getenv("PORT", "10000"))  # Render provides $PORT
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port),
        daemon=True
    ).start()

# ---------- optional libs for config loading ----------
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None

try:
    import pandas as pd
except Exception:
    pd = None

log = logging.getLogger("c1c-claims")
logging.basicConfig(level=logging.INFO)

# ---------- discord client ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- runtime config ----------
CFG = {
    "public_claim_thread_id": None,
    "levels_channel_id": None,
    "audit_log_channel_id": None,
    "guardian_knights_role_id": None,
    "group_window_seconds": 60,
    "max_file_mb": 8,
    "allowed_mimes": {"image/png", "image/jpeg"},
    "locale": "en",
    "hud_language": "EN",
    "embed_author_name": "The Scribe That Knows Too Much",
    "embed_author_icon": None,
    "embed_footer_text": "C1C Achievements",
    "embed_footer_icon": None,
}

CATEGORIES: List[dict] = []
ACHIEVEMENTS: Dict[str, dict] = {}
LEVELS: List[dict] = []
REASONS: Dict[str, str] = {}

# meta about current config load
CONFIG_META = {"source": "—", "loaded_at": None}
_AUTO_REFRESH_TASK: Optional[asyncio.Task] = None

# ---------- config loading ----------
def _svc_creds():
    raw = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    data = json.loads(raw) if raw.startswith("{") else json.load(open(raw, "r", encoding="utf-8"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    return Credentials.from_service_account_info(data, scopes=scopes)

def _truthy(x) -> bool:
    if isinstance(x, bool): return x
    s = str(x or "").strip().lower()
    return s in ("true", "yes", "y", "1", "wahr")

def _set_or_default(d: dict, key: str, default):
    val = d.get(key, default)
    if key == "allowed_mimes" and isinstance(val, str):
        return set(x.strip() for x in val.split(",") if x.strip())
    return val if val not in (None, "") else default

def _to_str(x) -> str:
    """Coerce any cell value to a clean string (handles ints/floats from Excel/Sheets)."""
    if x is None:
        return ""
    if isinstance(x, float):
        return str(int(x)) if x.is_integer() else str(x)
    if isinstance(x, int):
        return str(x)
    return str(x)

def _color_from_hex(hex_str: Optional[str]) -> Optional[discord.Color]:
    """Be tolerant: accept '#14532D', '14532D', or even numeric cells."""
    if hex_str in (None, ""):
        return None
    try:
        s = _to_str(hex_str).strip().lstrip("#")
        return discord.Color(int(s, 16))
    except Exception:
        return None

def load_config():
    """Try Google Sheets first, then local Excel. Logs strong diagnostics for each step."""
    sid   = os.getenv("CONFIG_SHEET_ID", "").strip()
    local = os.getenv("LOCAL_CONFIG_XLSX", "").strip()
    global CFG, CATEGORIES, ACHIEVEMENTS, LEVELS, REASONS, CONFIG_META

    # BOOT DIAGNOSTIC
    log.info(f"[boot] CONFIG_SHEET_ID set={bool(sid)} | LOCAL_CONFIG_XLSX set={bool(local)} | "
             f"gspread_loaded={gspread is not None} | pandas_loaded={pd is not None}")

    loaded = False
    source = "—"

    # ---- Google Sheets ----
    if sid and gspread:
        try:
            creds = _svc_creds()
            if not creds:
                raise RuntimeError("SERVICE_ACCOUNT_JSON missing/invalid for Google Sheets")
            gc = gspread.authorize(creds)
            sh = gc.open_by_key(sid)
            log.info("[boot] Opening Google Sheet succeeded")

            row = sh.worksheet("General").get_all_records()[0]
            CFG.update({
                "public_claim_thread_id": int(row.get("public_claim_thread_id") or 0) or None,
                "levels_channel_id": int(row.get("levels_channel_id") or 0) or None,
                "audit_log_channel_id": int(row.get("audit_log_channel_id") or 0) or None,
                "guardian_knights_role_id": int(row.get("guardian_knights_role_id") or 0) or None,
                "group_window_seconds": int(row.get("group_window_seconds") or 60),
                "max_file_mb": int(row.get("max_file_mb") or 8),
                "allowed_mimes": _set_or_default(row, "allowed_mimes", {"image/png","image/jpeg"}),
                "locale": row.get("locale") or "en",
                "hud_language": row.get("hud_language") or "EN",
                "embed_author_name": row.get("embed_author_name") or CFG["embed_author_name"],
                "embed_author_icon": row.get("embed_author_icon") or None,
                "embed_footer_text": row.get("embed_footer_text") or CFG["embed_footer_text"],
                "embed_footer_icon": row.get("embed_footer_icon") or None,
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

    # ---- Local Excel ----
    if not loaded and local and pd:
        try:
            if not os.path.isabs(local):
                # make it absolute relative to the project src on Render
                local = os.path.join("/opt/render/project/src", local)
            log.info(f"[boot] Attempting Excel load from: {local}")
            xl = pd.ExcelFile(local)
            gen = pd.read_excel(xl, "General").to_dict("records")[0]
            CFG.update({
                "public_claim_thread_id": int(gen.get("public_claim_thread_id") or 0) or None,
                "levels_channel_id": int(gen.get("levels_channel_id") or 0) or None,
                "audit_log_channel_id": int(gen.get("audit_log_channel_id") or 0) or None,
                "guardian_knights_role_id": int(gen.get("guardian_knights_role_id") or 0) or None,
                "group_window_seconds": int(gen.get("group_window_seconds") or 60),
                "max_file_mb": int(gen.get("max_file_mb") or 8),
                "allowed_mimes": _set_or_default(gen, "allowed_mimes", {"image/png","image/jpeg"}),
                "locale": gen.get("locale") or "en",
                "hud_language": gen.get("hud_language") or "EN",
                "embed_author_name": gen.get("embed_author_name") or CFG["embed_author_name"],
                "embed_author_icon": gen.get("embed_author_icon") or None,
                "embed_footer_text": gen.get("embed_footer_text") or CFG["embed_footer_text"],
                "embed_footer_icon": gen.get("embed_footer_icon") or None,
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
    CONFIG_META["loaded_at"] = datetime.datetime.utcnow()

# ---------- helpers ----------
def _is_image(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower()
    if ct in CFG["allowed_mimes"]:
        return True
    fn = att.filename.lower()
    return fn.endswith(".png") or fn.endswith(".jpg") or fn.endswith(".jpeg")

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
    """
    Accepts unicode emoji, <:name:id>, numeric id, or a name.
    Works even if the sheet gives us numbers (int/float).
    """
    v = _to_str(value).strip()
    if not v:
        v = _to_str(fallback).strip()
    if not v:
        return ""

    # Already a proper <...:id> tag
    if EMOJI_TAG_RE.match(v):
        return v

    # Pure numeric: treat as a custom emoji ID
    if v.isdigit():
        e = discord.utils.get(guild.emojis, id=int(v))
        return f"<{'a' if e.animated else ''}:{e.name}:{e.id}>" if e else ""

    # Otherwise, try by name; if not found, assume it's unicode and return as-is
    e = discord.utils.get(guild.emojis, name=v)
    return f"<{'a' if e.animated else ''}:{e.name}:{e.id}>" if e else v

def _inject_tokens(text: str, *, user: discord.Member, role: discord.Role, emoji: str) -> str:
    return (text or "").replace("{user}", user.mention).replace("{role}", role.name).replace("{emoji}", emoji)

# --- safe embed sender + channel resolver for "here/#channel/id" ---
async def safe_send_embed(dest, embed: discord.Embed):
    try:
        return await dest.send(embed=embed)
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
        if ch:
            return ch
    return ctx.channel

# --- pretty-format IDs to names/mentions for !testconfig / !configstatus ---
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

# ---------- embed builders ----------
def build_achievement_embed(guild: discord.Guild, user: discord.Member, role: discord.Role, ach_row: dict) -> discord.Embed:
    cat = _category_by_key(ach_row.get("category") or "")
    emoji = resolve_emoji_text(guild, ach_row.get("EmojiNameOrId"), fallback=(cat or {}).get("emoji"))
    title = _inject_tokens(ach_row.get("Title") or f"{role.name} unlocked!", user=user, role=role, emoji=emoji)
    body  = _inject_tokens(ach_row.get("Body")  or f"{user.mention} just unlocked **{role.name}**.", user=user, role=role, emoji=emoji)
    footer= _inject_tokens(ach_row.get("Footer") or "", user=user, role=role, emoji=emoji)
    color = _color_from_hex(ach_row.get("ColorHex")) or (role.color if getattr(role.color, "value", 0) else discord.Color.blurple())

    emb = discord.Embed(title=title, description=body, color=color, timestamp=datetime.datetime.utcnow())

    if CFG.get("embed_author_name"):
        icon = CFG.get("embed_author_icon")
        if icon:
            emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
        else:
            emb.set_author(name=CFG["embed_author_name"])

    footer_text = footer or CFG.get("embed_footer_text")
    if footer_text:
        icon = CFG.get("embed_footer_icon")
        if icon:
            emb.set_footer(text=footer_text, icon_url=icon)
        else:
            emb.set_footer(text=footer_text)

    hero = _big_role_icon_url(role)
    if hero:
        emb.set_image(url=hero)
    return emb


def build_group_embed(guild: discord.Guild, user: discord.Member, items: List[Tuple[discord.Role, dict]]) -> discord.Embed:
    r0, a0 = items[0]
    color = _color_from_hex(a0.get("ColorHex")) or (r0.color if getattr(r0.color, "value", 0) else discord.Color.blurple())
    emb = discord.Embed(title=f"{user.display_name} unlocked {len(items)} achievements", color=color, timestamp=datetime.datetime.utcnow())

    if CFG.get("embed_author_name"):
        icon = CFG.get("embed_author_icon")
        if icon:
            emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
        else:
            emb.set_author(name=CFG["embed_author_name"])

    lines = []
    for r, a in items:
        cat = _category_by_key(a.get("category") or "")
        emoji = resolve_emoji_text(guild, a.get("EmojiNameOrId"), fallback=(cat or {}).get("emoji"))
        body = _inject_tokens(a.get("Body") or f"{user.mention} just unlocked **{r.name}**.", user=user, role=r, emoji=emoji)
        lines.append(f"• {body}")
    emb.description = "\n".join(lines)

    hero = _big_role_icon_url(r0)
    if hero:
        emb.set_image(url=hero)

    footer_text = CFG.get("embed_footer_text")
    if footer_text:
        icon = CFG.get("embed_footer_icon")
        if icon:
            emb.set_footer(text=footer_text, icon_url=icon)
        else:
            emb.set_footer(text=footer_text)
    return emb


def build_level_embed(guild: discord.Guild, user: discord.Member, row: dict) -> discord.Embed:
    emoji = resolve_emoji_text(guild, row.get("EmojiNameOrId"))
    role_for_tokens = user.top_role if user.top_role else user.guild.default_role
    title = _inject_tokens(row.get("Title") or "Level up!", user=user, role=role_for_tokens, emoji=emoji)
    body  = _inject_tokens(row.get("Body")  or "{user} leveled up!", user=user, role=role_for_tokens, emoji=emoji)
    footer= _inject_tokens(row.get("Footer") or "", user=user, role=role_for_tokens, emoji=emoji)
    color = _color_from_hex(row.get("ColorHex")) or discord.Color.gold()

    emb = discord.Embed(title=title, description=body, color=color, timestamp=datetime.datetime.utcnow())

    if CFG.get("embed_author_name"):
        icon = CFG.get("embed_author_icon")
        if icon:
            emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
        else:
            emb.set_author(name=CFG["embed_author_name"])

    footer_text = footer or CFG.get("embed_footer_text")
    if footer_text:
        icon = CFG.get("embed_footer_icon")
        if icon:
            emb.set_footer(text=footer_text, icon_url=icon)
        else:
            emb.set_footer(text=footer_text)
    return emb


# ---------- grouping buffer ----------
GROUP: Dict[int, Dict[int, dict]] = {}

async def _flush_group(guild: discord.Guild, user_id: int):
    entry = GROUP.get(guild.id, {}).pop(user_id, None)
    if not entry: return
    levels_ch = guild.get_channel(CFG["levels_channel_id"]) if CFG["levels_channel_id"] else None
    if not levels_ch:
        log.warning("levels_channel_id not configured")
        return
    items = entry["items"]
    user = guild.get_member(user_id) or await guild.fetch_member(user_id)
    if len(items) == 1:
        r, ach = items[0]
        await levels_ch.send(embed=build_achievement_embed(guild, user, r, ach))
    else:
        await levels_ch.send(embed=build_group_embed(guild, user, items))

def _buffer_item(guild: discord.Guild, user_id: int, role: discord.Role, ach: dict):
    g = GROUP.setdefault(guild.id, {})
    e = g.get(user_id)
    if not e:
        e = g[user_id] = {"items": [], "task": None}
    e["items"].append((role, ach))
    if e["task"]:
        e["task"].cancel()
    async def _delay():
        try:
            await asyncio.sleep(CFG["group_window_seconds"])
            await _flush_group(guild, user_id)
        except asyncio.CancelledError:
            pass
    e["task"] = asyncio.create_task(_delay())

# ---------- GK Review views ----------
class TryAgainView(discord.ui.View):
    def __init__(self, owner_id: int, att: Optional[discord.Attachment]):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.att = att

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.owner_id:
            await itx.response.send_message("This belongs to someone else. Upload your own screenshot to claim.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Try again", style=discord.ButtonStyle.primary)
    async def try_again(self, itx: discord.Interaction, _btn: discord.ui.Button):
        await show_category_picker(itx, self.att)

class GKReview(discord.ui.View):
    def __init__(self, claimant_id: int, ach_key: str, att: Optional[discord.Attachment]):
        super().__init__(timeout=1800)
        self.claimant_id = claimant_id
        self.ach_key = ach_key
        self.att = att

    async def _only_gk(self, itx: discord.Interaction) -> bool:
        rid = CFG.get("guardian_knights_role_id")
        mem = itx.guild.get_member(itx.user.id)
        if not rid or not mem or not any(r.id == rid for r in mem.roles):
            await itx.response.send_message("Guardian Knights only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx): return
        await itx.response.defer()
        await finalize_grant(itx.guild, self.claimant_id, self.ach_key)
        await itx.message.edit(content="**Approved.**", view=None)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx): return
        reason = REASONS.get("NEED_BANNER", "Proof unclear. Please include the full result banner.")
        await itx.message.edit(content=f"**Not approved.** Reason: **{reason}**\nPost a clearer screenshot and hit **Try Again**.", view=TryAgainView(self.claimant_id, self.att))

    @discord.ui.button(label="Grant different role…", style=discord.ButtonStyle.secondary)
    async def grant_other(self, itx: discord.Interaction, _btn: discord.ui.Button):
        if not await self._only_gk(itx): return
        opts = [discord.SelectOption(label=a["display_name"], value=a["key"]) for a in ACHIEVEMENTS.values()]
        v = discord.ui.View(timeout=600)
        sel = discord.ui.Select(placeholder="Pick a role to grant instead…", options=opts)
        async def _on_pick(sel_itx: discord.Interaction):
            if not await self._only_gk(sel_itx): return
            key = sel_itx.data["values"][0]
            await sel_itx.response.defer()
            await finalize_grant(sel_itx.guild, self.claimant_id, key)
            await itx.message.edit(content="**Approved with different role.**", view=None)
        sel.callback = _on_pick
        v.add_item(sel)
        await itx.response.send_message("Choose replacement role:", view=v, ephemeral=True)

# ---------- Pickers ----------
class BaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout=600):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def on_timeout(self):
        try:
            await self.message.channel.send(f"**Claim expired for <@{self.owner_id}>.** No action needed.")
        except Exception:
            pass

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.owner_id:
            await itx.response.send_message("This claim belongs to someone else. Please upload your own screenshot.", ephemeral=True)
            return False
        return True

class MultiImageChoice(BaseView):
    def __init__(self, owner_id: int, atts: List[discord.Attachment]):
        super().__init__(owner_id)
        self.atts = [a for a in atts if _is_image(a)]

    @discord.ui.button(label="Use first", style=discord.ButtonStyle.primary)
    async def use_first(self, itx: discord.Interaction, _btn: discord.ui.Button):
        await show_category_picker(itx, self.atts[0])

    @discord.ui.button(label="Choose image", style=discord.ButtonStyle.secondary)
    async def choose_image(self, itx: discord.Interaction, _btn: discord.ui.Button):
        view = ImageSelect(self.owner_id, self.atts)
        await itx.response.edit_message(content="Pick one screenshot:", view=view)
        view.message = await itx.edit_original_response()

    @discord.ui.button(label="Use all", style=discord.ButtonStyle.success)
    async def use_all(self, itx: discord.Interaction, _btn: discord.ui.Button):
        await itx.response.edit_message(content=f"Apply one achievement to all **{len(self.atts)}** screenshots from this post. Pick the achievement once.", view=None)
        await show_category_picker(itx, None, batch_list=self.atts)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, itx: discord.Interaction, _btn: discord.ui.Button):
        try:
            await itx.message.delete()
        except Exception:
            pass
        await itx.channel.send(f"**Claim canceled by {itx.user.mention}.** No action needed.")

class ImageSelect(BaseView):
    def __init__(self, owner_id: int, atts: List[discord.Attachment]):
        super().__init__(owner_id)
        self.atts = atts
        opts = [discord.SelectOption(label=f"#{i} – {a.filename}", value=str(i-1)) for i,a in enumerate(atts, start=1)]
        sel = discord.ui.Select(placeholder="Choose a screenshot…", options=opts)
        sel.callback = self._on_pick
        self.add_item(sel)

    async def _on_pick(self, itx: discord.Interaction):
        idx = int(itx.data["values"][0])
        await show_category_picker(itx, self.atts[idx])

class CategoryPicker(BaseView):
    def __init__(self, owner_id: int, att: Optional[discord.Attachment], batch_list: Optional[List[discord.Attachment]]=None):
        super().__init__(owner_id)
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
        await itx.channel.send(f"**Claim canceled by {itx.user.mention}.** No action needed.")

    async def _pick_cat(self, itx: discord.Interaction, cat_key: str):
        await show_role_picker(itx, cat_key, self.att, self.batch)

class RolePicker(BaseView):
    def __init__(self, owner_id: int, cat_key: str, att: Optional[discord.Attachment], batch_list: Optional[List[discord.Attachment]]):
        super().__init__(owner_id)
        self.cat_key = cat_key
        self.att = att
        self.batch = batch_list
        achs = [a for a in ACHIEVEMENTS.values() if a.get("category")==cat_key]
        opts = [discord.SelectOption(label=a["display_name"], value=a["key"]) for a in achs]
        sel = discord.ui.Select(placeholder="Choose the exact achievement…", options=opts)
        sel.callback = self._on_pick
        self.add_item(sel)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        back.callback = self._back
        self.add_item(back)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _back(self, itx: discord.Interaction):
        await show_category_picker(itx, self.att, self.batch)

    async def _cancel(self, itx: discord.Interaction):
        try: await itx.message.delete()
        except Exception: pass
        await itx.channel.send(f"**Claim canceled by {itx.user.mention}.** No action needed.")

    async def _on_pick(self, itx: discord.Interaction):
        await itx.response.defer()
        key = itx.data["values"][0]
        await process_claim(itx, key, self.att, self.batch)

# ---------- Flow helpers ----------
async def show_category_picker(itx: discord.Interaction, attachment: Optional[discord.Attachment], batch_list: Optional[List[discord.Attachment]] = None):
    v = CategoryPicker(itx.user.id, attachment, batch_list=batch_list)
    try:
        await itx.response.edit_message(content="**Claim your achievement** — tap a category:", view=v)
        v.message = await itx.edit_original_response()
    except discord.InteractionResponded:
        m = await itx.followup.send("**Claim your achievement** — tap a category:", view=v)
        v.message = m

async def show_role_picker(itx: discord.Interaction, cat_key: str, attachment: Optional[discord.Attachment], batch_list: Optional[List[discord.Attachment]] = None):
    v = RolePicker(itx.user.id, cat_key, attachment, batch_list)
    try:
        await itx.response.edit_message(content=f"**{cat_key}** — choose the exact achievement:", view=v)
        v.message = await itx.edit_original_response()
    except discord.InteractionResponded:
        m = await itx.followup.send(f"**{cat_key}** — choose the exact achievement:", view=v)
        v.message = m

# ---------- Claim processing ----------
async def finalize_grant(guild: discord.Guild, user_id: int, ach_key: str):
    ach = ACHIEVEMENTS.get(ach_key)
    if not ach: return
    role = _get_role_by_config(guild, ach)
    if not role: return
    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    if role in member.roles: return
    await member.add_roles(role, reason=f"claim:{ach_key}")

    if CFG.get("audit_log_channel_id"):
        ch = guild.get_channel(CFG["audit_log_channel_id"])
        if ch:
            emb = discord.Embed(
                title="Achievement Claimed",
                description=f"**User:** {member.mention}\n**Role:** {role.mention}\n**Key:** `{ach_key}`",
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            await ch.send(embed=emb)

    _buffer_item(guild, user_id, role, ach)

async def process_claim(itx: discord.Interaction, ach_key: str, att: Optional[discord.Attachment], batch_list: Optional[List[discord.Attachment]]):
    guild = itx.guild
    ach = ACHIEVEMENTS.get(ach_key)
    if not ach:
        await itx.followup.send("Unknown achievement.", ephemeral=True)
        return
    role = _get_role_by_config(guild, ach)
    if not role:
        await itx.followup.send("Role not configured. Ping an admin.", ephemeral=True)
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
            await finalize_grant(guild, itx.user.id, ach_key)
            await itx.channel.send(f"✨ **{role.name}** unlocked for {itx.user.mention}!")
            return

        # MOD_APPROVE / OCR → GK review
        rid = CFG.get("guardian_knights_role_id")
        ping = f"<@&{rid}>" if rid else "**Guardian Knights**"
        emb = discord.Embed(
            title="Verification needed",
            description=f"{itx.user.mention} requested **{role.name}**",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.utcnow(),
        )
        thumb = _big_role_icon_url(role)
        if thumb: emb.set_thumbnail(url=thumb)
        v = GKReview(itx.user.id, ach_key, a)
        await itx.channel.send(content=f"{ping}, please review.", embed=emb, view=v)

    if batch_list:
        for a in batch_list:
            await _one(a)
    else:
        await _one(att)

# ---------- staff guard ----------
def _is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild:
        return True
    rid = CFG.get("guardian_knights_role_id")
    return bool(rid and any(r.id == rid for r in member.roles))

# ---------- test/admin commands ----------
@bot.command(name="testconfig")
async def testconfig(ctx: commands.Context):
    if not _is_staff(ctx.author):
        return await ctx.send("Staff only.")
    thread_txt = await _fmt_chan_or_thread(ctx.guild, CFG.get("public_claim_thread_id"))
    levels_txt = await _fmt_chan_or_thread(ctx.guild, CFG.get("levels_channel_id"))
    audit_txt  = await _fmt_chan_or_thread(ctx.guild, CFG.get("audit_log_channel_id"))
    gk_txt     = _fmt_role(ctx.guild, CFG.get("guardian_knights_role_id"))
    loaded_at = CONFIG_META["loaded_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if CONFIG_META["loaded_at"] else "—"
    emb = discord.Embed(title="Current configuration", color=discord.Color.blurple())
if CFG.get("embed_author_name"):
    icon = CFG.get("embed_author_icon")
    if icon:
        emb.set_author(name=CFG["embed_author_name"], icon_url=icon)
    else:
        emb.set_author(name=CFG["embed_author_name"])
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
    await safe_send_embed(ctx, emb)

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

@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.send("✅ Live and listening.")

# ---------- command error reporter (so failures aren’t silent) ----------
@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandNotFound):
        return
    try:
        await ctx.send(f"⚠️ **{type(error).__name__}**: `{error}`")
    except Exception:
        pass
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    log.error("Command error:\n%s", tb)

# ---------- message listener (levels & claims) ----------
@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return
    await bot.process_commands(msg)

    # Level triggers by substring
    try:
        for row in LEVELS:
            trig = row.get("trigger_contains") or row.get("Title") or ""
            if trig and trig in msg.content:
                user = msg.mentions[0] if msg.mentions else msg.author
                ch = msg.guild.get_channel(CFG["levels_channel_id"]) if CFG["levels_channel_id"] else None
                if ch:
                    await ch.send(embed=build_level_embed(msg.guild, user, row))
                break
    except Exception:
        pass

    # Claims only in the configured thread
    if not CFG.get("public_claim_thread_id") or msg.channel.id != CFG.get("public_claim_thread_id"):
        return
    images = [a for a in msg.attachments if _is_image(a)]
    if not images:
        return
    if len(images) == 1:
        view = CategoryPicker(msg.author.id, images[0])
        m = await msg.reply("**Claim your achievement**\nTap a category to continue. (Only you can use these buttons.)", view=view, mention_author=False)
        view.message = m
    else:
        view = MultiImageChoice(msg.author.id, images)
        m = await msg.reply(f"**I found {len(images)} screenshots. What do you want to do?**", view=view, mention_author=False)
        view.message = m

# ---------- startup & optional auto-refresh ----------
async def _auto_refresh_loop(minutes: int):
    while True:
        try:
            await asyncio.sleep(minutes * 60)
            load_config()
            log.info(f"Auto-refreshed config from {CONFIG_META['source']} at {CONFIG_META['loaded_at']}")
        except Exception:
            log.exception("Auto-refresh failed")

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} ({bot.user.id})")
    try:
        load_config()
        log.info("Configuration loaded.")
    except Exception as e:
        log.error(f"Config error: {e}")
        await bot.close()
        return

    # start background auto-refresh if enabled
    global _AUTO_REFRESH_TASK
    mins = int(os.getenv("CONFIG_AUTO_REFRESH_MINUTES", "0") or "0")
    if mins > 0 and _AUTO_REFRESH_TASK is None:
        _AUTO_REFRESH_TASK = asyncio.create_task(_auto_refresh_loop(mins))
        log.info(f"Auto-refresh enabled: every {mins} minutes")

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN")
    keep_alive()  # keep the Web Service alive on Render
    bot.run(token)
