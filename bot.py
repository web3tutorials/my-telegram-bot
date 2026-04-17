import logging
import os
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")import sqlite3
import asyncio
from datetime import datetime, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

import os
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = []  # Will be set by first /setadmin command, or hardcode your Telegram user ID here

DB_PATH = "deals.db"

CATEGORIES = ["Casino Bonus", "Free Spins", "No Deposit", "Sports Betting", "Promo Code", "VIP Deal"]

# Conversation states
(
    ADD_TITLE, ADD_CATEGORY, ADD_DESCRIPTION, ADD_LINK, ADD_EXPIRY,
    EDIT_CHOOSE, EDIT_FIELD, EDIT_VALUE,
) = range(8)


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
                category TEXT NOT NULL,
                description TEXT,
                link TEXT,
                expiry TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                alert_hour INTEGER DEFAULT 9,
                active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        conn.commit()


def is_admin(user_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None


def category_keyboard():
    buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{c}")] for c in CATEGORIES]
    return InlineKeyboardMarkup(buttons)


def browse_keyboard():
    buttons = [[InlineKeyboardButton(c, callback_data=f"browse_{c}")] for c in CATEGORIES]
    buttons.append([InlineKeyboardButton("🔥 All Deals", callback_data="browse_all")])
    return InlineKeyboardMarkup(buttons)


# ── User commands ──────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎰 *Welcome to iGaming Deals Bot!*\n\n"
        "Find the best casino bonuses, free spins, and promos.\n\n"
        "/browse — Browse deals by category\n"
        "/subscribe — Get daily deal alerts\n"
        "/unsubscribe — Stop daily alerts\n"
        "/latest — Show today's latest deals",
        parse_mode="Markdown"
    )


async def browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📂 Choose a category:", reply_markup=browse_keyboard()
    )


async def browse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    category = None if data == "browse_all" else data.replace("browse_", "")

    with get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM deals WHERE active=1 AND category=? ORDER BY created_at DESC LIMIT 10",
                (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM deals WHERE active=1 ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

    if not rows:
        await query.edit_message_text("No deals found in this category yet. Check back soon!")
        return

    label = category or "All Categories"
    text = f"🎯 *{label}*\n\n"
    for deal in rows:
        text += f"*{deal['title']}*\n"
        if deal['description']:
            text += f"{deal['description']}\n"
        if deal['link']:
            text += f"🔗 [Claim Deal]({deal['link']})\n"
        if deal['expiry']:
            text += f"⏳ Expires: {deal['expiry']}\n"
        text += "\n"

    await query.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM deals WHERE active=1 ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

    if not rows:
        await update.message.reply_text("No deals yet — check back soon!")
        return

    text = "🔥 *Latest Deals*\n\n"
    for deal in rows:
        text += f"[{deal['category']}] *{deal['title']}*\n"
        if deal['description']:
            text += f"{deal['description']}\n"
        if deal['link']:
            text += f"🔗 [Claim]({deal['link']})\n"
        text += "\n"

    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO subscribers (user_id, username, active) VALUES (?, ?, 1)",
            (user.id, user.username)
        )
        conn.commit()
    await update.message.reply_text(
        "✅ You're subscribed to daily deal alerts at 9:00 AM!\n"
        "Use /unsubscribe to stop."
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with get_db() as conn:
        conn.execute("UPDATE subscribers SET active=0 WHERE user_id=?", (user.id,))
        conn.commit()
    await update.message.reply_text("❌ Unsubscribed from daily alerts.")


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
            await update.message.reply_text("Admin already set. Ask existing admin to add you.")


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


# Add deal conversation
async def add_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    await update.message.reply_text("📝 *Add New Deal*\n\nEnter the deal title:", parse_mode="Markdown")
    return ADD_TITLE


async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"] = {"title": update.message.text}
    await update.message.reply_text("Choose a category:", reply_markup=category_keyboard())
    return ADD_CATEGORY


async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["deal"]["category"] = query.data.replace("cat_", "")
    await query.edit_message_text("Enter a short description (or /skip):")
    return ADD_DESCRIPTION


async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"]["description"] = update.message.text if update.message.text != "/skip" else ""
    await update.message.reply_text("Enter the affiliate/claim link (or /skip):")
    return ADD_LINK


async def add_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deal"]["link"] = update.message.text if update.message.text != "/skip" else ""
    await update.message.reply_text("Enter expiry date e.g. '2026-05-01' (or /skip):")
    return ADD_EXPIRY


async def add_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deal = context.user_data["deal"]
    deal["expiry"] = update.message.text if update.message.text != "/skip" else ""

    with get_db() as conn:
        conn.execute(
            "INSERT INTO deals (title, category, description, link, expiry) VALUES (?,?,?,?,?)",
            (deal["title"], deal["category"], deal["description"], deal["link"], deal["expiry"])
        )
        conn.commit()

    await update.message.reply_text(
        f"✅ Deal added!\n*{deal['title']}* [{deal['category']}]", parse_mode="Markdown"
    )
    return ConversationHandler.END


async def list_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    with get_db() as conn:
        rows = conn.execute("SELECT id, title, category, active FROM deals ORDER BY id DESC LIMIT 20").fetchall()
    if not rows:
        await update.message.reply_text("No deals yet.")
        return
    text = "*All Deals:*\n\n"
    for r in rows:
        status = "✅" if r["active"] else "❌"
        text += f"{status} ID {r['id']}: [{r['category']}] {r['title']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


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


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── Daily alerts ───────────────────────────────────────────────────────────────

async def send_daily_alerts(context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        subscribers = conn.execute(
            "SELECT user_id FROM subscribers WHERE active=1"
        ).fetchall()
        deals = conn.execute(
            "SELECT * FROM deals WHERE active=1 ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

    if not deals or not subscribers:
        return

    text = "🎰 *Daily iGaming Deals*\n\n"
    for deal in deals:
        text += f"[{deal['category']}] *{deal['title']}*\n"
        if deal['description']:
            text += f"{deal['description']}\n"
        if deal['link']:
            text += f"🔗 [Claim]({deal['link']})\n"
        text += "\n"
    text += "_Use /browse to see all deals by category._"

    for sub in subscribers:
        try:
            await context.bot.send_message(
                chat_id=sub["user_id"],
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning(f"Failed to send alert to {sub['user_id']}: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("adddeal", add_deal)],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            ADD_CATEGORY: [CallbackQueryHandler(add_category, pattern="^cat_")],
            ADD_DESCRIPTION: [MessageHandler(filters.TEXT, add_description)],
            ADD_LINK: [MessageHandler(filters.TEXT, add_link)],
            ADD_EXPIRY: [MessageHandler(filters.TEXT, add_expiry)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("browse", browse))
    app.add_handler(CommandHandler("latest", latest))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("setadmin", setadmin))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("listdeals", list_deals))
    app.add_handler(CommandHandler("delete", delete_deal))
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(browse_callback, pattern="^browse_"))

    # Daily alert at 9:00 AM
    app.job_queue.run_daily(send_daily_alerts, time=time(hour=9, minute=0))

    logger.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
