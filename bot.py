import logging
import os
import sqlite3
from datetime import datetime, time as dtime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DB_PATH = "deals.db"

CATEGORIES = {
    "Match Bonus":   "💎",
    "Free Spins":    "🎰",
    "No Deposit":    "🎁",
    "Cashback":      "💰",
    "Reload Bonus":  "🔄",
    "VIP Deal":      "👑",
    "Sports Bet":    "⚽",
    "Promo Code":    "🏷️",
}

CASINOS = {
    "Stake":        {"rating": 4.9, "crypto": "BTC · ETH · USDT · LTC"},
    "Maddax":       {"rating": 4.7, "crypto": "BTC · ETH · USDT"},
    "FortuneVault": {"rating": 4.5, "crypto": "BTC · ETH · USDT · BNB"},
    "BitCasino":    {"rating": 4.6, "crypto": "BTC · ETH · USDT · LTC · XRP"},
    "ApexPlay":     {"rating": 4.8, "crypto": "BTC · ETH · USDT · SOL"},
    "NovaBet":      {"rating": 4.4, "crypto": "BTC · ETH · USDT"},
}

SEED_DEALS = [
    {
        "title": "100% Match Bonus up to $1,000",
        "casino_name": "Stake",
        "category": "Match Bonus",
        "description": "Double your first deposit. Min $20 — Max $1,000. Auto-activated, no promo code needed.",
        "link": "https://better-play.io",
        "expiry": "2026-12-31",
        "bonus_amount": "$1,000",
        "min_deposit": "$20",
        "image_url": None,
        "is_featured": 1,
    },
    {
        "title": "Free Spins on Registration",
        "casino_name": "Maddax",
        "category": "Free Spins",
        "description": "No deposit required. Get free spins just for signing up — winnings paid in crypto.",
        "link": "https://better-play.io",
        "expiry": "2026-12-31",
        "bonus_amount": "Free Spins",
        "min_deposit": "$0",
        "image_url": None,
        "is_featured": 0,
    },
    {
        "title": "15% Weekly Cashback",
        "casino_name": "FortuneVault",
        "category": "Cashback",
        "description": "Get 15% back on net losses every week. Paid every Monday directly to your wallet.",
        "link": "https://better-play.io",
        "expiry": "2026-12-31",
        "bonus_amount": "15% Back",
        "min_deposit": "$10",
        "image_url": None,
        "is_featured": 0,
    },
    {
        "title": "50% Reload Bonus up to $300",
        "casino_name": "BitCasino",
        "category": "Reload Bonus",
        "description": "Every Monday, reload your account and get a 50% bonus on top. Up to $300 per week.",
        "link": "https://better-play.io",
        "expiry": "2026-12-31",
        "bonus_amount": "$300",
        "min_deposit": "$20",
        "image_url": None,
        "is_featured": 0,
    },
    {
        "title": "VIP Fast-Track from Day One",
        "casino_name": "ApexPlay",
        "category": "VIP Deal",
        "description": "Skip the grind. ApexPlay gives new players instant VIP status with dedicated support and higher limits.",
        "link": "https://better-play.io",
        "expiry": "2026-12-31",
        "bonus_amount": "VIP Access",
        "min_deposit": "$50",
        "image_url": None,
        "is_featured": 0,
    },
    {
        "title": "$200 Free Bet — Sportsbook",
        "casino_name": "NovaBet",
        "category": "Sports Bet",
        "description": "Place your first sports bet and get up to $200 back if it loses. BTC · ETH · USDT accepted.",
        "link": "https://better-play.io",
        "expiry": "2026-12-31",
        "bonus_amount": "$200",
        "min_deposit": "$20",
        "image_url": None,
        "is_featured": 0,
    },
]

# Conversation states
(
    ADD_TITLE, ADD_CASINO, ADD_CATEGORY, ADD_DESCRIPTION,
    ADD_LINK, ADD_EXPIRY, ADD_BONUS, ADD_MIN_DEP, ADD_IMAGE,
) = range(9)

BROADCAST_MSG = 9


# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                casino_name TEXT,
                category TEXT NOT NULL,
                description TEXT,
                link TEXT,
                expiry TEXT,
                bonus_amount TEXT,
                min_deposit TEXT,
                image_url TEXT,
                is_featured INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        conn.commit()
        # Seed only if empty
        count = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        if count == 0:
            for d in SEED_DEALS:
                conn.execute(
                    """INSERT INTO deals
                       (title, casino_name, category, description, link, expiry,
                        bonus_amount, min_deposit, image_url, is_featured)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (d["title"], d["casino_name"], d["category"], d["description"],
                     d["link"], d["expiry"], d["bonus_amount"], d["min_deposit"],
                     d["image_url"], d["is_featured"])
                )
            conn.commit()


def is_admin(user_id: int) -> bool:
    with get_db() as conn:
        return conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone() is not None


# ── Formatting helpers ─────────────────────────────────────────────────────────

def stars(rating: float) -> str:
    full = int(rating)
    return "⭐" * full + f"  {rating}/5"


def deal_card(deal) -> str:
    cat_emoji = CATEGORIES.get(deal["category"], "🎯")
    casino = deal["casino_name"] or ""
    casino_info = CASINOS.get(casino, {})
    rating_str = f"  {stars(casino_info['rating'])}" if casino_info else ""
    crypto_str = f"\n₿  {casino_info['crypto']}" if casino_info else ""

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"{cat_emoji}  *{deal['title']}*",
        f"🏛  {casino}{rating_str}" if casino else "",
        f"🎯  _{deal['category']}_",
    ]
    if deal["bonus_amount"]:
        lines.append(f"💥  Bonus: *{deal['bonus_amount']}*")
    if deal["min_deposit"] and deal["min_deposit"] != "$0":
        lines.append(f"💳  Min Deposit: {deal['min_deposit']}")
    elif deal["min_deposit"] == "$0":
        lines.append("💳  Min Deposit: *FREE — No deposit needed*")
    if deal["description"]:
        lines.append(f"\n{deal['description']}")
    if deal["link"]:
        lines.append(f"\n🔗  [Claim This Deal]({deal['link']})")
    if deal["expiry"]:
        lines.append(f"⏳  Expires: {deal['expiry']}")
    if crypto_str:
        lines.append(crypto_str)

    return "\n".join(l for l in lines if l)


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Hot Deals", callback_data="cmd_hot"),
         InlineKeyboardButton("📂 Browse", callback_data="cmd_browse")],
        [InlineKeyboardButton("⭐ Deal of the Day", callback_data="cmd_dealofday"),
         InlineKeyboardButton("🏛 Casinos", callback_data="cmd_casinos")],
        [InlineKeyboardButton("🔔 Subscribe Alerts", callback_data="cmd_subscribe")],
    ])


def category_keyboard(prefix="cat"):
    buttons = [
        [InlineKeyboardButton(f"{emoji}  {name}", callback_data=f"{prefix}_{name}")]
        for name, emoji in CATEGORIES.items()
    ]
    return InlineKeyboardMarkup(buttons)


def browse_keyboard():
    buttons = [
        [InlineKeyboardButton(f"{emoji}  {name}", callback_data=f"browse_{name}")]
        for name, emoji in CATEGORIES.items()
    ]
    buttons.append([InlineKeyboardButton("🔥  All Deals", callback_data="browse_all")])
    return InlineKeyboardMarkup(buttons)


# ── User commands ──────────────────────────────────────────────────────────────

WELCOME_TEXT = (
    "🎰  *Welcome to BetterPlay Deals Bot!*\n"
    "━━━━━━━━━━━━━━━━━━━━━\n\n"
    "Your #1 source for *verified crypto casino bonuses*, free spins, "
    "and exclusive iGaming deals — updated 24/7.\n\n"
    "🏆  *40+ Live Deals*  |  ⚡  *Instant Claims*  |  ₿  *Crypto First*\n\n"
    "━━━━━━━━━━━━━━━━━━━━━\n"
    "Use the menu below or these commands:\n\n"
    "/hot — 🔥 Today's hottest deals\n"
    "/browse — 📂 Browse by category\n"
    "/casinos — 🏛 All casinos & ratings\n"
    "/dealofday — ⭐ Featured deal\n"
    "/search \\<keyword\\> — 🔍 Search deals\n"
    "/subscribe — 🔔 Daily alerts at 9 AM\n"
    "/unsubscribe — 🔕 Stop alerts\n\n"
    "_18\\+ \\| Please gamble responsibly\\._"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=main_menu_keyboard(),
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cmd = query.data

    if cmd == "cmd_hot":
        await _send_hot(query.message, edit=True)
    elif cmd == "cmd_browse":
        await query.edit_message_text("📂 *Choose a category:*", parse_mode="Markdown",
                                      reply_markup=browse_keyboard())
    elif cmd == "cmd_dealofday":
        await _send_deal_of_day(query.message, edit=True)
    elif cmd == "cmd_casinos":
        await _send_casinos(query.message, edit=True)
    elif cmd == "cmd_subscribe":
        user = query.from_user
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO subscribers (user_id, username, active) VALUES (?,?,1)",
                (user.id, user.username)
            )
            conn.commit()
        await query.edit_message_text(
            "✅ *Subscribed!*\n\nYou'll receive daily deal alerts at *9:00 AM*.\n"
            "Use /unsubscribe to stop anytime.",
            parse_mode="Markdown"
        )


async def hot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_hot(update.message)


async def _send_hot(msg, edit=False):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM deals WHERE active=1 ORDER BY is_featured DESC, created_at DESC LIMIT 5"
        ).fetchall()

    if not rows:
        text = "No deals right now — check back soon! 🔜"
        if edit:
            await msg.edit_message_text(text)
        else:
            await msg.reply_text(text)
        return

    header = (
        "🔥 *HOT DEALS — BetterPlay*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "_Verified · Updated 24/7 · Crypto First_\n"
    )
    cards = "\n\n".join(deal_card(r) for r in rows)
    text = header + "\n" + cards + "\n\n━━━━━━━━━━━━━━━━━━━━━\n_18\\+ \\| gamble responsibly_"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📂 Browse All", callback_data="cmd_browse"),
        InlineKeyboardButton("⭐ Deal of Day", callback_data="cmd_dealofday"),
    ]])
    try:
        if edit:
            await msg.edit_message_text(text, parse_mode="Markdown",
                                         disable_web_page_preview=True, reply_markup=kb)
        else:
            await msg.reply_text(text, parse_mode="Markdown",
                                  disable_web_page_preview=True, reply_markup=kb)
    except Exception:
        # Fallback without Markdown if formatting fails
        if edit:
            await msg.edit_message_text(cards, disable_web_page_preview=True)
        else:
            await msg.reply_text(cards, disable_web_page_preview=True)


async def browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📂 *Choose a category:*", parse_mode="Markdown",
                                    reply_markup=browse_keyboard())


async def browse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    category = None if data == "browse_all" else data.replace("browse_", "")

    with get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM deals WHERE active=1 AND category=? ORDER BY created_at DESC LIMIT 8",
                (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM deals WHERE active=1 ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

    if not rows:
        await query.edit_message_text(
            f"No deals in *{category or 'All'}* yet — check back soon! 🔜",
            parse_mode="Markdown"
        )
        return

    cat_emoji = CATEGORIES.get(category, "🎯") if category else "🎯"
    label = f"{cat_emoji}  {category}" if category else "🔥  All Deals"
    header = f"*{label}*\n━━━━━━━━━━━━━━━━━━━━━\n"
    cards = "\n\n".join(deal_card(r) for r in rows)
    text = header + cards

    await query.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def deal_of_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_deal_of_day(update.message)


async def _send_deal_of_day(msg, edit=False):
    with get_db() as conn:
        deal = conn.execute(
            "SELECT * FROM deals WHERE active=1 AND is_featured=1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not deal:
            deal = conn.execute(
                "SELECT * FROM deals WHERE active=1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

    if not deal:
        text = "No featured deal today — check back soon!"
        if edit:
            await msg.edit_message_text(text)
        else:
            await msg.reply_text(text)
        return

    text = (
        "⭐ *DEAL OF THE DAY*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        + deal_card(deal) +
        "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        "🌐  [View All Deals](https://better-play.io)\n"
        "_18\\+ \\| Please gamble responsibly_"
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔥 More Hot Deals", callback_data="cmd_hot"),
        InlineKeyboardButton("🏛 All Casinos", callback_data="cmd_casinos"),
    ]])

    try:
        if deal["image_url"]:
            if edit:
                await msg.reply_photo(photo=deal["image_url"], caption=text,
                                       parse_mode="Markdown")
            else:
                await msg.reply_photo(photo=deal["image_url"], caption=text,
                                       parse_mode="Markdown", reply_markup=kb)
        else:
            if edit:
                await msg.edit_message_text(text, parse_mode="Markdown",
                                             disable_web_page_preview=True, reply_markup=kb)
            else:
                await msg.reply_text(text, parse_mode="Markdown",
                                      disable_web_page_preview=True, reply_markup=kb)
    except Exception:
        if edit:
            await msg.edit_message_text(deal_card(deal), disable_web_page_preview=True)
        else:
            await msg.reply_text(deal_card(deal), disable_web_page_preview=True)


async def casinos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_casinos(update.message)


async def _send_casinos(msg, edit=False):
    lines = ["🏛  *CRYPTO CASINOS — BetterPlay*", "━━━━━━━━━━━━━━━━━━━━━", ""]
    for name, info in CASINOS.items():
        with get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM deals WHERE active=1 AND casino_name=?", (name,)
            ).fetchone()[0]
        lines.append(
            f"*{name}*  {stars(info['rating'])}\n"
            f"₿  {info['crypto']}\n"
            f"🎯  {count} active deal{'s' if count != 1 else ''}\n"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🌐  [See All Deals on BetterPlay](https://better-play.io)")

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔥 Hot Deals", callback_data="cmd_hot"),
        InlineKeyboardButton("📂 Browse", callback_data="cmd_browse"),
    ]])

    if edit:
        await msg.edit_message_text(text, parse_mode="Markdown",
                                     disable_web_page_preview=True, reply_markup=kb)
    else:
        await msg.reply_text(text, parse_mode="Markdown",
                              disable_web_page_preview=True, reply_markup=kb)


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM deals WHERE active=1 ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    if not rows:
        await update.message.reply_text("No deals yet — check back soon!")
        return
    cards = "\n\n".join(deal_card(r) for r in rows)
    await update.message.reply_text(
        "🆕 *Latest Deals*\n━━━━━━━━━━━━━━━━━━━━━\n\n" + cards,
        parse_mode="Markdown", disable_web_page_preview=True
    )


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search <keyword>\nExample: /search free spins")
        return
    query_str = " ".join(context.args).lower()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM deals WHERE active=1 AND (
               LOWER(title) LIKE ? OR LOWER(description) LIKE ? OR
               LOWER(casino_name) LIKE ? OR LOWER(category) LIKE ?
            ) ORDER BY created_at DESC LIMIT 6""",
            (f"%{query_str}%",) * 4
        ).fetchall()
    if not rows:
        await update.message.reply_text(f"🔍 No deals found for *{query_str}*.", parse_mode="Markdown")
        return
    cards = "\n\n".join(deal_card(r) for r in rows)
    await update.message.reply_text(
        f"🔍 *Results for \"{query_str}\"*\n━━━━━━━━━━━━━━━━━━━━━\n\n" + cards,
        parse_mode="Markdown", disable_web_page_preview=True
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO subscribers (user_id, username, active) VALUES (?,?,1)",
            (user.id, user.username)
        )
        conn.commit()
    await update.message.reply_text(
        "✅ *Subscribed!*\n\n"
        "You'll receive *daily deal alerts at 9:00 AM* with the best crypto casino bonuses.\n\n"
        "Use /unsubscribe to stop anytime.",
        parse_mode="Markdown"
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with get_db() as conn:
        conn.execute("UPDATE subscribers SET active=0 WHERE user_id=?", (user.id,))
        conn.commit()
    await update.message.reply_text("🔕 Unsubscribed from daily alerts.")


# ── Admin commands ─────────────────────────────────────────────────────────────

async def setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
        if count == 0:
            conn.execute("INSERT INTO admins (user_id) VALUES (?)", (user_id,))
            conn.commit()
            await update.message.reply_text(f"✅ You ({user_id}) are now admin.")
        else:
            await update.message.reply_text("Admin already set. Ask existing admin to add you via /addadmin.")


async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    new_id = int(context.args[0])
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
        conn.commit()
    await update.message.reply_text(f"✅ Added admin: {new_id}")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    with get_db() as conn:
        total_deals = conn.execute("SELECT COUNT(*) FROM deals WHERE active=1").fetchone()[0]
        total_subs = conn.execute("SELECT COUNT(*) FROM subscribers WHERE active=1").fetchone()[0]
        total_admins = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) as c FROM deals WHERE active=1 GROUP BY category"
        ).fetchall()
    lines = [
        "📊 *Bot Stats*",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🎯  Active Deals: *{total_deals}*",
        f"🔔  Subscribers: *{total_subs}*",
        f"👤  Admins: *{total_admins}*",
        "",
        "*Deals by Category:*",
    ]
    for row in by_cat:
        emoji = CATEGORIES.get(row["category"], "🎯")
        lines.append(f"  {emoji}  {row['category']}: {row['c']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def list_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, casino_name, category, active, is_featured FROM deals ORDER BY id DESC LIMIT 20"
        ).fetchall()
    if not rows:
        await update.message.reply_text("No deals yet.")
        return
    lines = ["*All Deals (last 20):*\n"]
    for r in rows:
        status = "✅" if r["active"] else "❌"
        feat = " ⭐" if r["is_featured"] else ""
        lines.append(f"{status} ID {r['id']}{feat}: [{r['category']}] {r['casino_name']} — {r['title']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def delete_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /delete <deal_id>")
        return
    deal_id = int(context.args[0])
    with get_db() as conn:
        conn.execute("UPDATE deals SET active=0 WHERE id=?", (deal_id,))
        conn.commit()
    await update.message.reply_text(f"✅ Deal {deal_id} deactivated.")


