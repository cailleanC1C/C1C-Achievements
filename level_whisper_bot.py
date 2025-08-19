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
    "The Arachne": "Mikage doesn’t come easy — shard RNG, elusive epics, endless leveling, and the full fusion grind on top. Most players never even see her in their roster, but today Mikage’s here. That’s sheer determination paid in full. 🕷️🔥",
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

# --- Clan Boss Keys (keep ONLY the second set you chose) ---
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
