import nextcord
from nextcord import Interaction, Embed
from nextcord.ext import commands
from flask import Flask, jsonify, send_from_directory
import asyncio
import os
from threading import Thread
from datetime import datetime
import random
import string

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

def is_admin():
    async def predicate(interaction: Interaction):
        return interaction.user.guild_permissions.administrator
    return commands.check(predicate)

async def backup_entire_channel(channel):
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author = msg.author.display_name
        content = msg.content.replace("\n", " ")
        messages.append(f"[{timestamp}] {author}: {content}")
    filename = f"channel_{channel.id}.txt"
    filepath = os.path.join(BACKUP_FOLDER, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(messages))
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
    embed = Embed(title="Backup Created", description=f"Backup created at {timestamp}")
    embed.add_field(name="View Backup", value=f"[Click here]({url})", inline=False)
    await log_channel.send(embed=embed)

@bot.slash_command(guild_ids=[GUILD_ID], description="Backup entire channel messages")
@is_admin()
async def backup(interaction: Interaction):
    filename = await backup_entire_channel(interaction.channel)
    await post_backup_log(interaction.guild, filename)
    embed = Embed(title="Backup Completed", description="Channel backup created and logged.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
    bot.loop.create_task(auto_backup_loop())

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.run(TOKEN)
