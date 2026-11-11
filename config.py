import os

# ── Telegram bot token (from BotFather) ─────────────────────────────
# Read ONLY from the BOT_TOKEN environment variable / secret.
# No hardcoded fallback, so the token never lives in the source code.
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not set. Add it as a secret / environment variable named BOT_TOKEN."
    )

# ── Channel the user must join (bot must be ADMIN here) ─────────────
# Use the numeric chat id (starts with -100...) if possible — more reliable
# than invite links for getChatMember. See README section on how to get it.
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@your_channel_username_or_id")
TELEGRAM_CHANNEL_INVITE_LINK = "https://t.me/+iy-lf73ooaA0YTk1"

# ── Social links (honor-system, not programmatically verifiable) ───
FACEBOOK_LINK_1 = "https://www.facebook.com/share/1GFY5GMTF8/"
FACEBOOK_LINK_2 = "https://www.facebook.com/share/1ESSAeXnvQ/"
YOUTUBE_LINK = "https://youtube.com/@MahSuratTube?si=XrYD0EJz1o3aKa7b"

# ── How many ads must be watched before unlocking step 2 ────────────
ADS_REQUIRED = 2

# ── Monetag SDK zone (Telegram Mini App ad format) ───────────────────
MONETAG_ZONE_ID = "12223543"

# ── URL where ads.html is hosted (must be HTTPS — GitHub Pages works) ─
# Example: "https://yourusername.github.io/unlock-bot-ads/ads.html"
ADS_WEBAPP_URL = os.environ.get("ADS_WEBAPP_URL", "https://PUT_YOUR_HOSTED_ADS_HTML_URL_HERE")

# ── Backend URL (Render) for ad postback — used by ads.html ──────────
BACKEND_URL = os.environ.get("BACKEND_URL", "https://unlock-bot-xieo.onrender.com")

# ── Telegram Movie Bot link ──────────────────────────────────────────
TELEGRAM_MOVIE_BOT_LINK = "https://t.me/mahsuratstreamtg_bot"

# ── Database file ────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "bot_data.db")

# ── Shared secret so Monetag postback can't be spoofed easily ────────
POSTBACK_SECRET = os.environ.get("POSTBACK_SECRET", "change-this-secret")

# ── APK Storage Channel (bot must be ADMIN here) ─────────────────────
# Forward a message from @MahSuratAPKStorage to @RawDataBot to get numeric ID
APK_STORAGE_CHANNEL_ID = os.environ.get("APK_STORAGE_CHANNEL_ID", "-100xxxxxxxxxx")

# APK filename patterns for auto-detection
APK_PATTERN_TV = "MahSuratStreamTV"
APK_PATTERN_MOBILE = "MahSuratStream"