async def feature_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /feature <deal_id>")
        return
    deal_id = int(context.args[0])
    with get_db() as conn:
        conn.execute("UPDATE deals SET is_featured=0")
        conn.execute("UPDATE deals SET is_featured=1 WHERE id=?", (deal_id,))
        conn.commit()
    await update.message.reply_text(f"⭐ Deal {deal_id} is now the Deal of the Day.")


# ── Add deal conversation ──────────────────────────────────────────────────────

async def add_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📝 *Add New Deal*\n━━━━━━━━━━━━━━━━━━━━━\n\nStep 1/8 — Enter the deal *title*:",
        parse_mode="Markdown"
    )
    return ADD_TITLE


async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"] = {"title": update.message.text}
    casino_buttons = [[InlineKeyboardButton(name, callback_data=f"casino_{name}")] for name in CASINOS]
    casino_buttons.append([InlineKeyboardButton("Other / Custom", callback_data="casino_Other")])
    await update.message.reply_text(
        "Step 2/8 — Choose the *casino*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(casino_buttons)
    )
    return ADD_CASINO


async def add_casino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["deal"]["casino_name"] = query.data.replace("casino_", "")
    await query.edit_message_text("Step 3/8 — Choose a *category*:", parse_mode="Markdown",
                                   reply_markup=category_keyboard("cat"))
    return ADD_CATEGORY


