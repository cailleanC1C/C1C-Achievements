from flask import Flask
from threading import Thread
import discord
from discord.ext import commands

# Web server setup to keep the bot alive
app = Flask('')

@app.route('/')
def home():
    return "I'm alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Level-up triggers
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

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Helping Caillean run the chaos • No refunds"
    ))
    for guild in bot.guilds:
        try:
            await guild.me.edit(nick="The Scribe That Knows Too Much")
            print(f"Nickname set in {guild.name}")
        except discord.Forbidden:
            print(f"Missing permission to change nickname in {guild.name}")
        except Exception as e:
            print(f"Failed to set nickname in {guild.name}: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != 1050097435789250570:
        return
    for trigger, response in triggers.items():
        if trigger in message.content:
            mentioned_user = message.mentions[0].mention if message.mentions else message.author.mention
            formatted = response.format(user=mentioned_user)
            await message.channel.send(formatted)
            break
    await bot.process_commands(message)

# Keep alive
keep_alive()
# Run the bot
import os
bot.run(os.getenv("DISCORD_BOT_TOKEN"))

