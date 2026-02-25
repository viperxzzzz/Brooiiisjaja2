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

BRAND = "⛧ VIPER GEN ⛧"

PRICES = {"low": 3, "medium": 10, "high": 14}
PRICE_PER_CREDIT = 0.35

STOCK_FILES = {
    "low": "stock_low.txt",
    "medium": "stock_medium.txt",
    "high": "stock_high.txt"
}

ODDS = {
    "low": {"robux": 8, "limited": 2, "rare": 5, "clean": 85},
    "medium": {"robux": 20, "limited": 8, "rare": 12, "clean": 60},
    "high": {"robux": 38, "limited": 18, "rare": 22, "clean": 22}
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

# ================= UTILS =================

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

def load_hitrate():
    if not os.path.exists(HITRATE_FILE):
        return {"total": 0, "robux": 0, "limited": 0, "rap_total": 0}
    with open(HITRATE_FILE, "r") as f:
        return json.load(f)

def save_hitrate(data):
    with open(HITRATE_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ================= PARSER =================

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
            val = int("".join(c for c in val if c.isdigit()))
            results.append({
                "tipo": "robux",
                "valor": val,
                "tier": tier,
                "user": user,
                "pass": pwd
            })

        elif "Limited:" in b:
            item = b.split("Limited:")[1].split("\n")[0].strip()
            rap = 0
            if "Value:" in b:
                line = b.split("Value:")[1].split("\n")[0]
                nums = "".join(c for c in line if c.isdigit())
                if nums:
                    rap = int(nums)

            results.append({
                "tipo": "limited",
                "item": item,
                "rap": rap,
                "tier": tier,
                "user": user,
                "pass": pwd
            })

    return results

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

def save_parsed_results(results):
    hit = load_hitrate()
    tier_counts = {"low": 0, "medium": 0, "high": 0}

    for r in results:
        tier = r["tier"]
        if tier not in STOCK_FILES:
            continue

        if r["tipo"] == "robux":
            line = f"ROBux:{r['valor']}|{r['user']}|{r['pass']}"
            hit["robux"] += 1
        else:
            line = f"LIMITED:{r['item']}|{r['rap']}|{r['user']}|{r['pass']}"
            hit["limited"] += 1
            hit["rap_total"] += r["rap"]

        with lock:
            with open(STOCK_FILES[tier], "a") as f:
                f.write(line + "\n")

        hit["total"] += 1
        tier_counts[tier] += 1

    save_hitrate(hit)
    return tier_counts

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

# ================= GEN =================

def roll_hit(tier):
    r = random.randint(1, 100)
    acc = 0
    for k, v in ODDS[tier].items():
        acc += v
        if r <= acc:
            return k
    return "clean"

class GenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def process(self, interaction, tipo):
        user = interaction.user
        price = PRICES[tipo]

        now = time.time()
        last = user_cooldowns.get(user.id, 0)

        if now - last < GEN_COOLDOWN:
            await interaction.response.send_message("⏳ Cooldown ativo", ephemeral=True)
            return

        if get_credits(user.id) < price:
            await interaction.response.send_message("❌ Créditos insuficientes", ephemeral=True)
            return

        produto = gerar_produto(tipo)
        hit = roll_hit(tipo)

        if not produto:
            await interaction.response.send_message("⚠️ OUT OF STOCK", ephemeral=True)
            return

        remove_credits(user.id, price)
        user_cooldowns[user.id] = time.time()

        with lock:
            with open(GEN_LOG_FILE, "a") as f:
                f.write(f"{datetime.utcnow()} | {user.id} | {tipo} | {hit} | {produto}\n")

        canal = bot.get_channel(GEN_LOG_CHANNEL_ID)
        if canal:
            await canal.send(
                f"{BRAND}\nUser: <@{user.id}>\nTier: {tipo.upper()}\nHit: {hit}\nKey: {produto}"
            )

        try:
            await user.send(
                f"{BRAND}\nProduto: {tipo.upper()}\nHit: {hit}\nKey: {produto}"
            )
            await interaction.response.send_message("✔ Entregue", ephemeral=True)
        except:
            await interaction.response.send_message("❌ Ative DM", ephemeral=True)

    @discord.ui.button(label="LOW", style=discord.ButtonStyle.danger)
    async def low(self, i, b): await self.process(i, "low")

    @discord.ui.button(label="MEDIUM", style=discord.ButtonStyle.primary)
    async def medium(self, i, b): await self.process(i, "medium")

    @discord.ui.button(label="HIGH", style=discord.ButtonStyle.success)
    async def high(self, i, b): await self.process(i, "high")

# ================= COMMANDS =================

@bot.command()
async def painel(ctx):
    embed = discord.Embed(title=BRAND, color=0xff003c)
    for tier in PRICES:
        o = ODDS[tier]
        txt = f"💰 {o['robux']}%\n📦 {o['limited']}%\n✨ {o['rare']}%\n🧼 {o['clean']}%"
        embed.add_field(name=f"{tier.upper()} — {PRICES[tier]} créditos", value=txt)
    await ctx.send(embed=embed, view=GenView())

@bot.command()
async def credits(ctx):
    await ctx.send(f"💳 {ctx.author.mention} créditos: {get_credits(ctx.author.id)}")

@bot.command()
async def buycredits(ctx, amount: int):
    oid = f"VX-{random.randint(1000,9999)}"
    total = round(amount * PRICE_PER_CREDIT, 2)

    orders = load_json(ORDERS_FILE)
    orders[oid] = {
        "user": ctx.author.id,
        "credits": amount,
        "total": total,
        "status": "waiting"
    }
    save_json(ORDERS_FILE, orders)

    await ctx.send(
        f"{BRAND}\nORDER {oid}\nCréditos: {amount}\nTotal: R${total}\nPIX: {PIX_KEY}"
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def confirm(ctx, order_id: str):
    orders = load_json(ORDERS_FILE)
    if order_id not in orders:
        await ctx.send("Pedido não encontrado")
        return

    o = orders[order_id]
    if o["status"] == "paid":
        await ctx.send("Já pago")
        return

    add_credits(o["user"], o["credits"])
    o["status"] = "paid"
    save_json(ORDERS_FILE, orders)

    await ctx.send(f"Confirmado {order_id}")

    user = await bot.fetch_user(o["user"])
    try:
        await user.send(f"{BRAND}\nCréditos: {o['credits']}")
    except:
        pass

@bot.command()
@commands.has_permissions(administrator=True)
async def restock(ctx, *, texto: str):
    parsed = parse_viper_blocks(texto)
    if not parsed:
        await ctx.send("Nada detectado")
        return

    tier_counts = save_parsed_results(parsed)

    await ctx.send(f"{BRAND}\nRestock: {len(parsed)} contas")

    canal = bot.get_channel(RESTOCK_CHANNEL_ID)
    if canal:
        msg = f"{BRAND}\n"
        for t, c in tier_counts.items():
            if c:
                msg += f"{t.upper()}: {c}\n"

        ping = f"<@&{RESTOCK_ROLE_ID}>\n" if RESTOCK_ROLE_ID else ""
        await canal.send(ping + msg)

@bot.command()
async def stock(ctx, tipo: str = None):
    if tipo:
        tipo = tipo.lower()
        if tipo not in STOCK_FILES:
            await ctx.send("Tipo inválido")
            return
        f = STOCK_FILES[tipo]
        qtd = 0
        if os.path.exists(f):
            with open(f) as arq:
                qtd = len([l for l in arq if l.strip()])
        await ctx.send(f"{tipo.upper()}: {qtd}")
        return

    msg = "STOCK\n"
    for t, f in STOCK_FILES.items():
        qtd = 0
        if os.path.exists(f):
            with open(f) as arq:
                qtd = len([l for l in arq if l.strip()])
        msg += f"{t.upper()}: {qtd}\n"
    await ctx.send(msg)

@bot.command()
async def stats(ctx):
    gens = 0
    users = set()
    credits_spent = 0
    tier_count = {"low": 0, "medium": 0, "high": 0}

    if os.path.exists(GEN_LOG_FILE):
        with open(GEN_LOG_FILE) as f:
            for line in f:
                p = line.split("|")
                if len(p) < 5:
                    continue
                _, uid, tier, _, _ = [x.strip() for x in p]
                gens += 1
                users.add(uid)
                if tier in tier_count:
                    tier_count[tier] += 1
                    credits_spent += PRICES[tier]

    lucro = round(credits_spent * PRICE_PER_CREDIT, 2)
    top = max(tier_count, key=tier_count.get).upper() if gens else "N/A"

    e = discord.Embed(title="⛧ VIPER ANALYTICS ⛧", color=0x00ffe1)
    e.add_field(name="Users", value=len(users))
    e.add_field(name="Generations", value=gens)
    e.add_field(name="Credits", value=credits_spent)
    e.add_field(name="Revenue", value=lucro)
    e.add_field(name="Top Tier", value=top)

    await ctx.send(embed=e)

@bot.command()
async def hitrate(ctx):
    hit = load_hitrate()
    if hit["total"] == 0:
        await ctx.send("Sem dados")
        return

    robux_pct = round(hit["robux"] / hit["total"] * 100, 1)
    limited_pct = round(hit["limited"] / hit["total"] * 100, 1)

    await ctx.send(
        f"{BRAND}\nTotal: {hit['total']}\nRobux: {robux_pct}%\nLimited: {limited_pct}%\nRAP: {hit['rap_total']}"
    )

@bot.command()
async def help(ctx):
    txt = (
        "**USER**\n"
        "!painel\n!credits\n!buycredits <qtd>\n\n"
        "**ADMIN**\n"
        "!restock\n!stock [tier]\n!confirm <id>\n\n"
        "**DATA**\n"
        "!stats\n!hitrate"
    )
    await ctx.send(f"{BRAND}\n{txt}")

# ================= RUN =================

bot.run(TOKEN)
