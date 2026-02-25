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

def load_hitrate():
    if not os.path.exists(HITRATE_FILE):
        return {"total": 0, "robux": 0, "limited": 0, "rap_total": 0}
    return load_json(HITRATE_FILE)

def save_hitrate(data):
    save_json(HITRATE_FILE, data)

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
                nums = "".join([c for c in line if c.isdigit()])
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

# ================= SAVE RESTOCK =================

def save_parsed_results(results):
    hit = load_hitrate()
    count_by_tier = {"low":0,"medium":0,"high":0}

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
        count_by_tier[tier]+=1

    save_hitrate(hit)
    return count_by_tier

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

# ================= ORDER =================

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

        texto_entrega = (
            f"💰 Robux: {val}\n"
            f"👤 User: {userp}\n"
            f"🔑 Pass: {passp}"
        )

    elif produto.startswith("LIMITED:"):
        parts = produto.split("|")
        item = parts[0].split(":", 1)[1]
        rap = parts[1]
        userp = parts[2]
        passp = parts[3]

        texto_entrega = (
            f"🎩 Limited: {item}\n"
            f"💎 RAP: {rap}\n"
            f"👤 User: {userp}\n"
            f"🔑 Pass: {passp}"
        )
    else:
        texto_entrega = produto

    # ===== LOG =====
    with lock:
        with open(GEN_LOG_FILE, "a") as f:
            f.write(f"{datetime.utcnow()}|{user.id}|{tipo}|{produto}\n")

    canal = bot.get_channel(GEN_LOG_CHANNEL_ID)
    if canal:
        await canal.send(
            f"GEN\nUser: <@{user.id}>\nTier: {tipo.upper()}\n{texto_entrega}"
        )

    # ===== DM =====
    try:
        await user.send(
            f"VIPER GEN\nProduto: {tipo.upper()}\n\n{texto_entrega}"
        )
        await interaction.response.send_message("✔ Entregue", ephemeral=True)
    except:
        await interaction.response.send_message("❌ DM fechada", ephemeral=True)

# ================= COMMANDS =================

@bot.command()
async def painel(ctx):
    embed = discord.Embed(
        title="VIPER GEN",
        description="Roblox Account Generator",
        color=0xff003c
    )

    embed.add_field(name="LOW", value=f"{PRICES['low']} credits")
    embed.add_field(name="MEDIUM", value=f"{PRICES['medium']} credits")
    embed.add_field(name="HIGH", value=f"{PRICES['high']} credits")

    await ctx.send(embed=embed, view=GenView())

@bot.command()
async def credits(ctx):
    c = get_credits(ctx.author.id)
    await ctx.send(f"Você tem {c} créditos")

@bot.command()
@commands.has_permissions(administrator=True)
async def addcredits(ctx, user: discord.Member, amount: int):
    add_credits(user.id, amount)
    await ctx.send(f"{amount} créditos adicionados para {user.mention}")

@bot.command()
async def buycredits(ctx, amount: int):
    oid, total = create_order(ctx.author.id, amount)
    await ctx.send(
        f"Pedido: {oid}\nCréditos: {amount}\nTotal: R${total}\nPIX: {PIX_KEY}"
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def confirm(ctx, order_id: str):
    orders = load_json(ORDERS_FILE)
    if order_id not in orders:
        await ctx.send("Pedido não encontrado")
        return

    order = orders[order_id]
    if order["status"] == "paid":
        await ctx.send("Já pago")
        return

    add_credits(order["user"], order["credits"])
    order["status"] = "paid"
    save_json(ORDERS_FILE, orders)

    await ctx.send("Pagamento confirmado")

@bot.command()
@commands.has_permissions(administrator=True)
async def restock(ctx, *, texto: str):
    parsed = parse_viper_blocks(texto)
    if not parsed:
        await ctx.send("Nenhum bloco detectado")
        return

    counts = save_parsed_results(parsed)
    total = sum(counts.values())

    canal = bot.get_channel(RESTOCK_CHANNEL_ID)
    if canal:
        ping = f"<@&{RESTOCK_ROLE_ID}> " if RESTOCK_ROLE_ID else ""
        await canal.send(
            f"{ping}RESTOCK\nLOW: {counts['low']} | MEDIUM: {counts['medium']} | HIGH: {counts['high']}"
        )

    await ctx.send(f"Restockado: {total}")

@bot.command()
async def stock(ctx, tipo: str=None):
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

    msg = ""
    for t,file in STOCK_FILES.items():
        if not os.path.exists(file):
            qtd=0
        else:
            with open(file) as f:
                qtd=len([l for l in f if l.strip()])
        msg += f"{t.upper()}: {qtd}\n"
    await ctx.send(msg)

@bot.command()
async def stats(ctx):
    gens=0
    users=set()
    tier_count={"low":0,"medium":0,"high":0}
    credits_spent=0

    if os.path.exists(GEN_LOG_FILE):
        with open(GEN_LOG_FILE) as f:
            for line in f:
                parts=line.strip().split("|")
                if len(parts)<4:
                    continue
                _,user_id,tier,_=parts
                gens+=1
                users.add(user_id)
                if tier in tier_count:
                    tier_count[tier]+=1
                    credits_spent+=PRICES[tier]

    lucro=round(credits_spent*PRICE_PER_CREDIT,2)
    top=max(tier_count,key=tier_count.get).upper() if gens>0 else "N/A"

    embed=discord.Embed(title="VIPER ANALYTICS",color=0x00ffcc)
    embed.add_field(name="Users",value=len(users))
    embed.add_field(name="Generations",value=gens)
    embed.add_field(name="Credits",value=credits_spent)
    embed.add_field(name="Revenue R$",value=lucro)
    embed.add_field(name="Top Tier",value=top)

    await ctx.send(embed=embed)

@bot.command()
async def hitrate(ctx):
    hit=load_hitrate()
    if hit["total"]==0:
        await ctx.send("Sem dados")
        return

    robux_pct=round(hit["robux"]/hit["total"]*100,1)
    limited_pct=round(hit["limited"]/hit["total"]*100,1)

    await ctx.send(
        f"Total: {hit['total']}\n"
        f"Robux: {hit['robux']} ({robux_pct}%)\n"
        f"Limited: {hit['limited']} ({limited_pct}%)\n"
        f"RAP: {hit['rap_total']}"
    )

# ================= RUN =================

bot.run(TOKEN)
