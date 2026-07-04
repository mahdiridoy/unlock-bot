# Telegram Unlock Bot — FULLY FREE Deployment Guide

Two pieces, two free homes:
- `ads.html` → **GitHub Pages** (static, free forever)
- Everything else (`app.py`, `bot.py`, `db.py`, `config.py`) → **Render.com free Web Service**, kept awake with a free **UptimeRobot** monitor

---

## Part A — Host `ads.html` on GitHub Pages

1. Create a new GitHub repo, e.g. `unlock-ads` (public).
2. Upload just `ads.html` to it.
3. Repo → **Settings → Pages** → Source: deploy from `main` branch, root folder.
4. Wait ~1 min, you'll get a URL like:
   `https://mahdiridoy.github.io/unlock-ads/ads.html`
5. You'll paste this into `config.py`'s `ADS_WEBAPP_URL` (Part C below).

---

## Part B — Add the bot as ADMIN of your Telegram channel

Required so the bot can verify real membership.
1. Your channel → Manage Channel → Administrators → Add Admin → your bot.
2. Forward any message from the channel to **@RawDataBot** — it replies with the numeric chat ID (`-100...`).
3. Save that number for Part C.

---

## Part C — Deploy the bot + server on Render (free)

1. Push this whole folder (`app.py`, `bot.py`, `db.py`, `config.py`, `requirements.txt`, `Procfile`) to a **second** GitHub repo, e.g. `unlock-bot`.
2. Go to **render.com** → sign up free → **New → Web Service**.
3. Connect your `unlock-bot` repo.
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python app.py`
   - **Instance Type:** Free
5. Add Environment Variables (Render dashboard → Environment):
   - `BOT_TOKEN` = your real token (revoke the one you pasted in chat via BotFather `/revoke`, use the new one here)
   - `TELEGRAM_CHANNEL_ID` = the numeric ID from Part B
   - `ADS_WEBAPP_URL` = your GitHub Pages URL from Part A
   - `POSTBACK_SECRET` = make up any random string
6. Deploy. Render gives you a URL like `https://unlock-bot-xxxx.onrender.com`.

---

## Part D — Wire up Monetag's postback (makes ad-watching REAL)

In your Monetag dashboard, under the SDK zone (11237862) → Postback URL, set:
```
https://unlock-bot-xxxx.onrender.com/monetag_postback?ymid={ymid}&event={event}&zone_id={zone_id}&secret=YOUR_POSTBACK_SECRET
```
(Use your actual Render URL and the same secret you set in Part C.)

Also open `ads.html` and set `POSTBACK_BASE` to your Render URL, then re-upload it to GitHub Pages.

---

## Part E — Keep the free Render service awake (free)

Render's free tier sleeps after 15 minutes with no HTTP traffic — which would kill your bot's polling loop too. Fix, for free:
1. Sign up at **uptimerobot.com** (free plan).
2. Add a new monitor: HTTP(s), URL = `https://unlock-bot-xxxx.onrender.com/health`, interval = every 5 minutes.
3. That's it — the ping counts as traffic, so Render never sleeps, so your bot never stops polling.

---

## How the flow works end to end

1. `/start` → bot shows "Open Ads Page" (opens `ads.html` as a Telegram Mini App, from GitHub Pages).
2. User taps "Watch Ad" 5 times inside the Mini App. Each real completion triggers Monetag's server postback → hits your Render app → increments their count in the DB.
3. User returns to the chat, taps "Check my progress".
4. At 5/5 → bot shows Step 2 (Facebook, YouTube, Telegram buttons + Unlock).
5. Telegram join is verified for real via `getChatMember`. Facebook/YouTube stay honor-system — no public API can verify these.
6. On success → bot sends your `FINAL_UNLOCK_LINK`.

---

## Local testing (optional, before deploying)
```bash
pip install -r requirements.txt --break-system-packages
python app.py
```
This runs both the bot and the Flask server together on your machine. For Monetag's postback to reach you locally, use `ngrok http 5000` and put the ngrok URL into Monetag's dashboard temporarily.

## Files in this project
- `app.py` — **the file you actually deploy.** Runs bot + Flask together (needed for free hosting).
- `bot.py` — bot logic/handlers, also runnable standalone (`python bot.py`) for local testing without Flask.
- `postback_server.py` — standalone Flask-only version, kept for reference/local testing; not needed if using `app.py`.
- `db.py` — SQLite storage.
- `ads.html` — the Mini App page with Monetag's ad SDK, goes to GitHub Pages.
- `config.py` — all your links, IDs, and secrets.
