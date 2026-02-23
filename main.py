import discord
from discord.ext import commands
import json
import threading
import os

TOKEN = "SEU TOKEN AQUI"
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

lock = threading.Lock()

PRICES = {
    "low": 5,
    "medium": 10,
    "high": 14
}

STOCK_FILES = {
    "low": "stock_low.txt",
    "medium": "stock_medium.txt",
    "high": "stock_high.txt"
}

CREDITS_FILE = "credits.json"


# ================= CREDITS =================

def load_credits():
    if not os.path.exists(CREDITS_FILE):
        return {}
    with open(CREDITS_FILE, "r") as f:
        return json.load(f)

def save_credits(data):
    with open(CREDITS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def add_credits(user_id, amount):
    data = load_credits()
    data[str(user_id)] = data.get(str(user_id), 0) + amount
    save_credits(data)

def get_credits(user_id):
    data = load_credits()
    return data.get(str(user_id), 0)

def remove_credits_amount(user_id, amount):
    data = load_credits()
    uid = str(user_id)
    if uid not in data or data[uid] < amount:
        return False
    data[uid] -= amount
    save_credits(data)
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

        produto = linhas[0]
        linhas.pop(0)

        with open(file, "w") as f:
            f.write("\n".join(linhas))

        return produto


# ================= BOTÕES =================

class GenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def process(self, interaction, tipo):
        user = interaction.user
        price = PRICES[tipo]

        if get_credits(user.id) < price:
            await interaction.response.send_message(
                f"❌ Você precisa de {price} créditos.",
                ephemeral=True
            )
            return

        produto = gerar_produto(tipo)

        if not produto:
            await interaction.response.send_message(
                "❌ Estoque esgotado.",
                ephemeral=True
            )
            return

        remove_credits_amount(user.id, price)

        try:
            await user.send(
                f"🛒 Produto: {tipo.upper()}\n"
                f"🔑 {produto}"
            )
            await interaction.response.send_message(
                "✅ Produto enviado na DM.",
                ephemeral=True
            )
        except:
            await interaction.response.send_message(
                "❌ Ative sua DM.",
                ephemeral=True
            )

    @discord.ui.button(label="Low Quality (5)", style=discord.ButtonStyle.secondary)
    async def low(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, "low")

    @discord.ui.button(label="Medium Quality (10)", style=discord.ButtonStyle.primary)
    async def medium(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, "medium")

    @discord.ui.button(label="High Quality (14)", style=discord.ButtonStyle.success)
    async def high(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, "high")


# ================= COMANDOS =================

@bot.command()
async def credits(ctx):
    c = get_credits(ctx.author.id)
    await ctx.send(f"💳 {ctx.author.mention} você tem **{c} créditos**.")


@bot.command()
@commands.has_permissions(administrator=True)
async def addcredits(ctx, user: discord.Member, amount: int):
    add_credits(user.id, amount)
    await ctx.send(f"✅ {amount} créditos adicionados para {user.mention}.")


@bot.command()
@commands.has_permissions(administrator=True)
async def removecredits(ctx, user: discord.Member, amount: int):
    data = load_credits()
    uid = str(user.id)

    if uid not in data or data[uid] < amount:
        await ctx.send("❌ Créditos insuficientes.")
        return

    data[uid] -= amount
    save_credits(data)

    await ctx.send(f"➖ {amount} créditos removidos de {user.mention}.")


@bot.command()
async def painel(ctx):
    embed = discord.Embed(
        title="🛒 Painel de Geração",
        description=(
             "**The best guaranteed quality Roblox account generator**\n\n"
            "Work with quality accounts and profit today With Viper, you can usually hit Robux, valuable games items, RAP, old join date and much more.\n\n"
            "**We restock our stocks every 3-8 hours.**\n\n"
           
             "**Escolha o produto:**\n\n"
            "🔘 Low Quality — 5 créditos\n"
            "🔘 Medium Quality — 10 créditos\n"
            "🔘 High Quality — 14 créditos"
        ),
        color=0x2b2d31
    )

    embed.set_footer(text="Após clicar, o produto será enviado na DM.")

    await ctx.send(embed=embed, view=GenView())


# ================= RUN =================

bot.run(TOKEN)