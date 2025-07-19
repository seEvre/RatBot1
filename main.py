import nextcord
from nextcord import Interaction
from nextcord.ext import commands
from flask import Flask, jsonify
import asyncio
import sqlite3
import os
from threading import Thread

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

intents = nextcord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "Bot is alive"}), 200

def is_admin():
    async def predicate(interaction: Interaction):
        return interaction.user.guild_permissions.administrator
    return commands.check(predicate)

conn = sqlite3.connect("messages.db")
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS backups
             (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, message TEXT)''')
conn.commit()

async def backup_channel_messages(channel, limit=50):
    messages = await channel.history(limit=limit).flatten()
    for msg in messages:
        c.execute("INSERT INTO backups (channel_id, message) VALUES (?, ?)", (channel.id, msg.content))
    conn.commit()

@bot.slash_command(guild_ids=[GUILD_ID], description="Backup recent messages")
@is_admin()
async def backup(interaction: Interaction):
    await backup_channel_messages(interaction.channel)
    await interaction.response.send_message("Backed up recent messages.", ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Lockdown the server (remove invites)")
@is_admin()
async def lockdown(interaction: Interaction):
    guild = bot.get_guild(GUILD_ID)
    invites = await guild.invites()
    for invite in invites:
        await invite.delete()
    await interaction.response.send_message("Server is locked down.", ephemeral=True)

async def auto_backup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            for channel in guild.text_channels:
                try:
                    await backup_channel_messages(channel)
                except Exception:
                    pass
        await asyncio.sleep(1800)  # every 30 minutes

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    bot.loop.create_task(auto_backup_loop())

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.run(TOKEN)