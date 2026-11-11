import json
import logging
import re
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
        db.reset_user_progress(user_id)
        return
    
    apk_info = db.get_apk_info(app_type)
    logger.info(f"📥 download_apk: user={user_id}, app_type={app_type}, apk_info={apk_info}")
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
        logger.info(f"📥 download_apk: showing success buttons for user={user_id}")
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
        db.reset_user_progress(user_id)
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
    db.reset_user_progress(user_id)
    
    await query.edit_message_text(
        "🔄 Starting over...\n\n"
        f"Step 1: Watch {config.ADS_REQUIRED} ads to unlock apps.",
        reply_markup=step1_keyboard(0)
    )


def _storage_channel_matches(chat_id, username) -> bool:
    """True if chat_id/username belong to the configured APK storage channel.
    Matches by numeric id (any prefix style) OR by channel username, so a
    missing/placeholder APK_STORAGE_CHANNEL_ID on the host doesn't silently
    drop every upload."""
    digits_recv = re.sub(r"\D", "", str(chat_id))
    # Accept the storage channel OR the join channel (APK Pulse) — the bot is
    # admin of both; the placeholder storage id matched nothing and silently
    # dropped every upload.
    for cand in (config.APK_STORAGE_CHANNEL_ID, getattr(config, "TELEGRAM_CHANNEL_ID", "")):
        # tolerate whitespace/quotes from copy-paste into Render env vars
        configured = re.sub(r"\s", "", str(cand)).strip().strip('"').strip("'")
        if re.fullmatch(r"-?\d+", configured):  # ignore placeholder like -100xxxxxxxxxx
            digits_conf = re.sub(r"\D", "", configured)
            if len(digits_conf) >= 9 and (
                digits_recv == digits_conf
                or digits_recv.endswith(digits_conf)
                or digits_conf.endswith(digits_recv)
            ):
                return True
    username = username or ""
    expected_user = str(getattr(config, "APK_STORAGE_CHANNEL_USERNAME", "")).lstrip("@").lower()
    return bool(expected_user) and username.lower() == expected_user


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-detect APK uploads to @MahSuratAPKStorage and save latest version."""
    msg = update.channel_post or update.edited_channel_post
    if not msg or not msg.document:
        return

    logger.info(f"📥 Channel post received: chat_id={msg.chat_id}, username=@{getattr(msg.chat, 'username', None)}, file={msg.document.file_name}")

    if not _storage_channel_matches(msg.chat_id, getattr(msg.chat, "username", None)):
        logger.warning(f"📥 Ignoring - channel mismatch: got chat_id={msg.chat_id} username=@{getattr(msg.chat, 'username', None)}, expected APK_STORAGE_CHANNEL_ID={config.APK_STORAGE_CHANNEL_ID} or APK_STORAGE_CHANNEL_USERNAME=@{getattr(config, 'APK_STORAGE_CHANNEL_USERNAME', None)}")
        return

    await _handle_new_apk(context, msg.document, msg.message_id)


async def _handle_new_apk(context: ContextTypes.DEFAULT_TYPE, doc, channel_message_id: int):
    """Save a newer APK + notify/reset users. Shared by the channel_post
    handler and the DM-forward fallback (for when channel posts never arrive).
    Returns True if the APK was stored (newer), False otherwise."""
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
        return False

    # Extract version
    version = db.parse_version(file_name)
    if not version:
        logger.warning(f"Could not parse version from {file_name}")
        return False

    # Save if newer
    updated = db.save_apk_info(
        app_type=app_type,
        message_id=channel_message_id,
        file_name=file_name,
        version=version,
        file_size=file_size
    )

    if updated:
        logger.info(f"✅ Updated {app_type} APK: {file_name} v{version} (msg_id={channel_message_id})")
        
        # Notify ALL known users (per-deploy DB wipes empty the version/claim
        # tables, so targeted-only notify would silently reach nobody), and
        # reset them so the new APK requires a fresh unlock.
        targets = set(db.get_all_user_ids())
        for user_id in targets:
            try:
                db.reset_user_progress(user_id)
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
    return updated


async def apk_forward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback when channel_post updates never reach the bot: forward the
    APK message from the storage channel to the bot in DM. Telegram sets
    forward_origin, which can't be forged, so this is as trustworthy as the
    channel auto-detect. copyMessage needs the channel message_id, which the
    forward origin carries."""
    msg = update.message
    if not msg or not msg.document:
        return

    origin = getattr(msg, "forward_origin", None)
    origin_chat_id = None
    origin_msg_id = getattr(msg, "forward_from_message_id", None)
    origin_username = None
    origin_chat = getattr(origin, "chat", None) if origin is not None else None
    if origin_chat is not None:
        origin_chat_id = origin_chat.id
        origin_username = getattr(origin_chat, "username", None)
        origin_msg_id = getattr(origin, "message_id", None) or origin_msg_id
    elif getattr(msg, "forward_from_chat", None) is not None:  # legacy field
        origin_chat_id = msg.forward_from_chat.id
        origin_username = getattr(msg.forward_from_chat, "username", None)

    if origin_chat_id is None:
        return  # not forwarded from a channel
    if not _storage_channel_matches(origin_chat_id, origin_username):
        logger.info(f"📥 Forward from unconfigured channel chat={origin_chat_id} @{origin_username}")
        await msg.reply_text(
            f"ℹ️ This channel isn't your APK storage channel (id `{origin_chat_id}`).\n\n"
            f"To use it for APK auto-detect: set `APK_STORAGE_CHANNEL_ID={origin_chat_id}` "
            f"on Render and redeploy — then uploads work automatically."
        )
        return
    if not origin_msg_id:
        logger.warning("📥 Forward missing channel message_id; APK not stored")
        return

    logger.info(f"📥 APK forward received: channel_msg_id={origin_msg_id}, file={msg.document.file_name}")
    stored = await _handle_new_apk(context, msg.document, origin_msg_id)
    if stored:
        await msg.reply_text("✅ APK registered and users notified. Check /apk_status to confirm.")
    else:
        await msg.reply_text("ℹ️ APK not stored (unrecognized filename/version, or not newer). Check the filename matches MahSuratStreamTV_V*.apk / MahSuratStream_V*.apk and try again. /apk_status shows current state.")


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
        db.reset_user_progress(user_id)
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
                f"callback_query={update.callback_query.data if update.callback_query else None}, "
                f"channel_post={bool(update.channel_post)}, "
                f"edited_channel_post={bool(update.edited_channel_post)}, "
                f"message={bool(update.message)}, "
                f"doc={bool(update.message.document if update.message else (update.channel_post.document if update.channel_post else False))}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Optional /status command so users can check progress anytime."""
    user_id = update.effective_user.id
    row = db.get_or_create_user(user_id, update.effective_user.username)
    
    # Also show APK info
    tv_apk = db.get_apk_info("tv")
    mobile_apk = db.get_apk_info("mobile")
    
    await update.message.reply_text(
        f"Ads watched: {row['ads_watched']}/{config.ADS_REQUIRED}\n"
        f"Step 2 claimed: {'Yes' if row['step2_claimed'] else 'No'}\n"
        f"Unlock expired: {'Yes' if db.is_unlock_expired(user_id) else 'No'}\n\n"
        f"📱 TV App: {tv_apk['file_name'] if tv_apk else 'Not uploaded'} (v{tv_apk['version'] if tv_apk else 'N/A'})\n"
        f"📱 Mobile App: {mobile_apk['file_name'] if mobile_apk else 'Not uploaded'} (v{mobile_apk['version'] if mobile_apk else 'N/A'})"
    )


