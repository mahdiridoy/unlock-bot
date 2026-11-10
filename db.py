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
            created_at INTEGER,
            updated_at INTEGER
        )
    """)
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
