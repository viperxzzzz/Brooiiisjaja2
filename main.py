import json
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


BASE_DIR = Path(__file__).resolve().parent
TOKEN = os.getenv("TOKEN")
ENABLE_MEMBER_INTENT = os.getenv("ENABLE_MEMBER_INTENT", "false").lower() in {"1", "true", "yes", "on"}

GUILD_ID = 1463315641871106131
TOPUP_CHANNEL_ID = 1471541921292878058
RESTOCK_CHANNEL_ID = 1474702726389567588
RESTOCK_ROLE_ID = 1475311889293774939
GEN_LOG_CHANNEL_ID = 1475984317581627402
PANEL_CHANNEL_ID = 1471646039604723805
PANEL_MESSAGE_ID = 1478301494431322173

PRICE_PER_CREDIT = 0.35
PIX_KEY = "vhxzstore@gmail.com"
PIX_NAME = "VHXZ STORE"
GEN_COOLDOWN_SECONDS = 30
BOOST_CREDITS_PER_BOOST = 40

DEFAULT_PRICES = {"low": 3, "medium": 10, "high": 14}

STOCK_DIR = BASE_DIR / "stocks"
CREDITS_FILE = BASE_DIR / "credits.json"
ORDERS_FILE = BASE_DIR / "orders.json"
PRICES_FILE = BASE_DIR / "prices.json"
BOOST_CLAIMS_FILE = BASE_DIR / "boost_claims.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
GEN_LOG_FILE = BASE_DIR / "gen_log.txt"
AUDIT_LOG_FILE = BASE_DIR / "audit_log.jsonl"

STOCK_DIR.mkdir(exist_ok=True)

file_lock = threading.RLock()
user_cooldowns: dict[int, float] = {}
startup_synced = False

intents = discord.Intents.default()
intents.members = ENABLE_MEMBER_INTENT
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents, help_command=None)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default.copy() if isinstance(default, dict) else default

    with file_lock:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return default.copy() if isinstance(default, dict) else default

    return data if isinstance(data, type(default)) else default


def save_json(path: Path, data) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with file_lock:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4, ensure_ascii=False)
            handle.write("\n")
        temp_path.replace(path)


def write_audit(action: str, *, actor_id: Optional[int] = None, target_id: Optional[int] = None, details: Optional[dict] = None) -> None:
    entry = {
        "time": utc_now(),
        "action": action,
        "actor_id": actor_id,
        "target_id": target_id,
        "details": details or {},
    }
    with file_lock:
        with AUDIT_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def save_setting(key: str, value) -> None:
    settings = load_json(SETTINGS_FILE, {})
    settings[key] = value
    save_json(SETTINGS_FILE, settings)


def load_runtime_settings() -> None:
    global PANEL_CHANNEL_ID, PANEL_MESSAGE_ID

    settings = load_json(SETTINGS_FILE, {})
    PANEL_CHANNEL_ID = int(settings.get("panel_channel_id", PANEL_CHANNEL_ID))
    PANEL_MESSAGE_ID = int(settings.get("panel_message_id", PANEL_MESSAGE_ID))


def load_prices() -> dict[str, int]:
    prices = DEFAULT_PRICES.copy()
    stored = load_json(PRICES_FILE, {})
    prices.update({str(k).lower(): int(v) for k, v in stored.items() if str(v).isdigit() or isinstance(v, int)})
    return prices


def save_price(category: str, price: int) -> None:
    prices = load_prices()
    prices[category] = price
    save_json(PRICES_FILE, prices)


def delete_price(category: str) -> None:
    prices = load_prices()
    prices.pop(category, None)
    save_json(PRICES_FILE, prices)


def normalize_category(category: str) -> str:
    value = category.strip().lower().replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", value):
        raise ValueError("Use only letters, numbers, underscores, or hyphens for the category.")
    return value


def stock_path(category: str) -> Path:
    return STOCK_DIR / f"{category}.txt"


