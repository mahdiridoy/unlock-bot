import sqlite3
import time
import re
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
            step2_claimed_at INTEGER DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER
        )
    """)
    # Migration: add step2_claimed_at column if it doesn't exist
    try:
        conn.execute("ALTER TABLE users ADD COLUMN step2_claimed_at INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS apk_storage (
            app_type TEXT PRIMARY KEY,  -- 'tv' or 'mobile'
            message_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            version TEXT NOT NULL,
            file_size INTEGER,
            updated_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_apk_versions (
            user_id INTEGER NOT NULL,
            app_type TEXT NOT NULL,  -- 'tv' or 'mobile'
            version TEXT NOT NULL,
            updated_at INTEGER,
            PRIMARY KEY (user_id, app_type)
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


def mark_step2_claimed(user_id: int):
    conn = get_conn()
    now = int(time.time())
    conn.execute(
        "UPDATE users SET step2_claimed = 1, step2_claimed_at = ?, updated_at = ? WHERE user_id = ?",
        (now, now, user_id),
    )
    conn.commit()
    conn.close()


def is_unlock_expired(user_id: int, hours: int = 1) -> bool:
    """Check if user's unlock has expired (default 1 hour)"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT step2_claimed_at FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        # Column doesn't exist in old DB schema - treat as not expired
        conn.close()
        return False
    conn.close()
    if not row or not row["step2_claimed_at"]:
        return True
    return (int(time.time()) - row["step2_claimed_at"]) > (hours * 3600)


# ─────────────────────────── APK Storage ───────────────────────────────

def parse_version(filename: str) -> str | None:
    """Extract version from filename like 'MahSuratStreamTV_V1.0.0.263.apk' -> '1.0.0.263'"""
    match = re.search(r'_V?(\d+(?:\.\d+)+)', filename)
    return match.group(1) if match else None


def version_tuple(version: str) -> tuple:
    """Convert '1.0.0.263' -> (1, 0, 0, 263) for comparison"""
    return tuple(map(int, version.split('.')))


def is_newer_version(new_ver: str, current_ver: str) -> bool:
    """Return True if new_ver > current_ver"""
    try:
        return version_tuple(new_ver) > version_tuple(current_ver)
    except Exception:
        return False


def save_apk_info(app_type: str, message_id: int, file_name: str, version: str, file_size: int = None):
    """Save or update APK info if version is newer"""
    conn = get_conn()
    now = int(time.time())
    
    # Check current version
    row = conn.execute(
        "SELECT version FROM apk_storage WHERE app_type = ?", (app_type,)
    ).fetchone()
    
    if row is None or is_newer_version(version, row["version"]):
        conn.execute("""
            INSERT OR REPLACE INTO apk_storage 
            (app_type, message_id, file_name, version, file_size, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (app_type, message_id, file_name, version, file_size, now))
        conn.commit()
        conn.close()
        return True  # Updated
    conn.close()
    return False  # Not newer


def get_apk_info(app_type: str) -> dict | None:
    """Get latest APK info for app_type ('tv' or 'mobile')"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM apk_storage WHERE app_type = ?", (app_type,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────── User APK Version Tracking ─────────────────

def get_user_apk_version(user_id: int, app_type: str) -> str | None:
    """Get the APK version user last received for app_type"""
    conn = get_conn()
    row = conn.execute(
        "SELECT version FROM user_apk_versions WHERE user_id = ? AND app_type = ?",
        (user_id, app_type)
    ).fetchone()
    conn.close()
    return row["version"] if row else None


def set_user_apk_version(user_id: int, app_type: str, version: str):
    """Record the APK version user received"""
    conn = get_conn()
    now = int(time.time())
    conn.execute("""
        INSERT OR REPLACE INTO user_apk_versions (user_id, app_type, version, updated_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, app_type, version, now))
    conn.commit()
    conn.close()


def get_all_user_ids() -> list[int]:
    """Every user the bot knows (anyone who ran /start). Used for APK update
    broadcasts — per-deploy DB wipes make version/claim records unreliable."""
    conn = get_conn()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def reset_user_progress(user_id: int):
    """Reset step2_claimed AND ads_watched so the user must redo both steps."""
    conn = get_conn()
    conn.execute("""
        UPDATE users SET step2_claimed = 0, ads_watched = 0, step2_claimed_at = 0, updated_at = ? WHERE user_id = ?
    """, (int(time.time()), user_id))
    conn.commit()
    conn.close()


def reset_expired_unlocks(hours: int = 1) -> int:
    """Auto-reset users whose 1-hour unlock has lapsed. Returns how many were reset."""
    conn = get_conn()
    now = int(time.time())
    cur = conn.execute("""
        UPDATE users SET step2_claimed = 0, ads_watched = 0, step2_claimed_at = 0, updated_at = ?
        WHERE step2_claimed = 1 AND (step2_claimed_at = 0 OR (? - step2_claimed_at) > ?)
    """, (now, now, hours * 3600))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


