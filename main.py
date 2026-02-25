import discord
from discord.ext import commands
import json
import threading
import os
import time
import random
from datetime import datetime

TOKEN = os.getenv("TOKEN")
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
lock = threading.Lock()

# ================= CONFIG =================

PRICES = {"low": 3, "medium": 10, "high": 14}
PRICE_PER_CREDIT = 0.35

STOCK_FILES = {
    "low": "stock_low.txt",
    "medium": "stock_medium.txt",
    "high": "stock_high.txt"
}

CREDITS_FILE = "credits.json"
GEN_LOG_FILE = "gen_log.txt"
ORDERS_FILE = "orders.json"
HITRATE_FILE = "hitrate.json"

RESTOCK_CHANNEL_ID = 1474702726389567588
RESTOCK_ROLE_ID = 1475311889293774939
GEN_LOG_CHANNEL_ID = 1475984317581627402

PIX_KEY = "vhxzstore@gmail.com"
PIX_NAME = "VHXZ STORE"

GEN_COOLDOWN = 8
user_cooldowns = {}

# ================= JSON =================

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ================= HITRATE =================

def load_hitrate():
    if not os.path.exists(HITRATE_FILE):
        return {"total": 0, "robux": 0, "limited": 0, "rap_total": 0}
    return load_json(HITRATE_FILE)

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
    blocks = text.split("VIPER GEN RESULT")
    results = []

    for b in blocks:
        b = b.strip()
        if not b:
            continue

        tier = None
        if "Tier:" in b:
            tier = b.split("Tier:")[1].split("\n")[0].strip().lower()

        user = None
        if "User:" in b:
            user = b.split("User:")[1].split("\n")[0].strip()

        pwd = None
        if "Pass:" in b:
            pwd = b.split("Pass:")[1].split("\n")[0].strip()

        if "Robux:" in b:
            val = b.split("Robux:")[1].split("\n")[0]
            val = int("".join([c for c in val if c.isdigit()]))

            results.append(("robux", tier, val, user, pwd))

        elif "Limited:" in b:
            item = b.split("Limited:")[1].split("\n")[0].strip()

            rap = 0
            if "Value:" in b:
                line = b.split("Value:")[1].split("\n")[0]
                nums = "".join([c for c in line if c.isdigit()])
                if nums:
                    rap = int(nums)

            results.append(("limited", tier, item, rap, user, pwd))

    return results

def save_parsed_results(results):
    hit = load_hitrate()

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

        hit["total"] += 1

    save_hitrate(hit)

# ================= CREDITS =================

def add_credits(user_id, amount):
    data = load_json(CREDITS_FILE)
    data[str(user_id)] = data.get(str(user_id), 0) + amount
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

        # ===== PARSE PRODUTO =====
        if produto.startswith("ROBux:"):
            parts = produto.split("|")
            val = parts[0].split(":", 1)[1]
            userp = parts[1]
            passp = parts[2]

            texto = f"💰 Robux: {val}\n👤 User: {userp}\n🔑 Pass: {passp}"

        elif produto.startswith("LIMITED:"):
            parts = produto.split("|")
            item = parts[0].split(":", 1)[1]
            rap = parts[1]
            userp = parts[2]
            passp = parts[3]

            texto = f"🎩 Limited: {item}\n💎 RAP: {rap}\n👤 User: {userp}\n🔑 Pass: {passp}"
        else:
            texto = produto

        # ===== LOG =====
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
    embed = discord.Embed(
        title="VIPER GEN",
        description="Escolha o tier",
        color=0xff003c
    )

    for t in PRICES:
        embed.add_field(name=t.upper(), value=f"{PRICES[t]} credits", inline=False)

    await ctx.send(embed=embed, view=GenView())

@bot.command()
async def stats(ctx):
    gens = 0
    users = set()
    credits_spent = 0

    if os.path.exists(GEN_LOG_FILE):
        with open(GEN_LOG_FILE) as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) < 4:
                    continue
                _, user_id, tier, produto = parts
                gens += 1
                users.add(user_id)
                if tier in PRICES:
                    credits_spent += PRICES[tier]

    lucro = round(credits_spent * PRICE_PER_CREDIT, 2)

    embed = discord.Embed(title="VIPER STATS", color=0x00ffcc)
    embed.add_field(name="Users", value=len(users))
    embed.add_field(name="Generations", value=gens)
    embed.add_field(name="Credits Spent", value=credits_spent)
    embed.add_field(name="Revenue R$", value=lucro)

    await ctx.send(embed=embed)

@bot.command()
async def hitrate(ctx):
    hit = load_hitrate()
    if hit["total"] == 0:
        await ctx.send("Sem dados")
        return

    robux_pct = round(hit["robux"] / hit["total"] * 100, 1)
    limited_pct = round(hit["limited"] / hit["total"] * 100, 1)

    await ctx.send(
        f"HITRATE\nTotal: {hit['total']}\nRobux: {robux_pct}%\nLimited: {limited_pct}%\nRAP: {hit['rap_total']}"
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def restock(ctx, *, texto: str):
    parsed = parse_viper_blocks(texto)

    if not parsed:
        await ctx.send("Nada detectado")
        return

    save_parsed_results(parsed)

    canal = bot.get_channel(RESTOCK_CHANNEL_ID)
    if canal:
        ping = f"<@&{RESTOCK_ROLE_ID}> " if RESTOCK_ROLE_ID else ""
        await canal.send(f"{ping}RESTOCK: {len(parsed)}")

    await ctx.send(f"Restockado {len(parsed)}")

bot.run(TOKEN)