def migrate_legacy_stock_files() -> None:
    for legacy in BASE_DIR.glob("stock_*.txt"):
        category = normalize_category(legacy.stem.removeprefix("stock_"))
        target = stock_path(category)
        if target.exists() or legacy.stat().st_size == 0:
            continue
        target.write_text(legacy.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")


def get_categories(include_empty: bool = True) -> list[str]:
    categories = {path.stem for path in STOCK_DIR.glob("*.txt")}
    categories.update(DEFAULT_PRICES)
    if not include_empty:
        categories = {category for category in categories if stock_count(category) > 0}
    return sorted(categories)


def stock_count(category: str) -> int:
    path = stock_path(category)
    if not path.exists():
        return 0
    with file_lock:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip())


def read_stock_items(category: str) -> list[str]:
    path = stock_path(category)
    if not path.exists():
        return []
    with file_lock:
        return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def write_stock_items(category: str, items: list[str]) -> None:
    path = stock_path(category)
    with file_lock:
        path.write_text(("\n".join(items) + "\n") if items else "", encoding="utf-8")


def pop_stock_item(category: str) -> Optional[str]:
    path = stock_path(category)
    if not path.exists():
        return None

    with file_lock:
        lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
        if not lines:
            return None
        item = random.choice(lines)
        lines.remove(item)
        path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
        return item


def append_stock(category: str, items: list[str]) -> int:
    path = stock_path(category)
    with file_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(items) + "\n")
    return len(items)


def append_unique_stock(category: str, items: list[str]) -> tuple[int, int]:
    existing = set(read_stock_items(category))
    unique_items = []
    seen_upload = set()

    for item in items:
        if item in existing or item in seen_upload:
            continue
        unique_items.append(item)
        seen_upload.add(item)

    if unique_items:
        append_stock(category, unique_items)

    skipped = len(items) - len(unique_items)
    return len(unique_items), skipped


def get_credits(user_id: int) -> int:
    data = load_json(CREDITS_FILE, {})
    return int(data.get(str(user_id), 0))


def add_credits(user_id: int, amount: int) -> int:
    data = load_json(CREDITS_FILE, {})
    uid = str(user_id)
    data[uid] = int(data.get(uid, 0)) + amount
    save_json(CREDITS_FILE, data)
    return data[uid]


def remove_credits(user_id: int, amount: int) -> bool:
    data = load_json(CREDITS_FILE, {})
    uid = str(user_id)
    current = int(data.get(uid, 0))
    if current < amount:
        return False
    data[uid] = current - amount
    save_json(CREDITS_FILE, data)
    return True


def total_credits_in_circulation() -> int:
    data = load_json(CREDITS_FILE, {})
    return sum(int(value) for value in data.values())


def create_order(user_id: int, credits: int) -> tuple[str, float]:
    orders = load_json(ORDERS_FILE, {})
    while True:
        order_id = f"VX-{random.randint(1000, 9999)}"
        if order_id not in orders:
            break

    total = round(credits * PRICE_PER_CREDIT, 2)
    orders[order_id] = {
        "user": user_id,
        "credits": credits,
        "total": total,
        "status": "waiting",
        "time": utc_now(),
    }
    save_json(ORDERS_FILE, orders)
    return order_id, total


def has_claimed_boost(user_id: int) -> bool:
    claims = load_json(BOOST_CLAIMS_FILE, {})
    return bool(claims.get(str(user_id), {}).get("claimed"))


def mark_boost_claimed(user_id: int, source: str, amount: int) -> None:
    claims = load_json(BOOST_CLAIMS_FILE, {})
    claims[str(user_id)] = {
        "claimed": True,
        "source": source,
        "credits": amount,
        "time": utc_now(),
    }
    save_json(BOOST_CLAIMS_FILE, claims)


def product_embed(title: str, description: str, color: int = 0xFF003C) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))


def stock_lines(*, include_empty: bool = True) -> list[str]:
    prices = load_prices()
    return [
        f"**{category.upper()}**: {stock_count(category)} in stock - {prices.get(category, 5)} credits"
        for category in get_categories(include_empty=include_empty)
    ]


def panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="VIPER GEN",
        description=(
            "Private account delivery with credit-based generation.\n"
            "Use the buttons below or slash commands to generate, check stock, and manage credits."
        ),
        color=0xFF003C,
    )
    embed.add_field(name="Stock", value="\n".join(stock_lines(include_empty=False))[:1024] or "No categories in stock right now.", inline=False)
    embed.add_field(name="Boost Perk", value=f"Boost the server and claim **{BOOST_CREDITS_PER_BOOST} credits**.", inline=False)
    embed.set_footer(text="VHXZ - Instant Delivery")
    return embed


def boost_perks_embed() -> discord.Embed:
    embed = discord.Embed(
        title="VIPER GEN Boost Perks",
        description=(
            f"Server boosters receive **{BOOST_CREDITS_PER_BOOST} credits** as a boost reward.\n"
            "Use the button below after boosting to claim your credits."
        ),
        color=0xF47FFF,
    )
    embed.add_field(name="Reward", value=f"{BOOST_CREDITS_PER_BOOST} credits per approved boost reward.", inline=True)
    embed.add_field(name="Delivery", value="Credits are added directly to your bot balance.", inline=True)
    embed.set_footer(text="Admins can use /grantboost for manual multi-boost credit grants.")
    return embed


async def send_restock_alert(category: str, message: str, *, ping_role: bool = False) -> None:
    channel = bot.get_channel(RESTOCK_CHANNEL_ID)
    if channel and hasattr(channel, "send"):
        try:
            content = f"<@&{RESTOCK_ROLE_ID}>\n{message}" if ping_role else message
            embed = discord.Embed(
                title="Restock" if ping_role else "Stock Update",
                description=message,
                color=0x2ECC71 if ping_role else 0xF1C40F,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Category", value=category.upper(), inline=True)
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=ping_role),
            )
        except discord.DiscordException:
            pass


async def send_generation_log(user: discord.abc.User, category: str, item: str) -> None:
    with file_lock:
        with GEN_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{utc_now()}|{user.id}|{category}|{item}\n")

    channel = bot.get_channel(GEN_LOG_CHANNEL_ID)
    if channel and hasattr(channel, "send"):
        try:
            await channel.send(f"GEN\nUser: <@{user.id}>\nCategory: {category.upper()}\nItem: ||{item}||")
        except discord.DiscordException:
            pass


