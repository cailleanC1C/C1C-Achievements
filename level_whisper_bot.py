import os
import re
import logging
import asyncio
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands

# --------------------------
# Logging (so Render shows errors)
# --------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("c1c-appreciation-bot")

# --------------------------
# Keep-alive tiny web server (Render uses $PORT)
# --------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "I'm alive!"

def _run_flask():
    port = int(os.getenv("PORT", "10000"))  # Render provides PORT
    log.info(f"Flask keep-alive starting on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=_run_flask, daemon=True).start()

# -------------
# Discord setup
# -------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------------------------------------------
# CONFIG (channels + grouping)
# ------------------------------------------------------------
AUDIT_LOG_CHANNEL_NAME = "audit-log"   # source of role logs
LEVELS_CHANNEL_NAME    = "levels"      # target for appreciation
GROUP_WINDOW_SECONDS   = 60            # group for 60s

# ------------------------------------------------------------
# CONFIG (clusters)
# ------------------------------------------------------------
CLUSTERS = {
    "hydra": {"roles": {"Hydra Normal", "Hydra Hard", "Hydra Brutal", "Hydra NM"}},
    "chimera": {"roles": {"Chimera Normal", "Chimera Hard", "Chimera NM", "Chimera UNM"}},
    "doomtower": {"roles": {"Doomtower Normal", "Doomtower Hard"}},
    "cursed_city": {"roles": {"101 Stages cleared Sintranos Normal", "101 Stages cleared Sintranos Hard"}},
    "amius": {"roles": {"Amius Normal", "Amius Hard"}},
    "cb_keys": {"roles": {"1 Key NM", "1 Key UNM", "2 Key UNM"}},
    "arena": {"roles": {"Platinum Arena"}},
    "faction_wars": {"roles": {"Faction Wars"}},
}

# Special champions fire immediately (never grouped)
SPECIAL_CHAMPIONS = {
    "The Angel": """Arbiter’s questline finally closed — campaign clears, dungeons farmed, and every stubborn step ticked off. That road is long and brutal, and finishing it deserves nothing less than a proper toast. 🥂✨""",
    "The Dragonborn": """Ramantu’s questline is no small grind — endless missions, high hurdles, and all the patience in the world. That’s endgame grit shining through, and a milestone worth loud applause. 🐉🔥""",
    "The Stampede": """The Marius questline beaten back step after step — waves endured, bosses toppled, stubborn retries piling high. Now Marius charges in, and that’s a flex the clan won’t forget. 🐂💥""",
    "The Medusa": """Hydra fragments hoarded chest by chest until Mithralla finally took shape. That’s weeks of patience, grind, and poison well spent. A champion forged in venom and victory. 🐍✨""",
    "The Zealot": """Chimera fragments gathered one by one — every fight, every chest, until Embrys stepped out of the mirror. That’s persistence crowned in style. 🔥🪞""",
    "The Succubus": """Siege after siege, reward chests farmed, fragments stacked steady. Lamasu doesn’t come easy — this is grind and glory rolled into one. 🛡️❤️""",
    "The Gladiator": """Live Arena is no joke — fight after fight, tooth and nail, until Quintus was earned. That’s raw PvP grit on display, and the crown sits well. 🗡️🏛️""",
    "The Devil": """500 cursed candles burned in the City, stage after stage, grind after grind — until Karnage rose from the shadows. That’s dedication with a streak of chaos, and we love it. 🔥💀""",
    "The Arachne": """Mikage doesn’t come easy — shard RNG, elusive epics, endless leveling, and the full fusion grind on top. Most players never even see her in their roster, but today Mikage’s here. That’s sheer determination paid in full. 🕷️🔥""",
}

# ------------------------------------------------------------
# Two-line Caillean toasts (exactly your text)
# ------------------------------------------------------------
def msg_hydra_single(user, role):
    return (
        f"> {user} just wrapped up **{role}**.\n"
        "That’s one of those clears — keys dropped, heads rolling, poisons ticking, and sheer stubborn willpower pushing it through. "
        "Hydra’s sulking in the corner, but the chest is cracked and the clan’s raising a glass. 🐍🍻"
    )

def msg_hydra_group(user, roles_list):
    roles_str = ", ".join(f"**{r}**" for r in roles_list)
    return (
        f"> {user} didn’t just poke the beast… they cleared {roles_str} like it was a warm-up act.\n"
        "Keys burned, heads toppled one after another, loot stacked with every chest — and not a pause in sight. "
        "That’s the kind of progress that makes the rest of us quietly re-check if we even used our keys this week. 👏🔥"
    )

def msg_chimera_single(user, role):
    return (
        f"> {user} just finished **{role}**.\n"
        "That’s no easy feat — reflections twisting, phases dragging on, and more than a few “do we really have to?” key drops. "
        "But Chimera blinked first, and the loot is proof. 🪞✨"
    )

def msg_chimera_group(user, roles_list):
    roles_str = ", ".join(f"**{r}**" for r in roles_list)
    return (
        f"> {user} didn’t just step into the mirror hall… they cleared {roles_str} back-to-back.\n"
        "Illusions stacked against them, phases stretched long, every mechanic screaming for patience — yet they walked it like choreography. "
        "Smooth, stubborn, flawless. 👏💎"
    )

def msg_doom_single(user, role):
    return (
        f"> {user} just topped **{role}**.\n"
        "Floor after floor, waves dragging on, bosses stacking mechanics like bad jokes — but none of it held them back. "
        "The climb’s done, the key’s turned, and the tower’s been put back in its place. 🗼🥂"
    )

def msg_doom_group(user, roles_list):
    roles_str = ", ".join(f"**{r}**" for r in roles_list)
    return (
        f"> {user} didn’t just poke around — they cleared {roles_str} in one sweep.\n"
        "Rotations reset, bosses lined up, every floor conquered without flinching. "
        "That’s not just a climb, that’s planting a flag on top and waving down at the rest of us. 🏆🔥"
    )

def msg_city_single(user, role):
    return (
        f"> {user} just wrapped up **{role}**.\n"
        "Every path walked, every stage dragged through, every stubborn fight finally settled. "
        "Sintranos doesn’t give up its crown easy — but today it bowed, and the loot’s proof of it. 👑✨"
    )

def msg_city_group(user, roles_list):
    roles_str = ", ".join(f"**{r}**" for r in roles_list)
    return (
        f"> {user} didn’t just wander the streets — they swept up {roles_str} in one run.\n"
        "Routes traced, side paths beaten, the full city scrubbed clean from start to finish. "
        "That’s not just a clear, that’s owning the map outright. 🏰🔥"
    )

def msg_amius_single(user, role):
    return (
        f"> {user} just wrapped up **{role}**.\n"
        "That’s the end boss of Sintranos brought down — waves endured, mechanics dragged out, and sheer stubbornness carrying it through. "
        "Amius doesn’t fall easy, but today it’s their banner standing tall. 👑⚔️"
    )

def msg_amius_group(user, roles_list):
    roles_str = ", ".join(f"**{r}**" for r in roles_list)
    return (
        f"> {user} didn’t just poke the Cursed City — they cleared {roles_str} straight through.\n"
        "Both ends of Amius crushed, the hardest fights in Sintranos checked off the list. "
        "That’s not just progression, that’s mastery stamped on the map. 🏰🔥"
    )

# --- Clan Boss Keys (only the second set) ---
def msg_cb_single(user, role):
    return (
        f"> {user} just earned **{role}**.\n"
        "Max chest cracked with ruthless efficiency — the boss barely had time to snarl before the damage stacked too high. "
        "That’s account power showing off. 🔑📊"
    )

def msg_cb_group(user, roles_list):
    roles_str = ", ".join(f"**{r}**" for r in roles_list)
    return (
        f"> {user} stacked {roles_str}.\n"
        "Different levels, same story — max chests opened in style, bosses folded like paper. "
        "That’s damage math and team building coming together beautifully. 🥁💥"
    )

def msg_arena_single(user, role):
    return (
        f"> {user} just climbed into **{role}**.\n"
        "That’s the big leagues — speed checks, nukes flying, constant scrapping at the top. "
        "Platinum’s not a tourist stop, and they just planted their flag on the skyline. ⚔️🌆"
    )

def msg_faction_single(user, role):
    return (
        f"> {user} just wrapped up **Faction Wars** and welcomed Lydia home.\n"
        "That’s months of grind, team building across every faction, and more retries than anyone dares to count. "
        "Finishing it is one of the biggest steps in Raid — and today it’s done. Huge respect. 💜⚔️"
    )

def msg_cross_fallback(user, roles_list):
    roles_str = ", ".join(f"**{r}**" for r in roles_list)
    return (
        f"> {user} just went on a spree and picked up {roles_str}.\n"
        "That’s milestones dropping left and right — bosses toppled, fragments stacked, loot pouring in, and progress lighting up across the board. "
        "Feels less like a checklist and more like a raid festival, and we’re all clapping from the tavern seats. 🍿🔥"
    )

def msg_special(user, role_name, note):
    return (
        f"> {user} just unlocked **{role_name}**.\n"
        f"{note}"
    )

# Cluster → (single_fn, group_fn)
CLUSTER_TEMPLATES = {
    "hydra":        (msg_hydra_single,   msg_hydra_group),
    "chimera":      (msg_chimera_single, msg_chimera_group),
    "doomtower":    (msg_doom_single,    msg_doom_group),
    "cursed_city":  (msg_city_single,    msg_city_group),
    "amius":        (msg_amius_single,   msg_amius_group),
    "cb_keys":      (msg_cb_single,      msg_cb_group),
    "arena":        (msg_arena_single,   None),  # single only
    "faction_wars": (msg_faction_single, None),  # single only
}

# Build role → cluster map (include Amius)
ROLE_TO_CLUSTER = {}
for cluster, data in CLUSTERS.items():
    for r in data["roles"]:
        ROLE_TO_CLUSTER[r.lower()] = cluster

# ------------------------------------------------------------
# Level-up messages (kept as-is)
# ------------------------------------------------------------
triggers = {
    "has reached Level 20!":
    """ ## 🔹 **The first sparks always seem small. Until you realize they never went out.**

**{user}** has reached **Level 20** and stepped into the role of **🔥 Keeper of the Conversation Flame**. You’ve brought warmth, noise and the kind of flickers we gather around. Keep it lit.""",

    "has reached Level 30!":
    """ ## 🔹 **The words know who carries them.**

{user}, you’ve reached **Level 30** and now wear the title **📝 Warden of the Words**. You show up, you speak up, and somehow… you make it all feel a little more like home.""",

    "has reached Level 40!":
    """ ## 🔹 **There’s laughter in the halls, and somewhere behind it, a steady presence.**

{user} has reached **Level 40** and been named **🎭 Guardian of the Banter Hall**. You don’t just toss words into the fire, you hold the space when it gets too hot.""",

    "has reached Level 50!":
    """ ## 🔹 **Not all chaos is loud. Some of it is carefully catalogued.**

{user} hit  **Level 50** and with it, the mantle of **🧷 High Curator of Chat Chaos**. You leave a trail of inside jokes and suspicious emoji reactions. We wouldn’t have it any other way.""",

    "has reached Level 60!":
    """ ## 🔹 **Some voices echo. Others endure.**

{user} has reached  **Level 60** and taken their place as **🕯️ Steward of the Spoken Flame**. You’ve helped keep this place warm, even when it got quiet. That’s what makes it real.""",

    "has reached Level 70!":
    """ ## 🔹 **It’s not always what you say. Sometimes it’s just that you show up.**

{user} now walks at  **Level 70** as the **📣 Patron of the Public Word**. You’ve shared, sparked, replied, stayed. And it matters more than you know.""",

    "has reached Level 80!":
    """ ## 🔹 **You’ve seen things. Typed things. Possibly instigated things.**

{user} is now  **Level 80** and whispered into the role of **🪶 Custodian of the Cult Chatter**. You don’t just ride the chaos, you store it neatly in scrolls somewhere we’re afraid to open.""",

    "has reached Level 90!":
    """ ## 🔹 **There are legends buried in these channels, and you’ve probably caused half of them.**

{user} has reached **Level 90** and now scribes as **📚 Archivist of the Banter Scrolls**. May your scrolls remain unreadable and your typos forever canon.""",

    "has reached Level 100!":
    """ ## 🔹 **There’s always that one voice you hear before the storm hits.**

{user} now wears the title **🗣️ Mouthpiece of the Madness** at Level 100. We’d say you’ve earned it… but let’s be honest, it was inevitable.""",

    "has reached Level 110!":
    """ ## 🔹 **The dots appear. And we all know what’s coming.**

{user} has reached **Level 110** and taken their place as **💬 Harbinger of the Typing Dots**. Your messages may delay, but your presence is never in doubt.""",
}

# ------------------------------------------------------------
# Runtime caches (grouping for non-specials)
# ------------------------------------------------------------
buffers = {}        # buffers[guild_id][user_id] = {"roles": set([...]), "task": asyncio.Task}
guild_channels = {} # guild_id -> {"audit": channel, "levels": channel}

# ------------------------------------------------------------
# Helpers (embed parsing + role detection)
# ------------------------------------------------------------
def _embed_text(msg: discord.Message) -> str:
    """Concatenate all embed text so we can regex it like content."""
    parts = []
    for e in msg.embeds:
        if e.title: parts.append(e.title)
        if e.description: parts.append(e.description)
        for f in (e.fields or []):
            if f.name: parts.append(f.name)
            if f.value: parts.append(f.value)
        if e.footer and getattr(e.footer, "text", None):
            parts.append(e.footer.text)
    return "\n".join(parts)

def find_cluster(role_name: str):
    return ROLE_TO_CLUSTER.get(role_name.lower())

def is_special(role_name: str):
    return role_name in SPECIAL_CHAMPIONS

def get_cluster_templates(cluster_key: str):
    return CLUSTER_TEMPLATES.get(cluster_key, (None, None))

async def ensure_channels_for_guild(guild: discord.Guild):
    if guild.id in guild_channels:
        return guild_channels[guild.id]
    audit = discord.utils.get(guild.text_channels, name=AUDIT_LOG_CHANNEL_NAME)
    levels = discord.utils.get(guild.text_channels, name=LEVELS_CHANNEL_NAME)
    guild_channels[guild.id] = {"audit": audit, "levels": levels}
    return guild_channels[guild.id]

async def send_levels(guild: discord.Guild, content: str):
    chans = await ensure_channels_for_guild(guild)
    levels = chans["levels"]
    if not levels:
        log.warning(f"levels channel '{LEVELS_CHANNEL_NAME}' not found in {guild.name}")
        return
    await levels.send(content)

async def flush_user_buffer(guild: discord.Guild, user_id: int, user_mention: str):
    """Send grouped message for non-special roles after GROUP_WINDOW_SECONDS."""
    gbuf = buffers.setdefault(guild.id, {})
    entry = gbuf.get(user_id)
    if not entry:
        return
    roles = sorted(entry["roles"])
    clusters_present = {find_cluster(r) for r in roles if find_cluster(r)}

    if not clusters_present:
        msg = msg_cross_fallback(user_mention, roles)
        await send_levels(guild, msg)
        gbuf.pop(user_id, None)
        return

    if len(clusters_present) == 1:
        cluster = next(iter(clusters_present))
        single_fn, group_fn = get_cluster_templates(cluster)
        if len(roles) == 1 and single_fn:
            msg = single_fn(user_mention, roles[0])
        else:
            msg = group_fn(user_mention, roles) if group_fn else msg_cross_fallback(user_mention, roles)
    else:
        msg = msg_cross_fallback(user_mention, roles)

    await send_levels(guild, msg)
    gbuf.pop(user_id, None)

def role_names_from_message(msg: discord.Message):
    """Extract role names from content + embeds + common patterns."""
    names = set()

    # Mentions (rare for roles in logs, but include)
    for r in msg.role_mentions:
        names.add(r.name)

    blob = f"{msg.content or ''}\n{_embed_text(msg)}".strip()

    # Bolded role names **Role**
    for m in re.finditer(r"\*\*([^*]+)\*\*", blob):
        names.add(m.group(1).strip())

    # Common phrases: "Role added", "Gave role", etc.
    for m in re.finditer(r"(?:role\s+added|gave\s+role(?:s)?|added\s+role)\s*[:\-]?\s*([^\n\r]+?)\s+(?:to|for)\s+", blob, flags=re.I):
        candidate = m.group(1).strip()
        for piece in re.split(r"[,/]| and ", candidate):
            piece = piece.strip()
            if piece:
                names.add(piece)

    # Also catch lines that look like "@Chimera Hard" in embeds
    for m in re.finditer(r"@([A-Za-z0-9 ][A-Za-z0-9 \-_/]+)", blob):
        names.add(m.group(1).strip())

    # Clean stray IDs
    cleaned = set()
    for n in names:
        cleaned.add(re.sub(r"<@&\d+>", "", n).strip())
    return {c for c in cleaned if c}

def looks_like_role_add(msg: discord.Message):
    blob = f"{(msg.content or '').lower()}\n{_embed_text(msg).lower()}"
    if "removed" in blob or "role removed" in blob:
        return False
    return ("role added" in blob or "gave role" in blob or "added role" in blob or msg.role_mentions)

# ------------------------------------------------------------
# Events
# ------------------------------------------------------------
@bot.event
async def on_ready():
    log.info(f"logged in as {bot.user} (id={bot.user.id})")
    try:
        for guild in bot.guilds:
            await ensure_channels_for_guild(guild)
            try:
                await guild.me.edit(nick="The Scribe That Knows Too Much")
            except discord.Forbidden:
                log.info(f"no permission to change nickname in {guild.name}")
    except Exception:
        log.exception("on_ready setup failed")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Existing level-up responses (kept)
    for trigger, response in triggers.items():
        if trigger in message.content:
            mentioned_user = message.mentions[0].mention if message.mentions else message.author.mention
            formatted = response.format(user=mentioned_user)
            await message.channel.send(formatted)
            break

    # Audit-log role detection (now parses embeds too)
    chans = await ensure_channels_for_guild(message.guild)
    if chans["audit"] and message.channel.id == chans["audit"].id and looks_like_role_add(message):
        target_mention = message.mentions[0].mention if message.mentions else None
        target_id = message.mentions[0].id if message.mentions else None
        if not target_id:
            m = re.search(r"\bto\s+<@!?(\d+)>", f"{message.content}\n{_embed_text(message)}")
            if m:
                target_id = int(m.group(1))
                target_mention = f"<@{target_id}>"
        if not target_id:
            return

        role_names = role_names_from_message(message)
        if not role_names:
            return

        to_collect = []
        for rn in role_names:
            if is_special(rn):
                await send_levels(message.guild, msg_special(target_mention, rn, SPECIAL_CHAMPIONS[rn]))
            elif rn.lower() in ROLE_TO_CLUSTER:
                to_collect.append(rn)

        if to_collect:
            gbuf = buffers.setdefault(message.guild.id, {})
            entry = gbuf.get(target_id)
            if entry and "task" in entry and not entry["task"].done():
                entry["roles"].update(to_collect)
                entry["task"].cancel()
            else:
                entry = {"roles": set()}
                gbuf[target_id] = entry
            entry["roles"].update(to_collect)

            async def _delayed_flush():
                try:
                    await asyncio.sleep(GROUP_WINDOW_SECONDS)
                    await flush_user_buffer(message.guild, target_id, target_mention)
                except asyncio.CancelledError:
                    pass

            entry["task"] = asyncio.create_task(_delayed_flush())

    await bot.process_commands(message)

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """
    Fallback: fires when roles actually change. We diff roles and run the same pipeline.
    Catches role adds even if the audit logger format changes.
    """
    try:
        before_set = {r.name for r in before.roles}
        after_set  = {r.name for r in after.roles}
        added = list(after_set - before_set)
        if not added:
            return

        recognized = []
        specials = []
        for rn in added:
            if rn in SPECIAL_CHAMPIONS:
                specials.append(rn)
            elif rn.lower() in ROLE_TO_CLUSTER:
                recognized.append(rn)

        if not recognized and not specials:
            return

        # Specials fire immediately
        for rn in specials:
            await send_levels(after.guild, msg_special(after.mention, rn, SPECIAL_CHAMPIONS[rn]))

        # Group others
        if recognized:
            gbuf = buffers.setdefault(after.guild.id, {})
            entry = gbuf.get(after.id)
            if entry and "task" in entry and not entry["task"].done():
                entry["roles"].update(recognized)
                entry["task"].cancel()
            else:
                entry = {"roles": set()}
                gbuf[after.id] = entry
            entry["roles"].update(recognized)

            async def _delayed_flush():
                try:
                    await asyncio.sleep(GROUP_WINDOW_SECONDS)
                    await flush_user_buffer(after.guild, after.id, after.mention)
                except asyncio.CancelledError:
                    pass

            entry["task"] = asyncio.create_task(_delayed_flush())
    except Exception:
        log.exception("on_member_update failed")

# --------------------------
# Start the app + discord
# --------------------------
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token or not token.strip():
        log.error("ENV DISCORD_BOT_TOKEN is missing/empty. Set it in Render → Environment.")
        raise SystemExit(1)

    keep_alive()
    log.info("starting discord client…")
    try:
        bot.run(token)
    except Exception:
        log.exception("fatal error on startup")
        raise
