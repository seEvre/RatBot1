import nextcord
from nextcord import Interaction, Embed
from nextcord.ext import commands
from flask import Flask, jsonify, send_from_directory, escape, request
import asyncio
import os
from threading import Thread
from datetime import datetime
import random
import string
import json

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True  # for member join event

bot = commands.Bot(command_prefix="!", intents=intents)
app = Flask(__name__)

LOCKDOWN_ENABLED = False
BACKUP_FOLDER = "backups"
BACKUP_INTERVAL = 30 * 60  # default 30 minutes in seconds

if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER)

@app.route("/")
def home():
    return jsonify({"status": "Bot is alive"}), 200

@app.route("/backups/<path:filename>")
def serve_backup(filename):
    return send_from_directory(BACKUP_FOLDER, filename)

@app.route("/view")
def view_backups():
    files = sorted(os.listdir(BACKUP_FOLDER), reverse=True)
    channel_map = {}

    # Group backups by channel id and get channel names from the bot cache
    for f in files:
        if "_" not in f:
            continue
        channel_id = f.split("_")[0]
        if channel_id not in channel_map:
            channel_map[channel_id] = []
        channel_map[channel_id].append(f)

    html = "<h1>📁 View Backups</h1>"
    for channel_id, backups in channel_map.items():
        channel = bot.get_channel(int(channel_id))
        channel_name = channel.name if channel else f"Unknown Channel ({channel_id})"
        html += f"<h2>#{escape(channel_name)}</h2><ul>"
        for file in backups:
            html += f"<li><a href='/logs/{escape(file)}'>{escape(file)}</a></li>"
        html += "</ul>"

    return html

@app.route("/logs/<filename>")
def show_backup(filename):
    filepath = os.path.join(BACKUP_FOLDER, filename)
    if not os.path.exists(filepath):
        return "Backup not found.", 404

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"Failed to load backup: {e}", 500

    html = f"<h1>📝 Backup: {escape(filename)}</h1><ul>"
    for entry in data:
        content = escape(entry.get('content', ''))
        author = escape(entry.get('author', 'Unknown'))
        timestamp_raw = entry.get('timestamp', '')
        # Convert ISO timestamp string to UNIX timestamp for Discord style timestamp
        try:
            dt = datetime.fromisoformat(timestamp_raw.replace('Z', '+00:00'))
            unix_ts = int(dt.timestamp())
            time_str = f"<t:{unix_ts}:f>"
        except Exception:
            time_str = timestamp_raw

        html += f"<li><b>{author}</b> at {time_str}: {content}"

        embeds = entry.get('embeds', [])
        if embeds:
            html += f"<br><i>Embeds:</i><ul>"
            for embed in embeds:
                title = escape(embed.get('title', ''))
                desc = escape(embed.get('description', ''))
                html += f"<li><b>{title}</b><br>{desc}</li>"
            html += "</ul>"

        html += "</li><br>"
    html += "</ul><a href='/view'>← Back to backups list</a>"

    return html

def is_admin():
    async def predicate(interaction: Interaction):
        return interaction.user.guild_permissions.administrator
    return commands.check(predicate)

