import json
import logging
import urllib.request
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import config
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────── Keyboards ───────────────────────────────

def step1_keyboard(ads_watched: int):
    rows = [
        [InlineKeyboardButton(
            f"▶️ Open Ads Page ({ads_watched}/{config.ADS_REQUIRED} done)",
            web_app=WebAppInfo(url=config.ADS_WEBAPP_URL),
        )],
        [InlineKeyboardButton("🔄 Check my progress", callback_data="check_ads")],
    ]
    return InlineKeyboardMarkup(rows)


def step2_keyboard():
    rows = [
        [InlineKeyboardButton("📘 Follow Facebook Page 1", url=config.FACEBOOK_LINK_1)],
        [InlineKeyboardButton("📘 Follow Facebook Page 2", url=config.FACEBOOK_LINK_2)],
        [InlineKeyboardButton("▶️ Subscribe YouTube", url=config.YOUTUBE_LINK)],
        [InlineKeyboardButton("💬 Join Telegram Channel", url=config.TELEGRAM_CHANNEL_INVITE_LINK)],
        [InlineKeyboardButton("✅ I've done all of this — Unlock", callback_data="verify_step2")],
    ]
    return InlineKeyboardMarkup(rows)


# ─────────────────────────── Handlers ────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username)

    text = (
        f"👋 Welcome {user.first_name}!\n\n"
        f"To unlock your link, complete 2 quick steps:\n\n"
        f"*Step 1:* Watch {config.ADS_REQUIRED} ads below\n"
        f"*Step 2:* Follow our Facebook, YouTube & Telegram\n\n"
        f"Let's start with Step 1 👇"
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=step1_keyboard(0)
    )


async def check_ads_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_row = db.get_or_create_user(user_id, query.from_user.username)
    watched = user_row["ads_watched"]

    await query.answer()

    if watched >= config.ADS_REQUIRED:
        text = (
            "🎉 Step 1 complete! You've watched all required ads.\n\n"
            "Now finish *Step 2* — follow us everywhere below, then tap Unlock."
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=step2_keyboard()
        )
    else:
        text = (
            f"You've watched {watched}/{config.ADS_REQUIRED} ads.\n"
            f"Keep watching, then check again 👇"
        )
        await query.edit_message_text(text, reply_markup=step1_keyboard(watched))


async def verify_step2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_row = db.get_or_create_user(user_id, query.from_user.username)
    if user_row["ads_watched"] < config.ADS_REQUIRED:
        await query.edit_message_text(
            "⚠️ You still need to finish Step 1 first (watch all the ads).",
            reply_markup=step1_keyboard(user_row["ads_watched"]),
        )
        return

    # Real, verifiable check: is the user actually a member of the Telegram channel?
    is_member = await check_telegram_membership(context, user_id)

    if not is_member:
        await query.edit_message_text(
            "❌ We couldn't verify that you've joined the Telegram channel yet.\n\n"
            "Please join it, then tap Unlock again.\n"
            "(Facebook/YouTube follows are trusted on the honor system — "
            "please actually follow them, it supports the channel! 🙏)",
            reply_markup=step2_keyboard(),
        )
        return

    db.mark_step2_claimed(user_id)

    # Fetch the actual latest APK asset from each GitHub release
    repos = [
        ("1️⃣ TV App", "mahdiridoy/MahSuratStreamTV", config.SPECIAL_APP_URL_TV),
        ("2️⃣ Mobile App", "mahdiridoy/MahSuratStream", config.SPECIAL_APP_URL_STREAM),
    ]
    buttons = []
    for label, repo, fallback in repos:
        try:
            url, asset_name, tag = await asyncio.get_running_loop().run_in_executor(
                None, _latest_apk, repo
            )
            ver = f" ({tag})" if tag else ""
            if url:
                buttons.append([InlineKeyboardButton(f"{label}{ver}", url=url)])
            else:
                buttons.append([InlineKeyboardButton(f"{label}{ver}", url=fallback)])
        except Exception as e:
            logger.warning(f"latest apk fetch failed for {repo}: {e}")
            buttons.append([InlineKeyboardButton(label, url=fallback)])

    # Add the Telegram Movie Bot link as 3rd item
    buttons.append([InlineKeyboardButton("3️⃣ Telegram Movie Bot", url=config.TELEGRAM_MOVIE_BOT_LINK)])

    await query.edit_message_text(
        "🎉 Verified! Here are your unlocked apps:\n\n"
        "Tap each button to download/open:\n"
        "• 1️⃣ TV App — MahSuratStream TV\n"
        "• 2️⃣ Mobile App — MahSuratStream\n"
        "• 3️⃣ Telegram Movie Bot",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def check_telegram_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Returns True only if the bot can confirm real membership.
    Requires the bot to be an ADMIN of TELEGRAM_CHANNEL_ID."""
    try:
        member = await context.bot.get_chat_member(
            chat_id=config.TELEGRAM_CHANNEL_ID, user_id=user_id
        )
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.warning(f"Membership check failed for {user_id}: {e}")
        # If the bot isn't admin yet or chat_id is wrong, this will always fail.
        return False


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Optional /status command so users can check progress anytime."""
    user_id = update.effective_user.id
    row = db.get_or_create_user(user_id, update.effective_user.username)
    await update.message.reply_text(
        f"Ads watched: {row['ads_watched']}/{config.ADS_REQUIRED}\n"
        f"Step 2 claimed: {'Yes' if row['step2_claimed'] else 'No'}"
    )


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Logs any exception raised inside a handler instead of letting it
    disappear silently (which looks like the bot 'doing nothing')."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)


def _latest_apk(repo: str):
    """Return (download_url, asset_name, tag_name) for the newest .apk asset
    of the given GitHub repo's latest release. Falls back to the release page
    URL if no apk asset is found."""
    api = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(api, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "mahsurat-unlock-bot",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    tag = data.get("tag_name")
    page = data.get("html_url") or f"https://github.com/{repo}/releases/latest"
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".apk"):
            return asset.get("browser_download_url", page), name, tag
    return None, None, tag


def build_application():
    """Builds and returns the PTB Application with all handlers registered,
    without starting polling. Used both by main() below (standalone run)
    and by app.py (combined bot + web server, for free-tier hosting)."""
    application = Application.builder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(check_ads_callback, pattern="^check_ads$"))
    application.add_handler(CallbackQueryHandler(verify_step2_callback, pattern="^verify_step2$"))
    application.add_error_handler(error_handler)
    return application


def main():
    """Standalone run (e.g. local testing, or a host that runs bot.py directly).
    For free-tier deployment (Render + uptime monitor), use app.py instead."""
    db.init_db()
    application = build_application()
    logger.info("Bot starting (standalone polling mode)...")
    application.run_polling()


if __name__ == "__main__":
    main()
