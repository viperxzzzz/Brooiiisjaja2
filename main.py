import discord
from discord.ext import commands
import json
import threading
import os
import time
import re
from datetime import datetime

TOKEN = os.getenv("TOKEN")
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
lock = threading.Lock()

PRICES = {"low": 3, "medium": 10, "high": 14}
PRICE_PER_CREDIT = 0.35

STOCK_FILES = {
    "low": "stock_low.txt",
    "medium": "stock_medium.txt",
    "high": "stock_high.txt"
}

CREDITS_FILE = "credits.json"
GEN_LOG_FILE = "gen_log.txt"
HITRATE_FILE = "hitrate.json"

RESTOCK_CHANNEL_ID = 1474702726389567588
RESTOCK_ROLE_ID = 1475311889293774939
GEN_LOG_CHANNEL_ID = 1475984317581627402

GEN_COOLDOWN = 8
user_cooldowns = {}

# ================= JSON =================

def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ================= HITRATE =================

def load_hitrate():
    data = load_json(HITRATE_FILE)
    if not data:
        return {"total": 0, "robux": 0, "limited": 0, "rap_total": 0}
    return data

def save_hitrate(data):
    save_json(HITRATE_FILE, data)

# ================= STOCK =================

def gerar_produto(tipo):
    file = STOCK_FILES[tipo]
    with lock:
        if not os.path.exists(file):
            return None
        with open(file, "r") as f:
            linhas = [l.strip() for l in f if l.strip()]
        if not linhas:
            return None
        produto = linhas.pop(0)
        with open(file, "w") as f:
            f.write("\n".join(linhas))
        return produto

# ================= PARSER RESTOCK =================

def parse_viper_blocks(text):
    blocks = re.split(r"VIPER GEN RESULT", text, flags=re.I)
    results = []

    for b in blocks:
        b = b.strip()
        if not b:
            continue

        tier = None
        m = re.search(r"Tier:\s*(LOW|MEDIUM|HIGH)", b, re.I)
        if m:
            tier = m.group(1).lower()

        user = None
        m = re.search(r"User:\s*(.+)", b)
        if m:
            user = m.group(1).strip()

        pwd = None
        m = re.search(r"Pass:\s*(.+)", b)
        if m:
            pwd = m.group(1).strip()

        robux_match = re.search(r"Robux:\s*([\d,\.]+)", b, re.I)
        if robux_match:
            val = int(re.sub(r"\D", "", robux_match.group(1)))
            results.append(("robux", tier, val, user, pwd))
            continue

        limited_match = re.search(r"Limited:\s*(.+)", b, re.I)
        if limited_match:
            item = limited_match.group(1).strip()
            rap = 0
            rap_match = re.search(r"Value:\s*([\d,\.]+)", b, re.I)
            if rap_match:
                rap = int(re.sub(r"\D", "", rap_match.group(1)))
            results.append(("limited", tier, item, rap, user, pwd))

    return results

def save_parsed_results(results):
    hit = load_hitrate()
    tier_counts = {"low":0,"medium":0,"high":0}

    for r in results:
        if r[0] == "robux":
            _, tier, val, user, pwd = r
            line = f"ROBux:{val}|{user}|{pwd}"
            hit["robux"] += 1
        else:
            _, tier, item, rap, user, pwd = r
            line = f"LIMITED:{item}|{rap}|{user}|{pwd}"
            hit["limited"] += 1
            hit["rap_total"] += rap

        if tier in STOCK_FILES:
            with lock:
                with open(STOCK_FILES[tier], "a") as f:
                    f.write(line + "\n")
            tier_counts[tier] += 1

        hit["total"] += 1

    save_hitrate(hit)
    return tier_counts

# ================= CREDITS =================

def add_credits(user_id, amount):
    data = load_json(CREDITS_FILE)
    uid = str(user_id)
    data[uid] = data.get(uid, 0) + amount
    save_json(CREDITS_FILE, data)

def get_credits(user_id):
    data = load_json(CREDITS_FILE)
    return data.get(str(user_id), 0)

def remove_credits(user_id, amount):
    data = load_json(CREDITS_FILE)
    uid = str(user_id)
    if data.get(uid, 0) < amount:
        return False
    data[uid] -= amount
    save_json(CREDITS_FILE, data)
    return True

# ================= GEN VIEW =================

class GenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def process(self, interaction, tipo):
        user = interaction.user
        price = PRICES[tipo]

        now = time.time()
        last = user_cooldowns.get(user.id, 0)

        if now - last < GEN_COOLDOWN:
            await interaction.response.send_message("⏳ Cooldown", ephemeral=True)
            return

        if get_credits(user.id) < price:
            await interaction.response.send_message("❌ Sem créditos", ephemeral=True)
            return

        produto = gerar_produto(tipo)
        if not produto:
            await interaction.response.send_message("⚠️ Sem stock", ephemeral=True)
            return

        remove_credits(user.id, price)
        user_cooldowns[user.id] = time.time()

        if produto.startswith("ROBux:"):
            _, userp, passp = produto.split("|")
            val = produto.split(":",1)[1].split("|")[0]
            texto = f"💰 Robux: {val}\n👤 User: {userp}\n🔑 Pass: {passp}"

        elif produto.startswith("LIMITED:"):
            parts = produto.split("|")
            item = parts[0].split(":",1)[1]
            rap = parts[1]
            userp = parts[2]
            passp = parts[3]
            texto = f"🎩 Limited: {item}\n💎 RAP: {rap}\n👤 User: {userp}\n🔑 Pass: {passp}"
        else:
            texto = produto

        with lock:
            with open(GEN_LOG_FILE, "a") as f:
                f.write(f"{datetime.utcnow()}|{user.id}|{tipo}|{produto}\n")

        canal = bot.get_channel(GEN_LOG_CHANNEL_ID)
        if canal:
            await canal.send(f"GEN\nUser: <@{user.id}>\nTier: {tipo.upper()}\n{texto}")

        try:
            await user.send(f"VIPER GEN\nProduto: {tipo.upper()}\n\n{texto}")
            await interaction.response.send_message("✔ Entregue", ephemeral=True)
        except:
            await interaction.response.send_message("❌ DM fechada", ephemeral=True)

    @discord.ui.button(label="LOW", style=discord.ButtonStyle.danger)
    async def low(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, "low")

    @discord.ui.button(label="MEDIUM", style=discord.ButtonStyle.primary)
    async def medium(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, "medium")

    @discord.ui.button(label="HIGH", style=discord.ButtonStyle.success)
    async def high(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, "high")

# ================= COMMANDS =================

@bot.command()
async def painel(ctx):
    embed = discord.Embed(title="VIPER GEN", description="Escolha o tier", color=0xff003c)
    for t in PRICES:
        embed.add_field(name=t.upper(), value=f"{PRICES[t]} credits", inline=False)
    await ctx.send(embed=embed, view=GenView())

@bot.command()
@commands.has_permissions(administrator=True)
async def restock(ctx, *, texto: str):
    parsed = parse_viper_blocks(texto)
    if not parsed:
        await ctx.send("Nada detectado")
        return

    tier_counts = save_parsed_results(parsed)

    canal = bot.get_channel(RESTOCK_CHANNEL_ID)
    if canal:
        ping = f"<@&{RESTOCK_ROLE_ID}> " if RESTOCK_ROLE_ID else ""
        for tier, count in tier_counts.items():
            if count > 0:
                await canal.send(f"{ping}RESTOCK {tier.upper()} {count}")

    await ctx.send(f"Restockado {sum(tier_counts.values())}")

bot.run(TOKEN)