async def backup_entire_channel(channel):
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        # Save content + embeds data
        msg_entry = {
            "timestamp": msg.created_at.isoformat(),
            "author": msg.author.display_name,
            "content": msg.content,
            "embeds": []
        }
        for emb in msg.embeds:
            emb_data = {
                "title": emb.title or "",
                "description": emb.description or "",
            }
            msg_entry["embeds"].append(emb_data)
        messages.append(msg_entry)

    filename = f"{channel.id}_{int(datetime.utcnow().timestamp())}.json"
    filepath = os.path.join(BACKUP_FOLDER, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    return filename

async def post_backup_log(guild, filename):
    log_channel = next((ch for ch in guild.text_channels if ch.name == "backup-logs"), None)
    if log_channel is None:
        overwrites = {
            guild.default_role: nextcord.PermissionOverwrite(send_messages=False, view_channel=True),
            guild.me: nextcord.PermissionOverwrite(send_messages=True, view_channel=True)
        }
        log_channel = await guild.create_text_channel("backup-logs", overwrites=overwrites)

    url = f"{os.getenv('RENDER_EXTERNAL_URL')}/backups/{filename}"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    embed = Embed(title="Backup Created", description=f"Backup created at <t:{int(datetime.utcnow().timestamp())}:f>")
    embed.add_field(name="View Backup", value=f"[Click here]({url})", inline=False)
    await log_channel.send(embed=embed)

@bot.slash_command(guild_ids=[GUILD_ID], description="Backup entire channel messages")
@is_admin()
async def backup(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    filename = await backup_entire_channel(interaction.channel)
    await post_backup_log(interaction.guild, filename)
    embed = Embed(title="Backup Completed", description="Channel backup created and logged.")
    await interaction.followup.send(embed=embed, ephemeral=True)

lockdown_enabled = False

@bot.slash_command(guild_ids=[GUILD_ID], description="Enable lockdown mode")
@is_admin()
async def lockdown(interaction: Interaction):
    global lockdown_enabled
    lockdown_enabled = True
    embed = Embed(title="Lockdown Enabled", description="New users will be kicked upon joining.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Disable lockdown mode")
@is_admin()
async def unlock(interaction: Interaction):
    global lockdown_enabled
    lockdown_enabled = False
    embed = Embed(title="Lockdown Disabled", description="Users can join normally again.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Set backup interval in minutes")
@is_admin()
async def setinterval(interaction: Interaction, minutes: int):
    global BACKUP_INTERVAL
    if minutes < 1 or minutes > 1440:
        await interaction.response.send_message("Please set an interval between 1 and 1440 minutes.", ephemeral=True)
        return
    BACKUP_INTERVAL = minutes * 60
    embed = Embed(title="Backup Interval Updated", description=f"Backup interval set to {minutes} minute(s).")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Spam audit log by creating and deleting roles 50 times (admin only)")
@is_admin()
async def auditspam(interaction: Interaction):
    await interaction.response.send_message("Starting audit log spam: creating and deleting 50 roles...", ephemeral=True)

    for i in range(50):
        role_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        try:
            role = await interaction.guild.create_role(name=role_name)
            await asyncio.sleep(0.5)  # wait to reduce rate limit risks
            await role.delete()
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Error during auditspam iteration {i}: {e}")

    await interaction.followup.send("Audit log spam complete!", ephemeral=True)

@bot.slash_command(guild_ids=[GUILD_ID], description="Delete all backups in storage (admin only)")
@is_admin()
async def deletebackups(interaction: Interaction, confirm: bool = False):
    if not confirm:
        await interaction.response.send_message("⚠️ This will delete all backups. Run again with `confirm: true` to confirm.", ephemeral=True)
        return

    count = 0
    for filename in os.listdir(BACKUP_FOLDER):
        try:
            os.remove(os.path.join(BACKUP_FOLDER, filename))
            count += 1
        except Exception as e:
            print(f"Failed to delete backup {filename}: {e}")
    embed = Embed(title="Backups Deleted", description=f"Deleted {count} backup file(s).")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_member_join(member):
    if lockdown_enabled and member.guild.id == GUILD_ID:
        try:
            await member.kick(reason="Server is in lockdown mode.")
        except Exception as e:
            print(f"Failed to kick {member}: {e}")

async def auto_backup_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            for channel in guild.text_channels:
                try:
                    filename = await backup_entire_channel(channel)
                    await post_backup_log(guild, filename)
                except Exception as e:
                    print(f"Backup error for {channel.name}: {e}")
        await asyncio.sleep(BACKUP_INTERVAL)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not hasattr(bot, "backup_task") or bot.backup_task.done():
        bot.backup_task = bot.loop.create_task(auto_backup_loop())

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.run(TOKEN)
