"""
Flask server with two endpoints:

1. /monetag_postback - the AUTHORITATIVE, server-to-server callback Monetag
   calls when it has confirmed an ad event really happened. This is the one
   that actually counts and can't be faked by the user.

   In your Monetag dashboard, under the SDK zone's Postback URL setting, put:
   https://YOUR_DOMAIN/monetag_postback?ymid={ymid}&event={event}&zone_id={zone_id}&secret=YOUR_POSTBACK_SECRET
   Monetag fills in {ymid} etc. with real values. ymid is whatever you
   passed from ads.html - we pass the Telegram user id there, so ymid IS
   the Telegram user_id.

2. /client_ad_ping - an OPTIONAL, non-authoritative ping straight from the
   browser (ads.html) right after the Promise resolves, purely so the UI can
   update instantly. This can be spoofed by a technical user opening dev
   tools, so it does NOT increment the real counter - it's just logged.
   The real increment only happens via /monetag_postback above.
"""

from flask import Flask, request, jsonify
import db
import config

app = Flask(__name__)
db.init_db()


@app.route("/monetag_postback", methods=["GET", "POST"])
def monetag_postback():
    args = request.values  # works for both GET query params and POST form data

    secret = args.get("secret")
    if secret != config.POSTBACK_SECRET:
        return jsonify({"status": "error", "message": "invalid secret"}), 403

    # ymid is the Telegram user id we passed into show_11237862({ymid: ...})
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


@app.route("/client_ad_ping", methods=["POST"])
def client_ad_ping():
    """Non-authoritative - just for logging/debugging. Does not affect the
    real ad count, which only updates from the Monetag server postback."""
    user_id = request.values.get("user_id")
    print(f"[client ping] user {user_id} finished an ad locally (unverified)")
    return jsonify({"status": "logged"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