async def apk_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to check stored APK info"""
    tv_apk = db.get_apk_info("tv")
    mobile_apk = db.get_apk_info("mobile")
    
    text = "📦 <b>Stored APK Info:</b>\n\n"
    if tv_apk:
        text += f"📺 <b>TV App:</b>\n"
        text += f"  File: {tv_apk['file_name']}\n"
        text += f"  Version: {tv_apk['version']}\n"
        text += f"  Msg ID: {tv_apk['message_id']}\n"
        text += f"  Size: {tv_apk.get('file_size', 'N/A')}\n\n"
    else:
        text += "📺 <b>TV App:</b> Not uploaded\n\n"
    
    if mobile_apk:
        text += f"📱 <b>Mobile App:</b>\n"
        text += f"  File: {mobile_apk['file_name']}\n"
        text += f"  Version: {mobile_apk['version']}\n"
        text += f"  Msg ID: {mobile_apk['message_id']}\n"
        text += f"  Size: {mobile_apk.get('file_size', 'N/A')}\n"
    else:
        text += "📱 <b>Mobile App:</b> Not uploaded\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def scan_channel_apks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: Info about APK scanning"""
    await update.message.reply_text(
        "📋 <b>APK Scanning Info</b>\n\n"
        "Bot API cannot scan channel history (requires userbot).\n\n"
        "<b>For existing APKs in @MahSuratAPKStorage:</b>\n"
        "1. Re-upload the APK files to the channel\n"
        "2. Bot will auto-detect and store them instantly\n\n"
        "<b>For new APKs:</b>\n"
        "Just upload to @MahSuratAPKStorage — bot detects automatically.\n\n"
        "Use <code>/apk_status</code> to check currently stored APKs.",
        parse_mode=ParseMode.HTML
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


async def _auto_reset_expired_loop():
    """Background task: every 5 minutes, reset unlocks older than 1 hour."""
    while True:
        await asyncio.sleep(300)
        try:
            n = db.reset_expired_unlocks(1)
            if n:
                logger.info(f"⏰ Auto-reset {n} expired unlock(s)")
        except Exception:
            logger.exception("Auto-reset of expired unlocks failed")


_reset_task = None


async def _post_init(application):
    global _reset_task
    # Plain asyncio task: PTB's create_task here warns that it won't be awaited
    _reset_task = asyncio.create_task(_auto_reset_expired_loop(), name="auto-reset-expired")


async def _post_shutdown(application):
    global _reset_task
    if _reset_task:
        _reset_task.cancel()
        _reset_task = None


def build_application():
    """Builds and returns the PTB Application with all handlers registered,
    without starting polling. Used both by main() below (standalone run)
    and by app.py (combined bot + web server, for free-tier hosting)."""
    application = Application.builder().token(config.BOT_TOKEN).post_init(_post_init).post_shutdown(_post_shutdown).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("apk_status", apk_status))
    application.add_handler(CommandHandler("scan_apks", scan_channel_apks))
    application.add_handler(CallbackQueryHandler(check_ads_callback, pattern="^check_ads$"))
    application.add_handler(CallbackQueryHandler(verify_step2_callback, pattern="^verify_step2$"))
    application.add_handler(CallbackQueryHandler(download_apk_callback, pattern="^download_apk:"))
    application.add_handler(CallbackQueryHandler(back_to_apps_callback, pattern="^back_to_apps$"))
    application.add_handler(CallbackQueryHandler(start_over_callback, pattern="^start_over$"))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    # Channel post handler for auto-detecting APK uploads to @MahSuratAPKStorage
    # Use ChatType.CHANNEL + Document filter to catch all channel posts with files (PTB v21+)
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.Document.ALL, channel_post_handler))
    # Fallback: admin forwards the APK message from the storage channel to the bot in DM
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL, apk_forward_handler))
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
    application.run_polling(
        allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post", "callback_query"],
    )


if __name__ == "__main__":
    main()
