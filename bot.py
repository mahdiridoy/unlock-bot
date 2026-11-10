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
    MessageHandler,
    filters,
)

import config
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────── Keyboards ───────────────────────────────

def step1_keyboard(ads_watched: int):
    # Pass backend URL to ads.html so client_ad_ping works on any deployment
    ads_url = f"{config.ADS_WEBAPP_URL}?backend={config.BACKEND_URL}"
    rows = [
        [InlineKeyboardButton(
            f"▶️ Open Ads Page ({ads_watched}/{config.ADS_REQUIRED} done)",
            web_app=WebAppInfo(url=ads_url),
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


async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle data sent from ads.html via Telegram.WebApp.sendData()"""
    data = update.effective_message.web_app_data.data
    try:
        payload = json.loads(data)
        if payload.get("type") == "ads_complete":
            user_id = update.effective_user.id
            user_row = db.get_or_create_user(user_id, update.effective_user.username)
            if user_row["ads_watched"] >= config.ADS_REQUIRED:
                text = (
                    "🎉 Step 1 complete! You've watched all required ads.\n\n"
                    "Now finish *Step 2* — follow us everywhere below, then tap Unlock."
                )
                # Send to user's private chat (not reply to web_app_data message)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=step2_keyboard()
                )
    except Exception as e:
        logger.warning(f"web_app_data parse failed: {e}")


async def download_apk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send APK from storage channel using copyMessage (bypasses 50MB limit)."""
    query = update.callback_query
    await query.answer("Sending APK...")
    
    # Parse app_type from callback_data: "download_apk:tv" or "download_apk:mobile"
    app_type = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    
    # Check if unlock expired
    user_row = db.get_or_create_user(user_id, query.from_user.username)
    if not user_row["step2_claimed"] or db.is_unlock_expired(user_id):
        await query.edit_message_text(
            "⏰ Your unlock has expired (1 hour limit).\n\n"
            "Please complete the steps again to get the latest APK.",
            reply_markup=step1_keyboard(0)
        )
        # Reset for fresh start
        db.reset_user_step2(user_id)
        db.set_ads_watched(user_id, 0)
        return
    
    apk_info = db.get_apk_info(app_type)
    if not apk_info:
        await query.edit_message_text(
            f"❌ No {app_type} APK uploaded yet.\n"
            f"Ask admin to upload to @MahSuratAPKStorage"
        )
        return
    
    try:
        await query.edit_message_text(f"📤 Sending {apk_info['file_name']} (v{apk_info['version']})...")
        
        await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=config.APK_STORAGE_CHANNEL_ID,
            message_id=apk_info["message_id"],
            caption=f"📱 {apk_info['file_name']}\nVersion: v{apk_info['version']}"
        )
        
        # Track user's version
        db.set_user_apk_version(user_id, app_type, apk_info["version"])
        
        # Show success with BACK button and START OVER button
        buttons = [
            [InlineKeyboardButton("🔙 Back to Apps", callback_data="back_to_apps")],
            [InlineKeyboardButton("🔄 Start Over", callback_data="start_over")],
        ]
        await query.edit_message_text(
            f"✅ {apk_info['file_name']} (v{apk_info['version']}) sent!\n\n"
            f"Tap below to get the other app or restart:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        
    except Exception as e:
        logger.exception(f"copyMessage failed for {app_type}: {e}")
        await query.edit_message_text(
            f"❌ Failed to send APK.\n"
            f"Error: {str(e)[:200]}\n\n"
            f"Make sure bot is admin in storage channel."
        )


async def back_to_apps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to the apps selection menu"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    # Check if unlock expired
    user_row = db.get_or_create_user(user_id, query.from_user.username)
    if not user_row["step2_claimed"] or db.is_unlock_expired(user_id):
        await query.edit_message_text(
            "⏰ Your unlock has expired (1 hour limit).\n\n"
            "Please complete the steps again to get the latest APK.",
            reply_markup=step1_keyboard(0)
        )
        db.reset_user_step2(user_id)
        db.set_ads_watched(user_id, 0)
        return
    
    buttons = [
        [InlineKeyboardButton("1️⃣ TV App", callback_data="download_apk:tv")],
        [InlineKeyboardButton("2️⃣ Mobile App", callback_data="download_apk:mobile")],
        [InlineKeyboardButton("3️⃣ Telegram Movie Bot", url=config.TELEGRAM_MOVIE_BOT_LINK)],
    ]
    
    await query.edit_message_text(
        "🎉 Verified! Here are your unlocked apps (valid for 1 hour):\n\n"
        "Tap each button to get the latest APK:\n"
        "• 1️⃣ TV App — MahSuratStream TV\n"
        "• 2️⃣ Mobile App — MahSuratStream\n"
        "• 3️⃣ Telegram Movie Bot",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def start_over_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset everything and show Step 1"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    # Reset user progress
    db.reset_user_step2(user_id)
    db.set_ads_watched(user_id, 0)
    
    await query.edit_message_text(
        "🔄 Starting over...\n\n"
        f"Step 1: Watch {config.ADS_REQUIRED} ads to unlock apps.",
        reply_markup=step1_keyboard(0)
    )


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-detect APK uploads to @MahSuratAPKStorage and save latest version."""
    msg = update.channel_post or update.edited_channel_post
    if not msg or not msg.document:
        return
    
    # Debug: log all channel posts
    logger.info(f"📥 Channel post received: chat_id={msg.chat_id}, file={msg.document.file_name}")
    logger.info(f"📥 Configured APK_STORAGE_CHANNEL_ID={config.APK_STORAGE_CHANNEL_ID}")
    
    # Only process messages from the configured storage channel
    # Compare both with and without -100 prefix
    configured_id = str(config.APK_STORAGE_CHANNEL_ID)
    received_id = str(msg.chat_id)
    
    if received_id != configured_id and received_id != configured_id.lstrip("-100") and received_id != "-" + configured_id.lstrip("-100"):
        logger.warning(f"📥 Ignoring - channel mismatch: got {received_id}, expected {configured_id}")
        return
    
    doc = msg.document
    file_name = doc.file_name or ""
    file_size = doc.file_size
    
    # Determine app type from filename
    app_type = None
    if config.APK_PATTERN_TV in file_name:
        app_type = "tv"
    elif config.APK_PATTERN_MOBILE in file_name:
        app_type = "mobile"
    else:
        logger.info(f"📥 Not our APK pattern: {file_name} (looking for {config.APK_PATTERN_TV} or {config.APK_PATTERN_MOBILE})")
        return  # Not our APK
    
    # Extract version
    version = db.parse_version(file_name)
    if not version:
        logger.warning(f"Could not parse version from {file_name}")
        return
    
    # Save if newer
    updated = db.save_apk_info(
        app_type=app_type,
        message_id=msg.message_id,
        file_name=file_name,
        version=version,
        file_size=file_size
    )
    
    if updated:
        logger.info(f"✅ Updated {app_type} APK: {file_name} v{version} (msg_id={msg.message_id})")
        
        # Notify users who have older version and reset their step2
        old_users = db.get_users_with_old_version(app_type, version)
        for user_id in old_users:
            try:
                db.reset_user_step2(user_id)
                app_name = "TV App" if app_type == "tv" else "Mobile App"
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🔔 <b>Update Available!</b>\n\n"
                        f"New version of <b>{app_name}</b> is ready: <b>v{version}</b>\n\n"
                        f"To get the latest APK, please complete the unlock steps again:\n"
                        f"1. Watch {config.ADS_REQUIRED} ads\n"
                        f"2. Follow our socials\n\n"
                        f"Tap /start to begin."
                    ),
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"📢 Notified user {user_id} about {app_type} update v{version}")
            except Exception as e:
                logger.warning(f"Failed to notify user {user_id}: {e}")
    else:
        logger.info(f"ℹ️ Skipped {app_type} APK {file_name} v{version} (not newer)")


async def verify_step2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    user_row = db.get_or_create_user(user_id, query.from_user.username)
    logger.info(f"🔓 verify_step2: user={user_id}, ads_watched={user_row['ads_watched']}, step2_claimed={user_row['step2_claimed']}")
    
    if user_row["ads_watched"] < config.ADS_REQUIRED:
        await query.edit_message_text(
            "⚠️ You still need to finish Step 1 first (watch all the ads).",
            reply_markup=step1_keyboard(user_row["ads_watched"]),
        )
        return

    # Check if previous unlock expired (1 hour)
    if user_row["step2_claimed"] and db.is_unlock_expired(user_id):
        db.reset_user_step2(user_id)
        user_row["step2_claimed"] = 0
        user_row["ads_watched"] = 0
        db.set_ads_watched(user_id, 0)
        logger.info(f"🔓 verify_step2: unlock expired for user={user_id}, reset progress")

    # Real, verifiable check: is the user actually a member of the Telegram channel?
    logger.info(f"🔓 verify_step2: checking membership for user={user_id} in channel={config.TELEGRAM_CHANNEL_ID}")
    is_member = await check_telegram_membership(context, user_id)
    logger.info(f"🔓 verify_step2: membership result for user={user_id}: {is_member}")

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
    logger.info(f"🔓 verify_step2: success for user={user_id}, marked step2_claimed")

    # Buttons for TV and Mobile apps (stored in @MahSuratAPKStorage)
    buttons = [
        [InlineKeyboardButton("1️⃣ TV App", callback_data="download_apk:tv")],
        [InlineKeyboardButton("2️⃣ Mobile App", callback_data="download_apk:mobile")],
        [InlineKeyboardButton("3️⃣ Telegram Movie Bot", url=config.TELEGRAM_MOVIE_BOT_LINK)],
    ]

    await query.edit_message_text(
        "🎉 Verified! Here are your unlocked apps (valid for 1 hour):\n\n"
        "Tap each button to get the latest APK:\n"
        "• 1️⃣ TV App — MahSuratStream TV\n"
        "• 2️⃣ Mobile App — MahSuratStream\n"
        "• 3️⃣ Telegram Movie Bot",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def check_telegram_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Returns True only if the bot can confirm real membership.
    Requires the bot to be an ADMIN of TELEGRAM_CHANNEL_ID."""
    try:
        logger.info(f"🔓 check_membership: calling get_chat_member for user={user_id}, chat={config.TELEGRAM_CHANNEL_ID}")
        member = await context.bot.get_chat_member(
            chat_id=config.TELEGRAM_CHANNEL_ID, user_id=user_id
        )
        logger.info(f"🔓 check_membership: result for user={user_id}: status={member.status}")
        return member.status not in ("left", "kicked")
    except Exception as e:
        logger.error(f"🔓 check_membership: FAILED for user={user_id}: {e}")
        # If the bot isn't admin yet or chat_id is wrong, this will always fail.
        return False


async def debug_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug: log every update type received"""
    logger.info(f"🔍 UPDATE: type={update.__class__.__name__}, "
                f"chat={update.effective_chat.id if update.effective_chat else None}, "
                f"user={update.effective_user.id if update.effective_user else None}, "
                f"channel_post={bool(update.channel_post)}, "
                f"edited_channel_post={bool(update.edited_channel_post)}, "
                f"message={bool(update.message)}, "
                f"doc={bool(update.message.document if update.message else (update.channel_post.document if update.channel_post else False))}")


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
    application.add_handler(CallbackQueryHandler(download_apk_callback, pattern="^download_apk:"))
    application.add_handler(CallbackQueryHandler(back_to_apps_callback, pattern="^back_to_apps$"))
    application.add_handler(CallbackQueryHandler(start_over_callback, pattern="^start_over$"))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    # Channel post handler for auto-detecting APK uploads to @MahSuratAPKStorage
    # Use ChatType.CHANNEL + Document filter to catch all channel posts with files (PTB v21+)
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.Document.ALL, channel_post_handler))
    # Debug: log ALL updates
    application.add_handler(MessageHandler(filters.ALL, debug_all_updates), group=-1)
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
