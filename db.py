import sqlite3
import time
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            ads_watched INTEGER DEFAULT 0,
            step2_claimed INTEGER DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER,
            last_ad_at INTEGER DEFAULT 0,
            last_postback_at INTEGER DEFAULT 0,
            last_client_at INTEGER DEFAULT 0
        )
    """)
    # Upgrade older databases that don't have last_ad_at yet.
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
    for col in ("last_ad_at", "last_postback_at", "last_client_at"):
        if col not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def get_or_create_user(user_id: int, username: str = None):
    conn = get_conn()
    now = int(time.time())
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, ads_watched, step2_claimed, created_at, updated_at, last_ad_at) "
        "VALUES (?, ?, 0, 0, ?, ?, 0)",
        (user_id, username, now, now),
    )
    if username:
        conn.execute("UPDATE users SET username = ? WHERE user_id = ? AND (username IS NULL OR username != ?)",
                     (username, user_id, username))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row)


def register_ad(user_id: int, max_ads: int, min_interval: int = 0,
                source: str = "postback", dedupe_window: int = 0):
    """Counts ONE ad atomically. source is "postback" (Monetag) or "client".
    - never above max_ads
    - same source: at least min_interval seconds apart
    - other source counted within dedupe_window seconds => this is the same ad, skip
    Returns (counted: bool, new_count: int)."""
    mine, other = ("last_postback_at", "last_client_at") if source == "postback" else ("last_client_at", "last_postback_at")
    get_or_create_user(user_id)
    now = int(time.time())
    conn = get_conn()
    cur = conn.execute(
        f"UPDATE users SET ads_watched = ads_watched + 1, last_ad_at = ?, {mine} = ?, updated_at = ? "
        f"WHERE user_id = ? AND ads_watched < ? "
        f"AND (? - COALESCE({mine}, 0)) >= ? AND (? - COALESCE({other}, 0)) >= ?",
        (now, now, now, user_id, max_ads, now, min_interval, now, dedupe_window),
    )
    conn.commit()
    counted = cur.rowcount == 1
    row = conn.execute("SELECT ads_watched FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return counted, (row["ads_watched"] if row else 0)


def increment_ads_watched(user_id: int) -> int:
    """Kept for compatibility. Increments and returns the new count."""
    conn = get_conn()
    conn.execute(
        "UPDATE users SET ads_watched = ads_watched + 1, updated_at = ? WHERE user_id = ?",
        (int(time.time()), user_id),
    )
    conn.commit()
    row = conn.execute("SELECT ads_watched FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row["ads_watched"] if row else 0


def set_ads_watched(user_id: int, count: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET ads_watched = ?, updated_at = ? WHERE user_id = ?",
        (count, int(time.time()), user_id),
    )
    conn.commit()
    conn.close()


def mark_step2_claimed(user_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET step2_claimed = 1, updated_at = ? WHERE user_id = ?",
        (int(time.time()), user_id),
    )
    conn.commit()
    conn.close()