async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["deal"]["category"] = query.data.replace("cat_", "")
    await query.edit_message_text("Step 4/8 — Enter a short *description* (or /skip):",
                                   parse_mode="Markdown")
    return ADD_DESCRIPTION


async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"]["description"] = "" if update.message.text == "/skip" else update.message.text
    await update.message.reply_text("Step 5/8 — Enter the *claim link* (or /skip):", parse_mode="Markdown")
    return ADD_LINK


async def add_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"]["link"] = "" if update.message.text == "/skip" else update.message.text
    await update.message.reply_text("Step 6/8 — Enter expiry date e.g. *2026-05-01* (or /skip):",
                                    parse_mode="Markdown")
    return ADD_EXPIRY


async def add_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"]["expiry"] = "" if update.message.text == "/skip" else update.message.text
    await update.message.reply_text("Step 7/8 — Enter the *bonus amount* e.g. $500, 50 Free Spins (or /skip):",
                                    parse_mode="Markdown")
    return ADD_BONUS


async def add_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"]["bonus_amount"] = "" if update.message.text == "/skip" else update.message.text
    await update.message.reply_text("Step 8/8 — Enter *min deposit* e.g. $20, $0 for no-deposit (or /skip):",
                                    parse_mode="Markdown")
    return ADD_MIN_DEP


