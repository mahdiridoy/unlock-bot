"""
Combined entry point for FREE hosting (e.g. Render's free Web Service tier).

Why combined: free tiers that don't sleep usually only exist for services
that receive real HTTP traffic ("Web Services"), not for background workers
(those need a paid plan on most platforms). So this file runs:

  1. The Telegram bot (long-polling) in a background thread
  2. A Flask app (health check + Monetag postback + client ping) in the
     main thread, bound to the PORT the host gives us

An external free uptime monitor (e.g. UptimeRobot) pings /health every few
minutes, which counts as "traffic" and stops the free host from putting the
service to sleep — keeping the bot's polling loop alive 24/7 for free.

Deploy: set the start command to `python app.py` on your host.
"""

import os
import logging
import threading
import asyncio
import time

from flask import Flask, request, jsonify

import config
import db
from bot import build_application

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────── Flask app ───────────────────────────────

flask_app = Flask(__name__)
db.init_db()

bot_thread = None  # set once the bot thread starts, checked by /health below


@flask_app.route("/health", methods=["GET"])
def health():
    """Hit by your free uptime monitor to keep the service awake.
    Now also reports whether the bot thread is actually alive, so a crash
    shows up as a real alert instead of hiding behind a 200 OK forever."""
    bot_alive = bot_thread is not None and bot_thread.is_alive()
    status_code = 200 if bot_alive else 503
    return jsonify({"status": "healthy" if bot_alive else "bot_down", "bot_thread_alive": bot_alive}), status_code


@flask_app.route("/monetag_postback", methods=["GET", "POST"])
def monetag_postback():
    """AUTHORITATIVE server-to-server callback from Monetag confirming a
    real ad completion. Configure this URL in your Monetag SDK zone settings:
    https://YOUR_RENDER_URL/monetag_postback?ymid={ymid}&event={event}&zone_id={zone_id}&secret=YOUR_POSTBACK_SECRET
    """
    args = request.values

    secret = args.get("secret")
    if secret != config.POSTBACK_SECRET:
        return jsonify({"status": "error", "message": "invalid secret"}), 403

    user_id = args.get("ymid") or args.get("user_id")
    if not user_id:
        return jsonify({"status": "error", "message": "missing ymid"}), 400

    try:
        user_id = int(user_id)
    except ValueError:
        return jsonify({"status": "error", "message": "ymid must be numeric"}), 400

    row = db.get_or_create_user(user_id)
    if row["ads_watched"] < config.ADS_REQUIRED:
        new_count = db.increment_ads_watched(user_id)
    else:
        new_count = row["ads_watched"]

    return jsonify({"status": "ok", "user_id": user_id, "ads_watched": new_count})


@flask_app.route("/client_ad_ping", methods=["POST"])
def client_ad_ping():
    """Non-authoritative — just for logging. Real count only updates via
    /monetag_postback above."""
    user_id = request.values.get("user_id")
    logger.info(f"[client ping] user {user_id} finished an ad locally (unverified)")
    return jsonify({"status": "logged"})


# ─────────────────────────── Bot thread ──────────────────────────────

def run_bot():
    # Python 3.10+ (and especially 3.12+/3.14) no longer auto-creates an
    # event loop for non-main threads, so we must create and set one
    # explicitly before python-telegram-bot's run_polling() can use it.
    while True:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            application = build_application()
            logger.info("Bot starting (polling mode, background thread)...")
            # stop_signals=None: signal handlers only work in the main thread,
            # and this runs in a background thread, so we disable them here.
            application.run_polling(stop_signals=None)
        except Exception:
            # Without this, an unhandled exception here kills the thread
            # silently — /health keeps returning "healthy" forever while
            # the bot itself stops responding to every button and command.
            logger.exception("Bot polling loop crashed, restarting in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Flask server starting on port {port}...")
    flask_app.run(host="0.0.0.0", port=port)
