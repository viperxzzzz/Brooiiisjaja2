import discord
from discord.ext import commands
import json
import threading
import os
import time
from datetime import datetime

TOKEN = os.getenv("TOKEN")
PREFIX = "!"

intents = discord.Intents.default() intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents) lock = threading.Lock()

================= CONFIG =================

PRICES = { "low": 3, "medium": 10, "high": 14 }

STOCK_FILES = { "low": "stock_low.txt", "medium": "stock_medium.txt", "high": "stock_high.txt" }

CREDITS_FILE = "credits.json" GEN_LOG_FILE = "gen_log.txt"

RESTOCK_CHANNEL_ID = 1475313284583260202 RESTOCK_ROLE_ID = 1475311889293774939 GEN_LOG_CHANNEL_ID = 1475984317581627402

GEN_COOLDOWN = 8 user_cooldowns = {}

================= CREDITS =================

def load_credits(): if not os.path.exists(CREDITS_FILE): return {} with open(CREDITS_FILE, "r") as f: try: return json.load(f) except: return {}

def save_credits(data): with open(CREDITS_FILE, "w") as f: json.dump(data, f, indent=4)

def add_credits(user_id, amount): data = load_credits() data[str(user_id)] = data.get(str(user_id), 0) + amount save_credits(data)

def get_credits(user_id): data = load_credits() return data.get(str(user_id), 0)

def remove_credits_amount(user_id, amount): data = load_credits() uid = str(user_id) if uid not in data or data[uid] < amount: return False data[uid] -= amount save_credits(data) return True

================= STOCK =================

def gerar_produto(tipo): file = STOCK_FILES[tipo]

with lock:
    if not os.path.exists(file):
        return None

    with open(file, "r") as f:
        linhas = [l.strip() for l in f if l.strip()]

    if not linhas:
        return None

    produto = linhas[0]
    linhas.pop(0)

    with open(file, "w") as f:
        f.write("\n".join(linhas))

    return produto

================= CYBER VIEW =================

class GenView(discord.ui.View): def init(self): super().init(timeout=None)

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

    if not produto:
        await interaction.response.send_message(
            "⚠️ OUT OF STOCK",
            ephemeral=True
        )
        return

    remove_credits_amount(user.id, price)
    user_cooldowns[user.id] = time.time()

    # LOG TXT
    with lock:
        with open(GEN_LOG_FILE, "a") as f:
            f.write(f"{datetime.utcnow()} | {user.id} | {tipo} | {produto}\n")

    # LOG DISCORD
    try:
        canal = bot.get_channel(GEN_LOG_CHANNEL_ID)
        if canal:
            await canal.send(
                f"🧾 GEN LOG\n"
                f"User: <@{user.id}>\n"
                f"Tier: {tipo.upper()}\n"
                f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
    except:
        pass

    try:
        await user.send(
            f"⛧ VIPER GEN ⛧\n"
            f"TIER: {tipo.upper()}\n"
            f"KEY: {produto}"
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

================= COMANDOS =================

@bot.command() async def credits(ctx): c = get_credits(ctx.author.id) await ctx.send(f"💳 {ctx.author.mention} você tem {c} créditos.")

@bot.command() @commands.has_permissions(administrator=True) async def addcredits(ctx, user: discord.Member, amount: int): add_credits(user.id, amount) await ctx.send(f"✅ {amount} créditos adicionados para {user.mention}.")

@bot.command() @commands.has_permissions(administrator=True) async def removecredits(ctx, user: discord.Member, amount: int): data = load_credits() uid = str(user.id)

if uid not in data or data[uid] < amount:
    await ctx.send("❌ Créditos insuficientes.")
    return

data[uid] -= amount
save_credits(data)

await ctx.send(f"➖ {amount} créditos removidos de {user.mention}.")

@bot.command() async def painel(ctx): embed = discord.Embed( title="⛧ V I P E R   G E N ⛧", description=( "ansi\n" "\u001b[2;31mNEURAL ACCOUNT GENERATOR v3.1\u001b[0m\n" "" "⚠️ Premium Roblox Account Market\n" "━━━━━━━━━━━━━━━━━━━\n" "💠 Possible hits:\n" "• Robux\n" "• Limiteds\n" "• Rare items\n" "• Old join\n" "━━━━━━━━━━━━━━━━━━━\n" "🧬 SELECT TIER" ), color=0xff003c )

embed.add_field(name="🔻 LOW", value="3 credits", inline=True)
embed.add_field(name="🔺 MEDIUM", value="10 credits", inline=True)
embed.add_field(name="💎 HIGH", value="14 credits", inline=True)

embed.set_footer(text="Viper Systems • CyberGen Division")

await ctx.send(embed=embed, view=GenView())

================= RESTOCK =================

@bot.command() @commands.has_permissions(administrator=True) async def restock(ctx, tipo: str, *, produtos: str): tipo = tipo.lower()

if tipo not in STOCK_FILES:
    await ctx.send("❌ Tipo inválido.")
    return

file = STOCK_FILES[tipo]
lista = [p.strip() for p in produtos.split("\n") if p.strip()]

if not lista:
    await ctx.send("❌ Nenhum produto válido.")
    return

with lock:
    with open(file, "a") as f:
        f.write("\n".join(lista) + "\n")

await ctx.send(f"✅ {len(lista)} adicionados ao {tipo}.")

try:
    canal = bot.get_channel(RESTOCK_CHANNEL_ID)
    if canal:
        ping = f"<@&{RESTOCK_ROLE_ID}> " if RESTOCK_ROLE_ID else ""
        await canal.send(
            f"{ping}🔔 RESTOCK\n"
            f"Tier: {tipo.upper()}\n"
            f"Qty: {len(lista)}\n"
            f"By: {ctx.author.mention}"
        )
except:
    pass

================= STOCK =================

@bot.command() @commands.has_permissions(administrator=True) async def stock(ctx, tipo: str = None): if tipo: tipo = tipo.lower() if tipo not in STOCK_FILES: await ctx.send("❌ Tipo inválido.") return

file = STOCK_FILES[tipo]
    if not os.path.exists(file):
        await ctx.send("0")
        return

    with open(file, "r") as f:
        linhas = [l.strip() for l in f if l.strip()]

    await ctx.send(f"📦 {tipo.upper()} ({len(linhas)}):\n" + "\n".join(linhas[:50]))
    return

msg = "📦 STOCK:\n"
for t, file in STOCK_FILES.items():
    if not os.path.exists(file):
        qtd = 0
    else:
        with open(file) as f:
            qtd = len([l for l in f if l.strip()])
    msg += f"{t.upper()}: {qtd}\n"

await ctx.send(msg)

================= RUN =================

bot.run(TOKEN)
