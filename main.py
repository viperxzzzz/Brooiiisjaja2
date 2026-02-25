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

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
help_command=None)
lock = threading.Lock()

# ================= CONFIG =================

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

RESTOCK_CHANNEL_ID = 1475313284583260202
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

# ================= ODDS =================

def roll_hit(tier):
    r = random.randint(1, 100)
    acc = 0
    for k, v in ODDS[tier].items():
        acc += v
        if r <= acc:
            return k
    return "clean"

# ================= ORDER SYSTEM =================

def create_order(user_id, credits):
    orders = load_json(ORDERS_FILE)
    oid = f"VX-{random.randint(1000,9999)}"
    total = round(credits * PRICE_PER_CREDIT, 2)

    orders[oid] = {
        "user": user_id,
        "credits": credits,
        "total": total,
        "status": "waiting",
        "time": str(datetime.utcnow())
    }

    save_json(ORDERS_FILE, orders)
    return oid, total

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
            restante = int(GEN_COOLDOWN - (now - last))
            await interaction.response.send_message(
                f"⏳ Cooldown {restante}s",
                ephemeral=True
            )
            return

        if get_credits(user.id) < price:
            await interaction.response.send_message(
                f"❌ Need {price} credits",
                ephemeral=True
            )
            return

        produto = gerar_produto(tipo)
        hit = roll_hit(tipo)

        if not produto:
            await interaction.response.send_message(
                "⚠️ OUT OF STOCK",
                ephemeral=True
            )
            return

        remove_credits(user.id, price)
        user_cooldowns[user.id] = time.time()

        # ===== LOG TXT =====
        with lock:
            with open(GEN_LOG_FILE, "a") as f:
                f.write(f"{datetime.utcnow()} | {user.id} | {tipo} | {hit} | {produto}\n")

        # ===== LOG CANAL =====
        canal = bot.get_channel(GEN_LOG_CHANNEL_ID)
        if canal:
            await canal.send(
                f"🧾 GEN\n"
                f"User: <@{user.id}>\n"
                f"Tier: {tipo.upper()}\n"
                f"Hit: {hit}\n"
                f"Key: {produto}"
            )

        # ===== DM USER =====
        try:
            await user.send(
                f"⛧ VIPER GEN ⛧\n"
                f"🛒 Produto: {tipo.upper()}\n"
                f"🎯 Hit: {hit}\n"
                f"🔑 {produto}"
            )
            await interaction.response.send_message(
                "✔ Delivered",
                ephemeral=True
            )
        except:
            await interaction.response.send_message(
                "❌ Enable DM",
                ephemeral=True
            )

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
async def credits(ctx):
    c = get_credits(ctx.author.id)
    await ctx.send(f"💳 {ctx.author.mention} você tem {c} créditos.")

