import discord
from discord.ext import commands
import json
import threading
import os
import time
from datetime import datetime
import random

# ================= CONFIGURAÇÕES =================
TOKEN = os.getenv("TOKEN")
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
lock = threading.Lock()  # para evitar conflito de escrita em arquivos

# ===== Preços, créditos e arquivos =====
PRICES = {"low": 3, "medium": 10, "high": 14}  # preço em créditos por tier
GUILD_ID = 1463315641871106131
TOPUP_CHANNEL_ID = 1471541921292878058
PRICE_PER_CREDIT = 0.35  # R$ por crédito

STOCK_FILES = {
    "low": "stock_low.txt",
    "medium": "stock_medium.txt",
    "high": "stock_high.txt"
}

CREDITS_FILE = "credits.json"
ORDERS_FILE = "orders.json"
GEN_LOG_FILE = "gen_log.txt"

RESTOCK_CHANNEL_ID = 1474702726389567588
RESTOCK_ROLE_ID = 1475311889293774939
GEN_LOG_CHANNEL_ID = 1475984317581627402

GEN_COOLDOWN = 8  # segundos entre gerações para o mesmo usuário
user_cooldowns = {}

PIX_KEY = "vhxzstore@gmail.com"
PIX_NAME = "VHXZ STORE"

# ================= FUNÇÕES DE JSON =================
def load_json(path):
    """Carrega um arquivo JSON, retorna {} se não existir ou erro."""
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_json(path, data):
    """Salva um dicionário em arquivo JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ================= FUNÇÕES DE CRÉDITOS =================
def add_credits(user_id, amount):
    """Adiciona créditos a um usuário."""
    data = load_json(CREDITS_FILE)
    data[str(user_id)] = data.get(str(user_id), 0) + amount
    save_json(CREDITS_FILE, data)

def get_credits(user_id):
    """Retorna créditos de um usuário."""
    data = load_json(CREDITS_FILE)
    return data.get(str(user_id), 0)

def remove_credits(user_id, amount):
    """Remove créditos, retorna False se não tiver saldo suficiente."""
    data = load_json(CREDITS_FILE)
    uid = str(user_id)
    if data.get(uid, 0) < amount:
        return False
    data[uid] -= amount
    save_json(CREDITS_FILE, data)
    return True

# ================= FUNÇÕES DE STOCK =================
def gerar_produto(tipo):
    """Pega a primeira conta do stock e remove do arquivo."""
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

def stock_count(tipo):
    file = STOCK_FILES[tipo]
    if not os.path.exists(file):
        return 0
    with open(file, "r") as f:
        return len([l for l in f if l.strip()])

# ================= ORDERS =================
def create_order(user_id, credits):
    """Cria um pedido de créditos para pagamento."""
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
    """View do Discord com botões para gerar LOW, MEDIUM e HIGH."""

    def __init__(self):
        super().__init__(timeout=None)

    async def process(self, interaction, tipo):
        user = interaction.user
        price = PRICES[tipo]

        now = time.time()
        last = user_cooldowns.get(user.id, 0)
        if now - last < GEN_COOLDOWN:
            await interaction.response.send_message(f"⏳ Cooldown {int(GEN_COOLDOWN - (now - last))}s", ephemeral=True)
            return

        if get_credits(user.id) < price:
            await interaction.response.send_message("❌ Sem créditos suficientes", ephemeral=True)
            return

        produto = gerar_produto(tipo)
        if not produto:
            await interaction.response.send_message("⚠️ Sem stock", ephemeral=True)
            return

        remove_credits(user.id, price)
        user_cooldowns[user.id] = time.time()

        # LOG DE GERAÇÃO
        with lock:
            with open(GEN_LOG_FILE, "a") as f:
                f.write(f"{datetime.utcnow()}|{user.id}|{tipo}|{produto}\n")

        canal = bot.get_channel(GEN_LOG_CHANNEL_ID)
        if canal:
            await canal.send(f"GEN\nUser: <@{user.id}>\nTier: {tipo.upper()}\n{produto}")

        try:
            await user.send(f"VIPER GEN\nTier: {tipo.upper()}\n{produto}")
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

class MainPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        # botão Top-Up manual
        self.add_item(
            discord.ui.Button(
                label="Top-Up",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{GUILD_ID}/{TOPUP_CHANNEL_ID}"
            )
        )

    @discord.ui.button(label="Generate", style=discord.ButtonStyle.success)
    async def generate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🎯 Escolha o tier:",
            view=GenView(),
            ephemeral=True
        )

    @discord.ui.button(label="Your Credits", style=discord.ButtonStyle.primary)
    async def credits_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        credits = get_credits(interaction.user.id)
        await interaction.response.send_message(
            f"💳 Seus créditos atuais: **{credits}**",
            ephemeral=True
        )


# ================= COMANDOS =================
@bot.command()
async def painel(ctx):
    embed = discord.Embed(
        title="🦂 VIPER GEN",
        description="The real best guaranteed quality Roblox account generator \n\n With Viper, you can usually hit **Robux, valuable games items, RAP, ageds** and much more.\n\n Escolha uma opção abaixo.",
        color=0xff003c
    )

    embed.add_field(
        name="LOW",
        value=f"{PRICES['low']} credits | Stock: {stock_count('low')}",
        inline=False
    )

    embed.add_field(
        name="MEDIUM",
        value=f"{PRICES['medium']} credits | Stock: {stock_count('medium')}",
        inline=False
    )

    embed.add_field(
        name="HIGH",
        value=f"{PRICES['high']} credits | Stock: {stock_count('high')}",
        inline=False
    )

    embed.set_footer(text="VHXZ • Instant Delivery")

    await ctx.send(embed=embed, view=MainPanel())

@bot.command()
async def credits(ctx):
    """Mostra os créditos do usuário."""
    c = get_credits(ctx.author.id)
    await ctx.send(f"💳 {ctx.author.mention} você tem {c} créditos")

@bot.command()
@commands.has_permissions(administrator=True)
async def addcredits(ctx, member: discord.Member, amount: int):
    """Adiciona créditos para um usuário (admin)."""
    add_credits(member.id, amount)
    await ctx.send(f"✅ Adicionados {amount} créditos para {member.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def buycredits(ctx, amount: int):
    """Cria pedido de compra de créditos (admin)."""
    oid, total = create_order(ctx.author.id, amount)
    await ctx.send(
        f"ORDER {oid}\nCredits: {amount}\nTotal: R${total}\n\nPIX: {PIX_KEY}\nTitular: {PIX_NAME}\nStatus: WAITING PAYMENT"
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def confirm(ctx, order_id: str):
    """Confirma pedido de créditos e adiciona ao usuário."""
    orders = load_json(ORDERS_FILE)
    if order_id not in orders:
        await ctx.send("❌ Pedido não encontrado")
        return

    order = orders[order_id]
    if order["status"] == "paid":
        await ctx.send("✅ Pedido já confirmado")
        return

    add_credits(order["user"], order["credits"])
    order["status"] = "paid"
    save_json(ORDERS_FILE, orders)

    await ctx.send(f"✅ Pedido {order_id} confirmado")
    user = await bot.fetch_user(order["user"])
    try:
        await user.send(f"💰 Créditos adicionados: {order['credits']}")
    except:
        pass

@bot.command()
async def historic(ctx):
    """Mostra todos os pedidos já feitos, com status."""
    orders = load_json(ORDERS_FILE)
    if not orders:
        await ctx.send("Nenhum pedido registrado")
        return

    msg = "**HISTÓRICO DE PEDIDOS**\n"
    for oid, o in orders.items():
        msg += f"ID: {oid} | User: <@{o['user']}> | Credits: {o['credits']} | Total: R${o['total']} | Status: {o['status']} | Time: {o['time']}\n"
    await ctx.send(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def restock(ctx, tipo: str, *, produtos: str):
    """Adiciona stock de um único tipo e avisa no canal."""
    tipo = tipo.lower()
    if tipo not in STOCK_FILES:
        await ctx.send("Tipo inválido")
        return

    lista = [l.strip() for l in produtos.split("\n") if l.strip()]
    if not lista:
        await ctx.send("Nenhum produto detectado")
        return

    with lock:
        with open(STOCK_FILES[tipo], "a") as f:
            f.write("\n".join(lista) + "\n")

    canal = bot.get_channel(RESTOCK_CHANNEL_ID)
    if canal:
        ping = f"<@&{RESTOCK_ROLE_ID}> " if RESTOCK_ROLE_ID else ""
        await canal.send(f"{ping}RESTOCK {tipo.upper()} | {len(lista)}")

    await ctx.send(f"✅ Restock {tipo.upper()} | {len(lista)}")

@bot.command()
async def stock(ctx, tipo: str = None):
    """Mostra quantidade de contas em stock."""
    if tipo:
        tipo = tipo.lower()
        if tipo not in STOCK_FILES:
            await ctx.send("Tipo inválido")
            return
        file = STOCK_FILES[tipo]
        if not os.path.exists(file):
            await ctx.send(f"{tipo.upper()}: 0")
            return
        with open(file) as f:
            linhas = [l for l in f if l.strip()]
        await ctx.send(f"{tipo.upper()}: {len(linhas)}")
        return

    # Se não especificou tipo, mostra todos
    msg = "STOCK:\n"
    for t, file in STOCK_FILES.items():
        if not os.path.exists(file):
            qtd = 0
        else:
            with open(file) as f:
                qtd = len([l for l in f if l.strip()])
        msg += f"{t.upper()}: {qtd}\n"
    await ctx.send(msg)

bot.run(TOKEN)