async def refresh_panel() -> None:
    channel = bot.get_channel(PANEL_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(PANEL_MESSAGE_ID)
        await message.edit(embed=panel_embed(), view=MainPanel())
    except discord.DiscordException:
        return


async def generate_for_user(interaction: discord.Interaction, category: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        category = normalize_category(category)
    except ValueError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    prices = load_prices()
    price = int(prices.get(category, 5))
    now = time.monotonic()
    last_generation = user_cooldowns.get(interaction.user.id, 0)

    if now - last_generation < GEN_COOLDOWN_SECONDS:
        remaining = int(GEN_COOLDOWN_SECONDS - (now - last_generation))
        await interaction.followup.send(f"Cooldown active. Try again in {remaining}s.", ephemeral=True)
        return

    if stock_count(category) <= 0:
        await interaction.followup.send("This category is out of stock.", ephemeral=True)
        return

    if price > 0 and get_credits(interaction.user.id) < price:
        await interaction.followup.send(
            f"Not enough credits. `{category.upper()}` costs {price} credits and you have {get_credits(interaction.user.id)}.",
            ephemeral=True,
        )
        return

    item = pop_stock_item(category)
    if item is None:
        await interaction.followup.send("This category is out of stock.", ephemeral=True)
        return

    if price > 0 and not remove_credits(interaction.user.id, price):
        append_stock(category, [item])
        await interaction.followup.send("Your balance changed before generation completed. Try again.", ephemeral=True)
        return

    user_cooldowns[interaction.user.id] = now
    write_audit(
        "generate",
        actor_id=interaction.user.id,
        details={"category": category, "price": price, "remaining_stock": stock_count(category)},
    )

    delivery = f"Category: **{category.upper()}**\nAccount:\n```text\n{item}\n```"
    dm_sent = True
    try:
        await interaction.user.send(embed=product_embed("VIPER GEN Delivery", delivery))
    except discord.DiscordException:
        dm_sent = False

    await send_generation_log(interaction.user, category, item)

    if stock_count(category) == 0:
        await send_restock_alert(category, f"⚠️ **STOCK EMPTY**\nCategory: **{category.upper()}**")

    await refresh_panel()

    if dm_sent:
        await interaction.followup.send(
            f"Delivered in DM. Charged {price} credits. Balance: {get_credits(interaction.user.id)}.",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(
            f"Your DMs are closed, so here is the private delivery.\n{delivery}\nCharged {price} credits. Balance: {get_credits(interaction.user.id)}.",
            ephemeral=True,
        )


async def claim_boost_reward(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)

    if not isinstance(interaction.user, discord.Member):
        await interaction.followup.send("Boost rewards must be claimed inside the server.", ephemeral=True)
        return

    if interaction.user.premium_since is None:
        await interaction.followup.send("You need to boost the server before claiming this reward.", ephemeral=True)
        return

    if has_claimed_boost(interaction.user.id):
        await interaction.followup.send("You already claimed your boost reward. Ask staff if you boosted again.", ephemeral=True)
        return

    balance = add_credits(interaction.user.id, BOOST_CREDITS_PER_BOOST)
    mark_boost_claimed(interaction.user.id, "self_claim", BOOST_CREDITS_PER_BOOST)
    write_audit(
        "boost_claim",
        actor_id=interaction.user.id,
        target_id=interaction.user.id,
        details={"credits": BOOST_CREDITS_PER_BOOST, "balance": balance},
    )
    await interaction.followup.send(
        f"Boost reward claimed: **{BOOST_CREDITS_PER_BOOST} credits** added. New balance: **{balance}**.",
        ephemeral=True,
    )


async def category_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    del interaction
    current = current.lower()
    return [
        app_commands.Choice(name=f"{category.upper()} ({stock_count(category)} stock)", value=category)
        for category in get_categories()
        if current in category.lower()
    ][:25]


class GenDropdown(discord.ui.Select):
    def __init__(self):
        prices = load_prices()
        options = [
            discord.SelectOption(
                label=f"{category.upper()} - {prices.get(category, 5)} credits",
                description=f"Stock: {stock_count(category)}",
                value=category,
            )
            for category in get_categories(include_empty=False)
        ]
        if not options:
            options = [discord.SelectOption(label="No stock", description="No category is available right now.", value="none")]

        super().__init__(placeholder="Select a category", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("No stock is available right now.", ephemeral=True)
            return
        await generate_for_user(interaction, self.values[0])


class GenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(GenDropdown())


class BoostPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Boost Credits", style=discord.ButtonStyle.primary, custom_id="viper:claim_boost")
    async def claim_boost(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        await claim_boost_reward(interaction)


class MainPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Top-Up",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{GUILD_ID}/{TOPUP_CHANNEL_ID}",
            )
        )

    @discord.ui.button(label="Generate", style=discord.ButtonStyle.success, custom_id="viper:generate")
    async def generate(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        await interaction.response.send_message("Choose a category:", view=GenView(), ephemeral=True)

    @discord.ui.button(label="Your Credits", style=discord.ButtonStyle.primary, custom_id="viper:credits")
    async def credits_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        await interaction.response.send_message(f"Your current balance is **{get_credits(interaction.user.id)}** credits.", ephemeral=True)

    @discord.ui.button(label="Boost Perks", style=discord.ButtonStyle.secondary, custom_id="viper:boost_perks")
    async def boost_perks(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        await interaction.response.send_message(embed=boost_perks_embed(), view=BoostPanel(), ephemeral=True)


@bot.tree.command(name="panel", description="Post the generator panel in this channel.")
@app_commands.default_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    global PANEL_CHANNEL_ID, PANEL_MESSAGE_ID

    await interaction.response.send_message(embed=panel_embed(), view=MainPanel())
    message = await interaction.original_response()
    PANEL_CHANNEL_ID = interaction.channel_id or PANEL_CHANNEL_ID
    PANEL_MESSAGE_ID = message.id
    save_setting("panel_channel_id", PANEL_CHANNEL_ID)
    save_setting("panel_message_id", PANEL_MESSAGE_ID)
    write_audit("panel_posted", actor_id=interaction.user.id, details={"channel_id": PANEL_CHANNEL_ID, "message_id": PANEL_MESSAGE_ID})


@bot.tree.command(name="boostpanel", description="Post the boost perks panel in this channel.")
@app_commands.default_permissions(administrator=True)
async def boostpanel(interaction: discord.Interaction):
    await interaction.response.send_message(embed=boost_perks_embed(), view=BoostPanel())
    write_audit("boost_panel_posted", actor_id=interaction.user.id, details={"channel_id": interaction.channel_id})


@bot.tree.command(name="credits", description="Check your credit balance.")
async def credits(interaction: discord.Interaction):
    await interaction.response.send_message(f"You have **{get_credits(interaction.user.id)}** credits.", ephemeral=True)


@bot.tree.command(name="claimboost", description="Claim your server boost credit reward.")
async def claimboost(interaction: discord.Interaction):
    await claim_boost_reward(interaction)


@bot.tree.command(name="generate", description="Generate an account from a stock category.")
@app_commands.describe(category="Stock category to generate from.")
@app_commands.autocomplete(category=category_autocomplete)
async def generate(interaction: discord.Interaction, category: str):
    await generate_for_user(interaction, category)


@bot.tree.command(name="buycredits", description="Create a PIX credit purchase order.")
@app_commands.describe(amount="How many credits you want to buy.")
async def buycredits(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100000]):
    order_id, total = create_order(interaction.user.id, int(amount))
    write_audit("order_created", actor_id=interaction.user.id, details={"order_id": order_id, "credits": int(amount), "total": total})
    await interaction.response.send_message(
        f"Order `{order_id}` created.\n"
        f"Credits: **{amount}**\n"
        f"Total: **R${total:.2f}**\n\n"
        f"PIX: `{PIX_KEY}`\n"
        f"Titular: **{PIX_NAME}**\n"
        "Status: **WAITING PAYMENT**",
        ephemeral=True,
    )


@bot.tree.command(name="stock", description="Show stock counts.")
@app_commands.describe(category="Optional category to inspect.")
@app_commands.autocomplete(category=category_autocomplete)
async def stock(interaction: discord.Interaction, category: Optional[str] = None):
    if category:
        category = normalize_category(category)
        await interaction.response.send_message(f"{category.upper()}: **{stock_count(category)}** in stock.", ephemeral=True)
        return

    prices = load_prices()
    lines = [f"**{cat.upper()}**: {stock_count(cat)} stock - {prices.get(cat, 5)} credits" for cat in get_categories()]
    await interaction.response.send_message("\n".join(lines) or "No categories configured.", ephemeral=True)


@bot.tree.command(name="stockinfo", description="Show detailed information for a stock category.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(category="Category to inspect.")
@app_commands.autocomplete(category=category_autocomplete)
async def stockinfo(interaction: discord.Interaction, category: str):
    category = normalize_category(category)
    prices = load_prices()
    items = read_stock_items(category)

    embed = discord.Embed(title=f"Stock Info: {category.upper()}", color=0x3498DB, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Count", value=str(len(items)), inline=True)
    embed.add_field(name="Price", value=f"{prices.get(category, 5)} credits", inline=True)
    embed.add_field(name="File", value=f"`stocks/{category}.txt`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="exportstock", description="Export a category stock file.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(category="Category to export.")
@app_commands.autocomplete(category=category_autocomplete)
async def exportstock(interaction: discord.Interaction, category: str):
    category = normalize_category(category)
    path = stock_path(category)
    if not path.exists() or stock_count(category) == 0:
        await interaction.response.send_message("That category has no stock to export.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Exporting **{category.upper()}** with **{stock_count(category)}** item(s).",
        file=discord.File(path, filename=f"{category}_stock.txt"),
        ephemeral=True,
    )
    write_audit("stock_exported", actor_id=interaction.user.id, details={"category": category, "stock": stock_count(category)})


@bot.tree.command(name="clearstock", description="Clear all stock from a category.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(category="Category to clear.")
@app_commands.autocomplete(category=category_autocomplete)
async def clearstock(interaction: discord.Interaction, category: str):
    category = normalize_category(category)
    before_count = stock_count(category)
    write_stock_items(category, [])
    await refresh_panel()
    write_audit("stock_cleared", actor_id=interaction.user.id, details={"category": category, "removed": before_count})
    await interaction.response.send_message(f"Cleared **{before_count}** item(s) from **{category.upper()}**.", ephemeral=True)


@bot.tree.command(name="deletecategory", description="Delete a stock category and its saved price.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(category="Category to delete.")
@app_commands.autocomplete(category=category_autocomplete)
async def deletecategory(interaction: discord.Interaction, category: str):
    category = normalize_category(category)
    before_count = stock_count(category)
    path = stock_path(category)
    if path.exists():
        path.unlink()
    delete_price(category)
    await refresh_panel()
    write_audit("category_deleted", actor_id=interaction.user.id, details={"category": category, "removed_stock": before_count})
    await interaction.response.send_message(f"Deleted **{category.upper()}** and removed **{before_count}** stock item(s).", ephemeral=True)


@bot.tree.command(name="addcredits", description="Add credits to a user.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="User receiving credits.", amount="Credits to add.")
async def addcredits(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
    balance = add_credits(member.id, int(amount))
    write_audit("credits_added", actor_id=interaction.user.id, target_id=member.id, details={"amount": int(amount), "balance": balance})
    await interaction.response.send_message(f"Added **{amount}** credits to {member.mention}. New balance: **{balance}**.", ephemeral=True)


@bot.tree.command(name="removecredits", description="Remove credits from a user.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="User losing credits.", amount="Credits to remove.")
async def removecredits(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
    if not remove_credits(member.id, int(amount)):
        await interaction.response.send_message(f"{member.mention} does not have enough credits.", ephemeral=True)
        return
    write_audit("credits_removed", actor_id=interaction.user.id, target_id=member.id, details={"amount": int(amount), "balance": get_credits(member.id)})
    await interaction.response.send_message(f"Removed **{amount}** credits from {member.mention}. New balance: **{get_credits(member.id)}**.", ephemeral=True)


@bot.tree.command(name="grantboost", description="Manually grant boost reward credits to a user.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="User receiving boost credits.", boosts="Number of boost rewards to grant.")
async def grantboost(interaction: discord.Interaction, member: discord.Member, boosts: app_commands.Range[int, 1, 30] = 1):
    amount = int(boosts) * BOOST_CREDITS_PER_BOOST
    balance = add_credits(member.id, amount)
    write_audit("boost_granted", actor_id=interaction.user.id, target_id=member.id, details={"boosts": int(boosts), "credits": amount, "balance": balance})
    await interaction.response.send_message(
        f"Granted **{amount}** boost credits to {member.mention} for **{boosts}** boost reward(s). New balance: **{balance}**.",
        ephemeral=True,
    )
    try:
        await member.send(f"Staff granted you **{amount}** boost credits. New balance: **{balance}**.")
    except discord.DiscordException:
        pass


@bot.tree.command(name="setprice", description="Set the credit price for a category.")
@app_commands.default_permissions(administrator=True)
@app_commands.autocomplete(category=category_autocomplete)
async def setprice(interaction: discord.Interaction, category: str, price: app_commands.Range[int, 0, 100000]):
    category = normalize_category(category)
    save_price(category, int(price))
    await refresh_panel()
    write_audit("price_set", actor_id=interaction.user.id, details={"category": category, "price": int(price)})
    await interaction.response.send_message(f"Set **{category.upper()}** price to **{price}** credits.", ephemeral=True)


@bot.tree.command(name="restock", description="Upload a .txt file and add accounts to stock.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(category="Stock category.", price="Credit price for this category.", file="A .txt file with one account per line.")
async def restock(
    interaction: discord.Interaction,
    category: str,
    price: app_commands.Range[int, 0, 100000],
    file: discord.Attachment,
):
    category = normalize_category(category)
    if not file.filename.lower().endswith(".txt"):
        await interaction.response.send_message("Upload a `.txt` file with one account per line.", ephemeral=True)
        return

    try:
        content = await file.read()
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        await interaction.response.send_message("The uploaded file must be UTF-8 text.", ephemeral=True)
        return

    items = [line.strip() for line in text.splitlines() if line.strip()]
    if not items:
        await interaction.response.send_message("No accounts were found in the uploaded file.", ephemeral=True)
        return

    added, skipped = append_unique_stock(category, items)
    save_price(category, int(price))
    current_stock = stock_count(category)

    await interaction.response.send_message(
        f"Restock complete.\nCategory: **{category.upper()}**\nAdded: **{added}**\nSkipped duplicates: **{skipped}**\nCurrent stock: **{current_stock}**\nPrice: **{price}** credits.",
        ephemeral=True,
    )
    write_audit(
        "restock",
        actor_id=interaction.user.id,
        details={"category": category, "price": int(price), "added": added, "skipped_duplicates": skipped, "stock": current_stock},
    )
    if added > 0:
        await send_restock_alert(
            category,
            f"RESTOCK\nCategory: **{category.upper()}**\nAdded: **{added}**\nStock now: **{current_stock}**",
            ping_role=True,
        )
    await refresh_panel()


@bot.tree.command(name="confirm", description="Confirm a waiting credit order.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(order_id="Order ID, for example VX-1234.")
async def confirm(interaction: discord.Interaction, order_id: str):
    order_id = order_id.strip().upper()
    orders = load_json(ORDERS_FILE, {})
    order = orders.get(order_id)
    if not order:
        await interaction.response.send_message("Order not found.", ephemeral=True)
        return
    if order.get("status") == "paid":
        await interaction.response.send_message("This order is already confirmed.", ephemeral=True)
        return

    balance = add_credits(int(order["user"]), int(order["credits"]))
    order["status"] = "paid"
    order["confirmed_at"] = utc_now()
    save_json(ORDERS_FILE, orders)
    write_audit(
        "order_confirmed",
        actor_id=interaction.user.id,
        target_id=int(order["user"]),
        details={"order_id": order_id, "credits": int(order["credits"]), "balance": balance},
    )

    await interaction.response.send_message(f"Order `{order_id}` confirmed. New user balance: **{balance}**.", ephemeral=True)
    try:
        user = await bot.fetch_user(int(order["user"]))
        await user.send(f"Payment confirmed. **{order['credits']}** credits were added to your account.")
    except discord.DiscordException:
        pass


@bot.tree.command(name="orderinfo", description="Show details for a credit order.")
@app_commands.describe(order_id="Order ID, for example VX-1234.")
async def orderinfo(interaction: discord.Interaction, order_id: str):
    order_id = order_id.strip().upper()
    orders = load_json(ORDERS_FILE, {})
    order = orders.get(order_id)
    if not order:
        await interaction.response.send_message("Order not found.", ephemeral=True)
        return

    is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
    if int(order["user"]) != interaction.user.id and not is_admin:
        await interaction.response.send_message("You can only view your own orders.", ephemeral=True)
        return

    embed = discord.Embed(title=f"Order {order_id}", color=0x3498DB, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="User", value=f"<@{order['user']}>", inline=True)
    embed.add_field(name="Credits", value=str(order["credits"]), inline=True)
    embed.add_field(name="Total", value=f"R${order['total']:.2f}", inline=True)
    embed.add_field(name="Status", value=str(order["status"]).upper(), inline=True)
    embed.add_field(name="Created", value=order["time"], inline=False)
    if order.get("confirmed_at"):
        embed.add_field(name="Confirmed", value=order["confirmed_at"], inline=False)
    if order.get("cancelled_at"):
        embed.add_field(name="Cancelled", value=order["cancelled_at"], inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="cancelorder", description="Cancel a waiting order.")
@app_commands.describe(order_id="Order ID, for example VX-1234.")
async def cancelorder(interaction: discord.Interaction, order_id: str):
    order_id = order_id.strip().upper()
    orders = load_json(ORDERS_FILE, {})
    order = orders.get(order_id)
    if not order:
        await interaction.response.send_message("Order not found.", ephemeral=True)
        return

    is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
    if int(order["user"]) != interaction.user.id and not is_admin:
        await interaction.response.send_message("You can only cancel your own orders.", ephemeral=True)
        return
    if order.get("status") != "waiting":
        await interaction.response.send_message("Only waiting orders can be cancelled.", ephemeral=True)
        return

    order["status"] = "cancelled"
    order["cancelled_at"] = utc_now()
    order["cancelled_by"] = interaction.user.id
    save_json(ORDERS_FILE, orders)
    write_audit("order_cancelled", actor_id=interaction.user.id, target_id=int(order["user"]), details={"order_id": order_id})
    await interaction.response.send_message(f"Order `{order_id}` cancelled.", ephemeral=True)


@bot.tree.command(name="orders", description="Show credit orders.")
@app_commands.default_permissions(administrator=True)
async def orders(interaction: discord.Interaction):
    data = load_json(ORDERS_FILE, {})
    if not data:
        await interaction.response.send_message("No orders recorded.", ephemeral=True)
        return

    lines = []
    for order_id, order in sorted(data.items(), key=lambda item: item[1].get("time", ""), reverse=True)[:20]:
        lines.append(
            f"`{order_id}` | <@{order['user']}> | {order['credits']} credits | R${order['total']:.2f} | {order['status']} | {order['time']}"
        )
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="myorders", description="Show your recent credit orders.")
async def myorders(interaction: discord.Interaction):
    data = load_json(ORDERS_FILE, {})
    user_orders = [
        (order_id, order)
        for order_id, order in data.items()
        if int(order.get("user", 0)) == interaction.user.id
    ]
    if not user_orders:
        await interaction.response.send_message("You do not have any recorded orders.", ephemeral=True)
        return

    lines = []
    for order_id, order in sorted(user_orders, key=lambda item: item[1].get("time", ""), reverse=True)[:10]:
        lines.append(f"`{order_id}` | {order['credits']} credits | R${order['total']:.2f} | {order['status']} | {order['time']}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="stats", description="Show bot inventory and economy stats.")
@app_commands.default_permissions(administrator=True)
async def stats(interaction: discord.Interaction):
    orders_data = load_json(ORDERS_FILE, {})
    credits_data = load_json(CREDITS_FILE, {})
    total_stock = sum(stock_count(category) for category in get_categories())
    waiting_orders = sum(1 for order in orders_data.values() if order.get("status") == "waiting")
    paid_orders = sum(1 for order in orders_data.values() if order.get("status") == "paid")

    embed = discord.Embed(title="VIPER GEN Stats", color=0x3498DB, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Stock", value=f"{total_stock} total accounts\n{len(get_categories())} categories", inline=True)
    embed.add_field(name="Credits", value=f"{total_credits_in_circulation()} in circulation\n{len(credits_data)} users tracked", inline=True)
    embed.add_field(name="Orders", value=f"{waiting_orders} waiting\n{paid_orders} paid", inline=True)
    embed.add_field(name="Boosts", value=f"{len(load_json(BOOST_CLAIMS_FILE, {}))} claims tracked", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if not ENABLE_MEMBER_INTENT:
        return
    if before.premium_since is not None or after.premium_since is None:
        return
    if has_claimed_boost(after.id):
        return

    balance = add_credits(after.id, BOOST_CREDITS_PER_BOOST)
    mark_boost_claimed(after.id, "auto_member_update", BOOST_CREDITS_PER_BOOST)
    try:
        await after.send(f"Thanks for boosting. **{BOOST_CREDITS_PER_BOOST} credits** were added. Balance: **{balance}**.")
    except discord.DiscordException:
        pass


@bot.event
async def on_ready():
    global startup_synced

    load_runtime_settings()
    migrate_legacy_stock_files()

    if not startup_synced:
        bot.add_view(MainPanel())
        bot.add_view(BoostPanel())
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        startup_synced = True
        print(f"Bot online as {bot.user}. Synced {len(synced)} slash commands to guild {GUILD_ID}.")
        if not ENABLE_MEMBER_INTENT:
            print("ENABLE_MEMBER_INTENT is false. Automatic boost detection is disabled; /claimboost and /grantboost still work.")
    else:
        print(f"Bot reconnected as {bot.user}.")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You do not have permission to use this command."
    elif isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, ValueError):
        message = str(error.original)
    else:
        message = "The command failed. Check the bot console for details."
        print(f"Slash command error: {error!r}")

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def main() -> None:
    if not TOKEN:
        raise RuntimeError("Set the TOKEN environment variable before starting the bot.")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
