import os

# ── Telegram bot token (from BotFather) ─────────────────────────────
# NOTE: since this token was pasted in a chat, it's effectively exposed.
# Recommended: revoke it via BotFather (/revoke) and generate a new one,
# then set it as an environment variable instead of hardcoding it here.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8678859276:AAHojaYn_1oLAYut8fj0zwaEuZ3uS3ZgZtI")

# ── Channel the user must join (bot must be ADMIN here) ─────────────
# Use the numeric chat id (starts with -100...) if possible — more reliable
# than invite links for getChatMember. See README section on how to get it.
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@your_channel_username_or_id")
TELEGRAM_CHANNEL_INVITE_LINK = "https://t.me/+iy-lf73ooaA0YTk1"

# ── Social links (honor-system, not programmatically verifiable) ───
FACEBOOK_LINK_1 = "https://www.facebook.com/share/1GFY5GMTF8/"
FACEBOOK_LINK_2 = "https://www.facebook.com/share/1ESSAeXnvQ/"
YOUTUBE_LINK = "https://youtube.com/@nm-djridoy?si=XrYD0EJz1o3aKa7b"

# ── How many ads must be watched before unlocking step 2 ────────────
ADS_REQUIRED = 10

# ── Monetag SDK zone (Telegram Mini App ad format) ───────────────────
MONETAG_ZONE_ID = "11237862"

# ── URL where ads.html is hosted (must be HTTPS — GitHub Pages works) ─
# Example: "https://yourusername.github.io/unlock-bot-ads/ads.html"
ADS_WEBAPP_URL = os.environ.get("ADS_WEBAPP_URL", "https://PUT_YOUR_HOSTED_ADS_HTML_URL_HERE")

# ── The final reward link unlocked after both steps ──────────────────
FINAL_UNLOCK_LINK = "https://mahdiridoy.github.io/Tv/ridoyiptv.m3u"

# ── Database file ────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "bot_data.db")

# ── Shared secret so Monetag postback can't be spoofed easily ────────
POSTBACK_SECRET = os.environ.get("POSTBACK_SECRET", "change-this-secret")
