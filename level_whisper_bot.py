import os
import re
import logging
import asyncio
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands

# --------------------------
# Logging (so Render logs show issues)
# --------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("c1c-appreciation-bot")

# --------------------------
# Keep-alive tiny web server (use Render's $PORT)
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
    t = Thread(target=_run_flask, daemon=True)
    t.start()

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
AUDIT_LOG_CHANNEL_NAME = "audit-log"   # source channel for role logs
LEVELS_CHANNEL_NAME    = "levels"      # target channel for appreciation messages
GROUP_WINDOW_SECONDS   = 60            # group multiple role adds within 60s per user

# ------------------------------------------------------------
# CONFIG (clusters)
# ------------------------------------------------------------
CLUSTERS = {
    "hydra": {
        "roles": {"Hydra Normal", "Hydra Hard", "Hydra Brutal", "Hydra NM"}
    },
    "chimera": {
        "roles": {"Chimera Normal", "Chimera Hard", "Chimera NM", "Chimera UNM"}
    },
    "doomtower": {
        "roles": {"Doomtower Normal", "Doomtower Hard"}
    },
    "cursed_city": {
        "roles": {"101 Stages cleared Sintranos Normal", "101 Stages cleared Sintranos Hard"}
    },
    "amius": {
        "roles": {"Amius Normal", "Amius Hard"}
    },
    "cb_keys": {
        "roles": {"1 Key NM", "1 Key UNM", "2 Key UNM"}
    },
    "arena": {
        "roles": {"Platinum Arena"}
    },
    "faction_wars": {
        "roles": {"Faction Wars"}
    },
}

# Special champions fire immediately (never grouped)
SPECIAL_CHAMPIONS = {
    "The Angel": "Arbiter’s questline finally closed — campaign clears, dungeons farmed, and every stubborn step ticked off. That road is long and brutal, and finishing it deserves nothing less than a proper toast. 🥂✨",
    "The Dragonborn": "Ramantu’s questline is no small grind — endless missions, high hurdles, and all the patience in the world. That’s endgame grit shining through, and a milestone worth loud applause. 🐉🔥",
    "The Stampede": "The Marius questline beaten back step after step — waves endured, bosses toppled, stubborn retries piling high. Now Marius charges in, and that’s a flex the clan won’t forget. 🐂💥",
    "The Medusa": "Hydra fragments hoarded chest by chest until Mithralla finally took shape. That’s weeks of patience, grind, and poison well spent. A champion forged in venom and victory. 🐍✨",
    "The Zealot": "Chimera fragments gathered one by one — every fight, every chest, until Embrys stepped out of the mirror. That’s persistence crowned in style. 🔥🪞",
    "The Succubus": "Siege after siege, reward chests farmed, fragments stacked steady. Lamasu doesn’t come easy — this is grind and glory rolled into one. 🛡️❤️",
    "The Gladiator": "Live Arena is no joke — fight after fight, tooth and nail, until Quintus was earned. That’s raw PvP grit on display, and the crown sits well. 🗡️🏛️",
    "The Devil": "500 cursed candles burned in the City, stage after stage, grind after grind — until Karnage rose from the shadows. That’s dedication with a streak of chaos, and we love it. 🔥💀",
    "The Arachne": "M