@bot.command()
async def buycredits(ctx, amount: int):
    oid, total = create_order(ctx.author.id, amount)
    await ctx.send(
        f"ORDER {oid}\nCredits: {amount}\nTotal: R${total}\n\nPIX: {PIX_KEY}\nTitular: {PIX_NAME}\n\nStatus: WAITING PAYMENT"
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def confirm(ctx, order_id: str):
    orders = load_json(ORDERS_FILE)
    if order_id not in orders:
        await ctx.send("❌ Pedido não encontrado.")
        return

    order = orders[order_id]
    if order["status"] == "paid":
        await ctx.send("Já confirmado.")
        return

    add_credits(order["user"], order["credits"])
    order["status"] = "paid"
    save_json(ORDERS_FILE, orders)

    await ctx.send(f"✅ Pedido {order_id} confirmado.")

    user = await bot.fetch_user(order["user"])
    try:
        await user.send(f"💰 Créditos adicionados: {order['credits']}")
    except:
        pass

@bot.command()
async def painel(ctx):
    embed = discord.Embed(
        title="⛧ V I P E R   G E N ⛧",
        description="THE BEST ROBLOX ACCOUNT GENERATOR",
        color=0xff003c
    )

    for tier in ["low", "medium", "high"]:
        odds = ODDS[tier]
        txt = (
            f"💰 Robux: {odds['robux']}%\n"
            f"📦 Limited: {odds['limited']}%\n"
            f"✨ Rare: {odds['rare']}%\n"
            f"🧼 Clean: {odds['clean']}%"
        )
        embed.add_field(
            name=f"{tier.upper()} — {PRICES[tier]} credits",
            value=txt,
            inline=False
        )

    await ctx.send(embed=embed, view=GenView())

@bot.command()
@commands.has_permissions(administrator=True)
async def restock(ctx, tipo: str, *, produtos: str):
    tipo = tipo.lower()
    if tipo not in STOCK_FILES:
        await ctx.send("Tipo inválido")
        return

    lista = [p.strip() for p in produtos.split("\n") if p.strip()]
    with lock:
        with open(STOCK_FILES[tipo], "a") as f:
            f.write("\n".join(lista) + "\n")

    canal = bot.get_channel(RESTOCK_CHANNEL_ID)
    if canal:
        ping = f"<@&{RESTOCK_ROLE_ID}> " if RESTOCK_ROLE_ID else ""
        await canal.send(
            f"{ping}🔔 RESTOCK {tipo.upper()} | {len(lista)}"
        )

    await ctx.send("Restock OK")

@bot.command()
async def stock(ctx, tipo: str = None):
    if tipo:
        tipo = tipo.lower()
        if tipo not in STOCK_FILES:
            await ctx.send("Tipo inválido")
            return
        file = STOCK_FILES[tipo]
        if not os.path.exists(file):
            await ctx.send("0")
            return
        with open(file) as f:
            linhas = [l for l in f if l.strip()]
        await ctx.send(f"{tipo.upper()}: {len(linhas)}")
        return

    msg = "STOCK:\n"
    for t, file in STOCK_FILES.items():
        if not os.path.exists(file):
            qtd = 0
        else:
            with open(file) as f:
                qtd = len([l for l in f if l.strip()])
        msg += f"{t.upper()}: {qtd}\n"
    await ctx.send(msg)

@bot.command()
async def stats(ctx):
    gens = 0
    users = set()
    tier_count = {"low": 0, "medium": 0, "high": 0}
    credits_spent = 0

    if os.path.exists(GEN_LOG_FILE):
        with open(GEN_LOG_FILE, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) < 5:
                    continue
                _, user_id, tier, hit, key = [p.strip() for p in parts]
                gens += 1
                users.add(user_id)
                if tier in tier_count:
                    tier_count[tier] += 1
                    credits_spent += PRICES[tier]

    total_users = len(users)
    lucro = round(credits_spent * PRICE_PER_CREDIT, 2)

    top_tier = max(tier_count, key=tier_count.get).upper() if gens > 0 else "N/A"

    embed = discord.Embed(
        title="⛧ VIPER ANALYTICS ⛧",
        color=0x00ffe1
    )

    embed.add_field(name="Users", value=str(total_users))
    embed.add_field(name="Generations", value=str(gens))
    embed.add_field(name="Credits Spent", value=str(credits_spent))
    embed.add_field(name="Revenue (R$)", value=str(lucro))
    embed.add_field(name="Top Tier", value=top_tier)

    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="⛧ VIPER SYSTEM HELP ⛧",
        description="Command Matrix • Neural Interface",
        color=0xff003c
    )

    embed.add_field(
        name="👤 USER",
        value=(
            "`!painel` • abrir gerador\n"
            "`!credits` • ver saldo\n"
            "`!buycredits <qtd>` • comprar créditos"
        ),
        inline=False
    )

    embed.add_field(
        name="🛠️ ADMIN",
        value=(
            "`!restock <tier>` • adicionar stock\n"
            "`!stock [tier]` • ver estoque\n"
            "`!confirm <order>` • confirmar pagamento\n"
            "`!orderinfo <id>` • info pedido"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 ANALYTICS",
        value=(
            "`!stats` • visão geral\n"
            "`!economy` • financeiro\n"
            "`!leaderboard` • top usuários\n"
            "`!userstats <user>` • stats usuário\n"
            "`!hitrate` • taxa de hits"
        ),
        inline=False
    )

    embed.set_footer(text="Viper Systems • Command Matrix")

    await ctx.send(embed=embed)
# ================= RUN =================

bot.run(TOKEN)
