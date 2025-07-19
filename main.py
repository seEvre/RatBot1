import os
import json
import asyncio
from datetime import datetime
import random
import string

from flask import Flask, request, render_template_string
import threading

import nextcord
from nextcord import Embed, Intents, Interaction
from nextcord.ext import commands, tasks

TOKEN = "YOUR_BOT_TOKEN"
GUILD_ID = 123456789012345678  # Replace with your server ID
RENDER_URL = "https://your-render-service-url"  # e.g. https://mybot.onrender.com
BACKUP_FOLDER = "backups"
BACKUP_INTERVAL = 60 * 60  # 1 hour

intents = Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

app = Flask(__name__)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

def is_admin():
    def predicate(interaction):
        return interaction.user.guild_permissions.administrator
    return commands.check(predicate)

async def backup_entire_channel(channel):
    messages = []
    async for message in channel.history(limit=None, oldest_first=True):
        embeds_data = []
        for embed in message.embeds:
            embeds_data.append(embed.to_dict())
        messages.append({
            "author": str(message.author),
            "content": message.content,
            "timestamp": str(message.created_at),
            "embeds": embeds_data
        })
    filename = f"{BACKUP_FOLDER}/{channel.id}_{int(datetime.utcnow().timestamp())}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)
    return filename

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    backup_loop.start()

@tasks.loop(seconds=BACKUP_INTERVAL)
async def backup_loop():
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                await backup_entire_channel(channel)
            except Exception as e:
                print(f"Backup failed in {channel.name}: {e}")
        await post_backup_log(guild)

async def post_backup_log(guild):
    log_channel = next((c for c in guild.text_channels if c.name == "backup-logs"), None)
    if log_channel is None:
        log_channel = await guild.create_text_channel("backup-logs")

    timestamp = int(datetime.utcnow().timestamp())
    embed = Embed(
        title="📁 Server Backup Created",
        description=f"A backup of all server channels was just completed at <t:{timestamp}:f>.",
        color=0x00BFFF
    )
    embed.add_field(name="🔗 View Backups", value=f"[Open Viewer]({RENDER_URL}/view)", inline=False)
    embed.set_footer(text="Botanic Backup System")
    await log_channel.send(embed=embed)

@bot.slash_command(guild_ids=[GUILD_ID], description="Manually back up this channel")
@is_admin()
async def backup(interaction: Interaction):
    filename = await backup_entire_channel(interaction.channel)
    await post_backup_log(interaction.guild)
    timestamp = int(datetime.utcnow().timestamp())
    embed = Embed(
        title="✅ Manual Backup Complete",
        description=f"Channel **#{interaction.channel.name}** backed up at <t:{timestamp}:f>.",
        color=0x00FF7F
    )
    embed.set_footer(text="Botanic Manual Backup")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Delete all backup files")
@is_admin()
async def deletebackups(interaction: Interaction):
    deleted = 0
    for file in os.listdir(BACKUP_FOLDER):
        try:
            os.remove(os.path.join(BACKUP_FOLDER, file))
            deleted += 1
        except:
            continue
    embed = Embed(
        title="🗑️ Backups Deleted",
        description=f"Removed `{deleted}` backup file(s).",
        color=0xFF5555
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Set auto-backup interval (in minutes)")
@is_admin()
async def setinterval(interaction: Interaction, minutes: int):
    global BACKUP_INTERVAL
    if minutes < 1 or minutes > 1440:
        await interaction.response.send_message("Interval must be between 1 and 1440 minutes.", ephemeral=True)
        return
    BACKUP_INTERVAL = minutes * 60
    backup_loop.change_interval(seconds=BACKUP_INTERVAL)
    embed = Embed(
        title="⏱️ Interval Updated",
        description=f"Backups will now occur every **{minutes} minutes**.",
        color=0x3498DB
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Spam audit log with fake role changes")
@is_admin()
async def auditspam(interaction: Interaction):
    await interaction.response.send_message("Starting audit spam...", ephemeral=True)
    for _ in range(50):
        name = ''.join(random.choices(string.ascii_letters, k=8))
        try:
            role = await interaction.guild.create_role(name=name)
            await asyncio.sleep(0.2)
            await role.delete()
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Audit spam error: {e}")
    embed = Embed(
        title="🧨 Audit Log Spam Complete",
        description="Executed 50 create/delete role operations.",
        color=0xFFA500
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

# Flask Web Server for Render Keep-Alive and Viewer
@app.route("/")
def home():
    return "Bot is running."

@app.route("/view")
def view_backups():
    files = sorted(os.listdir(BACKUP_FOLDER), reverse=True)
    channel_map = {}
    for f in files:
        channel_id = f.split("_")[0]
        if channel_id not in channel_map:
            channel_map[channel_id] = []
        channel_map[channel_id].append(f)

    html = "<h1>📁 View Backups</h1>"
    for channel_id, backups in channel_map.items():
        html += f"<h2>Channel ID: {channel_id}</h2><ul>"
        for file in backups:
            html += f"<li><a href='/logs/{file}'>{file}</a></li>"
        html += "</ul>"
    return html

@app.route("/logs/<filename>")
def show_backup(filename):
    try:
        with open(os.path.join(BACKUP_FOLDER, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        html = f"<h1>📝 Backup: {filename}</h1><ul>"
        for entry in data:
            content = entry['content'].replace("<", "&lt;").replace(">", "&gt;")
            html += f"<li><b>{entry['author']}</b>: {content}"
            if entry['embeds']:
                html += f" <i>(+{len(entry['embeds'])} embed{'s' if len(entry['embeds']) > 1 else ''})</i>"
            html += "</li>"
        html += "</ul><a href='/view'>← Back</a>"
        return html
    except:
        return "Backup not found."

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

bot.run(TOKEN)
