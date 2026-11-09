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
import hmac
import hashlib
import json
from urllib.parse import parse_qsl

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


def verify_init_data(init_data: str, max_age: int = 86400):
    """Validates Telegram WebApp initData (HMAC with the bot token).
    Returns the Telegram user id, or None if invalid/expired."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got_hash = pairs.pop("hash", None)
        if not got_hash:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got_hash):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return int(json.loads(pairs["user"])["id"])
    except Exception:
        return None


@flask_app.after_request
def add_cors(resp):
    # ads.html is hosted on GitHub Pages (another origin) and calls these endpoints.
    if request.path in ("/client_ad_ping", "/ad_status"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@flask_app.route("/monetag_postback", methods=["GET", "POST"])
def monetag_postback():
    """AUTHORITATIVE server-to-server callback from Monetag confirming a
    real ad event. Configure this URL in your Monetag SDK zone settings:
    https://YOUR_RENDER_URL/monetag_postback?ymid={ymid}&event={event}&zone_id={zone_id}&secret=YOUR_POSTBACK_SECRET

    This is the ONLY place an ad is counted. Only events listed in
    config.COUNTED_EVENTS (impression) count; clicks are ignored."""
    args = request.values
    logger.info(f"[postback] incoming: {dict(args)}")

    if args.get("secret") != config.POSTBACK_SECRET:
        logger.warning("[postback] rejected: wrong secret")
        return jsonify({"status": "error", "message": "invalid secret"}), 403

    user_id = args.get("ymid") or args.get("user_id")
    if not user_id:
        return jsonify({"status": "error", "message": "missing ymid"}), 400
    try:
        user_id = int(user_id)
    except ValueError:
        return jsonify({"status": "error", "message": "ymid must be numeric"}), 400

    event = (args.get("event") or "impression").strip().lower()
    if event in config.IGNORED_EVENTS:
        row = db.get_or_create_user(user_id)
        return jsonify({"status": "ignored", "reason": f"event '{event}' not counted",
                        "user_id": user_id, "ads_watched": row["ads_watched"]})

    counted, new_count = db.register_ad(
        user_id, config.ADS_REQUIRED, config.ADS_MIN_INTERVAL_SECONDS,
        source="postback", dedupe_window=config.DEDUPE_WINDOW_SECONDS,
    )
    logger.info(f"[postback] user {user_id} event={event} counted={counted} total={new_count}")
    return jsonify({"status": "ok", "counted": counted, "user_id": user_id, "ads_watched": new_count})


@flask_app.route("/client_ad_ping", methods=["POST", "OPTIONS"])
def client_ad_ping():
    """ads.html reports a finished ad, with Telegram's signed initData.
    Counted only if the signature is valid (so it is for a real Telegram user,
    not a made-up id), and never twice for the same ad as the Monetag postback."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not config.CLIENT_FALLBACK_ENABLED:
        return jsonify({"status": "disabled"})
    uid = verify_init_data(request.values.get("init_data", ""))
    if uid is None:
        logger.warning("[client ping] rejected: invalid initData")
        return jsonify({"status": "error", "message": "invalid init_data"}), 403
    counted, total = db.register_ad(
        uid, config.ADS_REQUIRED, config.CLIENT_MIN_INTERVAL_SECONDS,
        source="client", dedupe_window=config.DEDUPE_WINDOW_SECONDS,
    )
    logger.info(f"[client ping] user {uid} counted={counted} total={total}")
    return jsonify({"status": "ok", "counted": counted, "ads_watched": total})


@flask_app.route("/ad_status", methods=["GET", "OPTIONS"])
def ad_status():
    """Lets ads.html show the real, server-verified count."""
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        uid = int(request.args.get("user_id", ""))
    except ValueError:
        return jsonify({"status": "error", "message": "bad user_id"}), 400
    row = db.get_or_create_user(uid)
    return jsonify({"ads_watched": row["ads_watched"], "required": config.ADS_REQUIRED})


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
