"""Standalone web server only (no bot). Uses the exact same routes as app.py
so the ad-counting logic lives in ONE place. For deployment use app.py."""
import os
from app import flask_app as app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
