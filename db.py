import sqlite3
import time
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
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
            updated_at INTEGER
        )
    """)
    conn.commit()
    conn.close()


def get_or_create_user(user_id: int, username: str = None):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        now = int(time.time())
        conn.execute(
            "INSERT INTO users (user_id, username, ads_watched, step2_claimed, created_at, updated_at) "
            "VALUES (?, ?, 0, 0, ?, ?)",
            (user_id, username, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row)


def increment_ads_watched(user_id: int) -> int:
    """Increments ad count and returns the new count."""
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