async def add_min_dep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"]["min_deposit"] = "" if update.message.text == "/skip" else update.message.text
    await update.message.reply_text(
        "Optional — Send an *image URL* for this deal (or /skip):\n"
        "_Tip: use a direct image link ending in .jpg or .png_",
        parse_mode="Markdown"
    )
    return ADD_IMAGE


async def add_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deal = context.user_data["deal"]
    deal["image_url"] = None if update.message.text == "/skip" else update.message.text

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO deals (title, casino_name, category, description, link, expiry,
               bonus_amount, min_deposit, image_url)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (deal["title"], deal.get("casino_name"), deal["category"], deal["description"],
             deal["link"], deal["expiry"], deal.get("bonus_amount"), deal.get("min_deposit"),
             deal["image_url"])
        )
        new_id = cursor.lastrowid
        subscribers = conn.execute("SELECT user_id FROM subscribers WHERE active=1").fetchall()
        conn.commit()

    await update.message.reply_text(
        f"✅ *Deal added!* (ID: {new_id})\n\n" + deal_card(
            type("obj", (object,), deal)()
        ),
        parse_mode="Markdown"
    )

    # Notify subscribers
    notify_text = (
        "🚨 *New Deal Just Dropped!*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*{deal['title']}*\n"
        f"🏛  {deal.get('casino_name', '')}\n"
        f"💥  {deal.get('bonus_amount', '')}\n\n"
        "🔗  Use /latest to see all new deals!"
    )
    for sub in subscribers:
        try:
            await context.bot.send_message(
                chat_id=sub["user_id"], text=notify_text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Notify failed for {sub['user_id']}: {e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


# ── Broadcast conversation ─────────────────────────────────────────────────────

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM subscribers WHERE active=1").fetchone()[0]
    await update.message.reply_text(
        f"📢 *Broadcast to {count} subscribers*\n\nSend your message below (supports Markdown):",
        parse_mode="Markdown"
    )
    return BROADCAST_MSG


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text
    with get_db() as conn:
        subscribers = conn.execute("SELECT user_id FROM subscribers WHERE active=1").fetchall()

    sent, failed = 0, 0
    for sub in subscribers:
        try:
            await context.bot.send_message(
                chat_id=sub["user_id"], text=f"📢 *BetterPlay Announcement*\n\n{msg_text}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"✅ Broadcast complete.\n✉️ Sent: {sent}  |  ❌ Failed: {failed}"
    )
    return ConversationHandler.END


# ── Daily alerts ───────────────────────────────────────────────────────────────

async def send_daily_alerts(context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        subscribers = conn.execute("SELECT user_id FROM subscribers WHERE active=1").fetchall()
        deals = conn.execute(
            "SELECT * FROM deals WHERE active=1 ORDER BY is_featured DESC, created_at DESC LIMIT 5"
        ).fetchall()

    if not deals or not subscribers:
        return

    today = datetime.now().strftime("%A, %B %d")
    header = (
        f"🎰 *BetterPlay Daily Deals — {today}*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Top crypto casino bonuses, verified & ready to claim:\n\n"
    )
    cards = "\n\n".join(deal_card(d) for d in deals)
    footer = (
        "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        "🌐  [All Deals → better-play.io](https://better-play.io)\n"
        "🔕  /unsubscribe to stop alerts\n"
        "_18\\+ \\| Gamble responsibly_"
    )
    text = header + cards + footer

    for sub in subscribers:
        try:
            await context.bot.send_message(
                chat_id=sub["user_id"], text=text,
                parse_mode="Markdown", disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning(f"Daily alert failed for {sub['user_id']}: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("adddeal", add_deal)],
        states={
            ADD_TITLE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            ADD_CASINO:      [CallbackQueryHandler(add_casino, pattern="^casino_")],
            ADD_CATEGORY:    [CallbackQueryHandler(add_category, pattern="^cat_")],
            ADD_DESCRIPTION: [MessageHandler(filters.TEXT, add_description)],
            ADD_LINK:        [MessageHandler(filters.TEXT, add_link)],
            ADD_EXPIRY:      [MessageHandler(filters.TEXT, add_expiry)],
            ADD_BONUS:       [MessageHandler(filters.TEXT, add_bonus)],
            ADD_MIN_DEP:     [MessageHandler(filters.TEXT, add_min_dep)],
            ADD_IMAGE:       [MessageHandler(filters.TEXT, add_image)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("hot", hot))
    app.add_handler(CommandHandler("browse", browse))
    app.add_handler(CommandHandler("latest", latest))
    app.add_handler(CommandHandler("casinos", casinos))
    app.add_handler(CommandHandler("dealofday", deal_of_day))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("setadmin", setadmin))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("listdeals", list_deals))
    app.add_handler(CommandHandler("delete", delete_deal))
    app.add_handler(CommandHandler("feature", feature_deal))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(add_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(CallbackQueryHandler(browse_callback, pattern="^browse_"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^cmd_"))

    app.job_queue.run_daily(send_daily_alerts, time=dtime(hour=9, minute=0))

    logger.info("BetterPlay Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
