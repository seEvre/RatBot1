import os
import discord
from discord.ext import commands, tasks
from flask import Flask, render_template_string, request
import threading
import datetime
import json
import asyncio

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)
app = Flask(__name__)

BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

# Templates
MAIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>📁 View Backups</title></head>
<body>
    <h1>📁 Available Backups</h1>
    {% for file in backups %}
        <div>
            <a href="/view?channel={{file}}">📄 {{file}}</a>
        </div>
    {% endfor %}
</body>
</html>
"""

VIEW_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>📄 {{channel_name}}</title></head>
<body>
    <h1>📄 Logs for #{{channel_name}}</h1>
    {% for log in logs %}
        <div style="margin-bottom: 15px;">
            <b>[{{log['timestamp']}}]</b>
            <u>{{log['author']}}</u>: {{log['content']}}
            {% if log['embeds'] %}
                <div style="background:#eee; padding:5px; margin-top:5px;">
                    <b>Embeds:</b>
                    {% for embed in log['embeds'] %}
                        <pre>{{embed}}</pre>
                    {% endfor %}
                </div>
            {% endif %}
        </div>
    {% endfor %}
</body>
</html>
"""

@app.route('/')
def index():
    backups = [f.replace(".json", "") for f in os.listdir(BACKUP_DIR)]
    return render_template_string(MAIN_TEMPLATE, backups=backups)

@app.route('/view')
def view():
    channel = request.args.get("channel")
    path = os.path.join(BACKUP_DIR, channel + ".json")
    if not os.path.exists(path):
        return f"No backup found for {channel}", 404
    with open(path, "r", encoding="utf-8") as f:
        logs = json.load(f)
    return render_template_string(VIEW_TEMPLATE, channel_name=channel, logs=logs)

def run_flask():
    app.run(host='0.0.0.0', port=8080)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print("Command sync failed:", e)

    await ensure_log_channels()
    backup_all_channels.start()

async def ensure_log_channels():
    for guild in bot.guilds:
        exists = discord.utils.get(guild.text_channels, name="backup-logs")
        if not exists:
            await guild.create_text_channel("backup-logs")

@tasks.loop(minutes=15)
async def backup_all_channels():
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                messages = []
                async for msg in channel.history(limit=None):
                    messages.append({
                        "author": str(msg.author),
                        "content": msg.content,
                        "timestamp": f"<t:{int(msg.created_at.timestamp())}:f>",
                        "embeds": [embed.to_dict() for embed in msg.embeds] if msg.embeds else []
                    })
                with open(os.path.join(BACKUP_DIR, f"{channel.name}.json"), "w", encoding="utf-8") as f:
                    json.dump(messages[::-1], f, indent=2)
            except Exception as e:
                print(f"Failed backing up #{channel.name}: {e}")

        log_channel = discord.utils.get(guild.text_channels, name="backup-logs")
        if log_channel:
            embed = discord.Embed(
                title="✅ Backup Completed",
                description="[📂 View Logs Here](http://localhost:8080)",
                color=discord.Color.green()
            )
            embed.set_footer(text="Backup System")
            await log_channel.send(embed=embed)

@bot.tree.command(name="auditspam", description="Spam audit log by creating/deleting roles rapidly")
async def auditspam(interaction: discord.Interaction):
    await interaction.response.send_message("📌 Spamming audit log...", ephemeral=True)
    for i in range(50):
        try:
            role = await interaction.guild.create_role(name=f"SpamRole-{i}")
            await role.delete()
        except Exception as e:
            print("Audit spam error:", e)
        await asyncio.sleep(0.0)

@bot.tree.command(name="set_interval", description="Set backup interval (in minutes)")
async def set_interval(interaction: discord.Interaction, minutes: int):
    backup_all_channels.change_interval(minutes=minutes)
    await interaction.response.send_message(f"⏱️ Backup interval set to {minutes} minutes.", ephemeral=True)

@bot.tree.command(name="delete_backups", description="Delete all stored backups")
async def delete_backups(interaction: discord.Interaction):
    for f in os.listdir(BACKUP_DIR):
        os.remove(os.path.join(BACKUP_DIR, f))
    await interaction.response.send_message("🗑️ All backups deleted.", ephemeral=True)

# Run web + bot
threading.Thread(target=run_flask).start()
bot.run(os.getenv("TOKEN"))
