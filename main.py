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

STOCK_FOLDER = "stocks"
os.makedirs(STOCK_FOLDER, exist_ok=True)

CREDITS_FILE = "credits.json"
ORDERS_FILE = "orders.json"
GEN_LOG_FILE = "gen_log.txt"

RESTOCK_CHANNEL_ID = 1474702726389567588
RESTOCK_ROLE_ID = 1475311889293774939
GEN_LOG_CHANNEL_ID = 1475984317581627402
PANEL_MESSAGE_ID = 1478301494431322173
PANEL_CHANNEL_ID = 1471646039604723805

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
    file = f"{STOCK_FOLDER}/{tipo}.txt"

    with lock:
        if not os.path.exists(file):
            return None

        with open(file) as f:
            linhas = [l.strip() for l in f if l.strip()]

        if not linhas:
            return None

        produto = random.choice(linhas)
        linhas.remove(produto)

        with open(file, "w") as f:
            f.write("\n".join(linhas) + "\n")

        return produto

def stock_count(tipo):
    file = f"{STOCK_FOLDER}/{tipo}.txt"

    if not os.path.exists(file):
        return 0

    with open(file) as f:
        return len([l for l in f if l.strip()])

def get_categories():
    files = os.listdir(STOCK_FOLDER)
    return [f.replace(".txt","") for f in files if f.endswith(".txt")]

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
class GenDropdown(discord.ui.Select):

    def __init__(self):

        categorias = get_categories()
        options = []

        for cat in categorias:

            qtd = stock_count(cat)

            # não mostrar categorias sem stock
            if qtd == 0:
                continue

            options.append(
    discord.SelectOption(
        label=f"{cat.upper()} — {PRICES.get(cat,0)} credits",
        description=f"Stock: {qtd}",
        value=cat
    )
)

        # caso todas categorias estejam sem stock
        if not options:
            options.append(
                discord.SelectOption(
                    label="SEM STOCK",
                    description="Nenhuma categoria disponível",
                    value="none"
                )
            )

        super().__init__(
            placeholder="🎯 Select a category",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        if self.values[0] == "none":
            await interaction.response.send_message(
                "⚠️ Nenhuma categoria disponível",
                ephemeral=True
            )
            return

        categoria = self.values[0]
        user = interaction.user
        price = PRICES.get(categoria, 5)

        now = time.time()
        last = user_cooldowns.get(user.id, 0)

        if now - last < GEN_COOLDOWN:
            await interaction.response.send_message(
                f"⏳ Cooldown {int(GEN_COOLDOWN - (now - last))}s",
                ephemeral=True
            )
            return

        if get_credits(user.id) < price:
            await interaction.response.send_message(
                "❌ Sem créditos suficientes",
                ephemeral=True
            )
            return

        produto = gerar_produto(categoria)

        if not produto:
            await interaction.response.send_message(
                "⚠️ Sem stock",
                ephemeral=True
            )
            return

        # alerta se acabou o stock
        if stock_count(categoria) == 0:
            canal = bot.get_channel(RESTOCK_CHANNEL_ID)

            if canal:
                await canal.send(
                    f"⚠️ **STOCK ESGOTADO**\n"
                    f"Categoria: **{categoria.upper()}**"
                )

        remove_credits(user.id, price)
        user_cooldowns[user.id] = time.time()

        await atualizar_painel()

        # log arquivo
        with lock:
            with open(GEN_LOG_FILE, "a") as f:
                f.write(f"{datetime.utcnow()}|{user.id}|{categoria}|{produto}\n")

        # log canal
        canal = bot.get_channel(GEN_LOG_CHANNEL_ID)

        if canal:
            await canal.send(
                f"GEN\nUser: <@{user.id}>\nCategoria: {categoria.upper()}\n{produto}"
            )

        try:
            await user.send(
                f"VIPER GEN\nCategoria: {categoria.upper()}\n{produto}"
            )

            await interaction.response.send_message(
                "✔ Entregue",
                ephemeral=True
            )

        except:
            await interaction.response.send_message(
                "❌ DM fechada",
                ephemeral=True
            )

class GenView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(GenDropdown())

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

def criar_embed():

    embed = discord.Embed(
        title="🦂 VIPER GEN",
        description=(
            "The real best guaranteed quality Roblox account generator\n\n"
            "Work with quality accounts and profit today\n\n"
            "With Viper, you can usually hit **Robux, valuable games items, RAP, old join date** and much more."
        ),
        color=0xff003c
    )

    embed.add_field(
        name="🎯 Generate Accounts",
        value="Click **Generate** to open the category selector.",
        inline=False
    )

    embed.set_footer(text="VHXZ • Instant Delivery")

    return embed

async def atualizar_painel():
    global PANEL_MESSAGE_ID, PANEL_CHANNEL_ID

    if not PANEL_MESSAGE_ID or not PANEL_CHANNEL_ID:
        return

    channel = bot.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(PANEL_MESSAGE_ID)
        await msg.edit(embed=criar_embed(), view=MainPanel())
    except:
        pass
# ================= COMANDOS =================
@bot.command()
async def painel(ctx):
    global PANEL_MESSAGE_ID, PANEL_CHANNEL_ID

    msg = await ctx.send(embed=criar_embed(), view=MainPanel())

    PANEL_MESSAGE_ID = msg.id
    PANEL_CHANNEL_ID = ctx.channel.id

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
@commands.has_permissions(administrator=False)
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

from discord import app_commands

@bot.tree.command(name="restock", description="Adicionar stock")
@app_commands.describe(
    categoria="Nome da categoria",
    preco="Preço do produto",
    arquivo="Arquivo .txt com as contas"
)
async def restock(interaction: discord.Interaction, categoria: str, preco: int, arquivo: discord.Attachment):

    categoria = categoria.lower()
    file_path = f"{STOCK_FOLDER}/{categoria}.txt"

    # baixar arquivo enviado
    content = await arquivo.read()
    texto = content.decode("utf-8")

    lista = [l.strip() for l in texto.split("\n") if l.strip()]

    if not lista:
        await interaction.response.send_message(
            "❌ Nenhuma conta encontrada no arquivo",
            ephemeral=True
        )
        return

    with open(file_path, "a") as f:
        f.write("\n".join(lista) + "\n")

    PRICES[categoria] = preco

    qtd = len(lista)

    await interaction.response.send_message(
        f"✅ Restock feito\n"
        f"Categoria: **{categoria.upper()}**\n"
        f"Adicionado: **{qtd} contas**"
    )

    # aviso no canal de restock
    canal = bot.get_channel(RESTOCK_CHANNEL_ID)

    if canal:
        await canal.send(
            f"📦 **RESTOCK**\n"
            f"Categoria: **{categoria.upper()}**\n"
            f"Adicionado: **{qtd} contas**\n"
            f"Stock atual: **{stock_count(categoria)}**"
        )

    await atualizar_painel()

@bot.command()
async def stock(ctx, tipo: str = None):

    if tipo:
        tipo = tipo.lower()
        await ctx.send(f"{tipo.upper()}: {stock_count(tipo)}")
        return

    msg = "STOCK:\n"

    for cat in get_categories():
        msg += f"{cat.upper()}: {stock_count(cat)}\n"

    await ctx.send(msg)

@bot.event
async def on_ready():

    guild = discord.Object(id=GUILD_ID)

    await bot.tree.sync(guild=guild)

    bot.add_view(MainPanel())
    bot.add_view(GenView())

    print(f"Bot online: {bot.user}")
bot.run(TOKEN)
