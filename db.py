import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import WEEKLY_NORM_DEFAULT

DB_PATH = Path("data/bot.db")
DB_PATH.parent.mkdir(exist_ok=True)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def week_start_for(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now()
    monday = dt.date() - timedelta(days=dt.weekday())
    return monday.isoformat()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _has_column(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cur.fetchall())


def _ensure_column(cur: sqlite3.Cursor, table: str, column: str, ddl: str):
    if not _has_column(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            is_member INTEGER DEFAULT 1,
            left_at TEXT,
            first_seen_at TEXT,
            last_message_at TEXT,
            inactive_notice_at TEXT,
            inactive_warned_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_stats (
            week_start TEXT,
            user_id INTEGER,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (week_start, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            name TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rests (
            user_id INTEGER PRIMARY KEY,
            role_name TEXT,
            expires_at TEXT,
            created_at TEXT,
            created_by INTEGER
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            admin_id INTEGER,
            reason TEXT,
            warn_type TEXT DEFAULT 'manual',
            created_at TEXT,
            active INTEGER DEFAULT 1
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mutes (
            user_id INTEGER PRIMARY KEY,
            until_at TEXT,
            old_title TEXT,
            was_admin INTEGER DEFAULT 0,
            issued_by INTEGER,
            reason TEXT,
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            display_name TEXT,
            text TEXT NOT NULL,
            created_at TEXT
        )
        """
    )

    # Migration from old schema
    _ensure_column(cur, "users", "inactive_notice_at", "TEXT")
    _ensure_column(cur, "users", "inactive_warned_at", "TEXT")
    _ensure_column(cur, "users", "first_seen_at", "TEXT")
    _ensure_column(cur, "warns", "expires_at", "TEXT")

    if get_setting("weekly_norm", cur) is None:
        set_setting("weekly_norm", str(WEEKLY_NORM_DEFAULT), cur)

    if get_setting("cleanup_enabled", cur) is None:
        set_setting("cleanup_enabled", "1", cur)

    if get_setting("cleanup_skip_once", cur) is None:
        set_setting("cleanup_skip_once", "0", cur)

    if get_setting("cleanup_skip_week_start", cur) is None:
        set_setting("cleanup_skip_week_start", "", cur)

    if get_setting("tg_links_block", cur) is None:
        set_setting("tg_links_block", "0", cur)

    conn.commit()
    conn.close()


# settings

def get_setting(key: str, cur: Optional[sqlite3.Cursor] = None, default: Optional[str] = None) -> Optional[str]:
    own_conn = None
    if cur is None:
        own_conn = get_conn()
        cur = own_conn.cursor()

    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()

    if own_conn:
        own_conn.close()

    if row is None:
        return default
    return row["value"]


def set_setting(key: str, value: str, cur: Optional[sqlite3.Cursor] = None):
    own_conn = None
    if cur is None:
        own_conn = get_conn()
        cur = own_conn.cursor()

    cur.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )

    if own_conn:
        own_conn.commit()
        own_conn.close()


def get_weekly_norm() -> int:
    return int(get_setting("weekly_norm", default=str(WEEKLY_NORM_DEFAULT)) or WEEKLY_NORM_DEFAULT)


def set_weekly_norm(value: int):
    set_setting("weekly_norm", str(value))


def is_cleanup_enabled() -> bool:
    return get_setting("cleanup_enabled", default="1") == "1"


def set_cleanup_enabled(enabled: bool):
    set_setting("cleanup_enabled", "1" if enabled else "0")
    # Enabling cleanup explicitly also clears one-time skip.
    if enabled:
        set_cleanup_skip_once(False)


def set_cleanup_skip_once(enabled: bool, at: Optional[datetime] = None):
    # Skip is bound to the current week only (Mon-Sun) and never spills to next week.
    set_setting("cleanup_skip_once", "1" if enabled else "0")
    if enabled:
        set_setting("cleanup_skip_week_start", week_start_for(at))
    else:
        set_setting("cleanup_skip_week_start", "")


def consume_cleanup_skip_once(at: Optional[datetime] = None) -> bool:
    at = at or datetime.now()
    current_week = week_start_for(at)
    skip_week = get_setting("cleanup_skip_week_start", default="") or ""
    legacy_skip = get_setting("cleanup_skip_once", default="0") == "1"

    should_skip = skip_week == current_week or (legacy_skip and not skip_week)

    # Always clear old boolean flag; clear week marker when consumed.
    if legacy_skip:
        set_setting("cleanup_skip_once", "0")
    if should_skip:
        set_setting("cleanup_skip_week_start", "")

    return should_skip


def is_cleanup_skip_once_enabled(at: Optional[datetime] = None) -> bool:
    at = at or datetime.now()
    current_week = week_start_for(at)
    skip_week = get_setting("cleanup_skip_week_start", default="") or ""
    legacy_skip = get_setting("cleanup_skip_once", default="0") == "1"
    return skip_week == current_week or (legacy_skip and not skip_week)


def get_last_cleanup_date() -> Optional[str]:
    return get_setting("last_cleanup_date")


def set_last_cleanup_date(value: str):
    set_setting("last_cleanup_date", value)


def is_tg_links_block_enabled() -> bool:
    return get_setting("tg_links_block", default="0") == "1"


def set_tg_links_block_enabled(enabled: bool):
    set_setting("tg_links_block", "1" if enabled else "0")


# users and stats

def upsert_user_profile(user_id: int, username: Optional[str], display_name: str):
    conn = get_conn()
    cur = conn.cursor()
    now = now_iso()
    cur.execute(
        """
        INSERT INTO users (user_id, username, display_name, first_seen_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            display_name = excluded.display_name,
            updated_at = excluded.updated_at
        """,
        (user_id, None, display_name, now, now),
    )
    conn.commit()
    conn.close()


def mark_user_joined(user_id: int, username: Optional[str], display_name: str, joined_at: Optional[datetime] = None):
    joined_at = joined_at or datetime.now()
    joined_iso = joined_at.isoformat(timespec="seconds")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, username, display_name, is_member, left_at, first_seen_at, updated_at)
        VALUES (?, ?, ?, 1, NULL, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            display_name = excluded.display_name,
            is_member = 1,
            left_at = NULL,
            first_seen_at = COALESCE(users.first_seen_at, excluded.first_seen_at),
            updated_at = excluded.updated_at
        """,
        (user_id, None, display_name, joined_iso, joined_iso),
    )
    conn.commit()
    conn.close()


def add_message(user_id: int, username: Optional[str], display_name: str, at: Optional[datetime] = None):
    at = at or datetime.now()
    at_iso = at.isoformat(timespec="seconds")
    week_start = week_start_for(at)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO users (user_id, username, display_name, is_member, left_at, first_seen_at, last_message_at, updated_at,
                           inactive_notice_at, inactive_warned_at)
        VALUES (?, ?, ?, 1, NULL, ?, ?, ?, NULL, NULL)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            display_name = excluded.display_name,
            is_member = 1,
            left_at = NULL,
            last_message_at = excluded.last_message_at,
            updated_at = excluded.updated_at,
            inactive_notice_at = NULL,
            inactive_warned_at = NULL
        """,
        (user_id, None, display_name, at_iso, at_iso, at_iso),
    )

    cur.execute(
        """
        INSERT INTO weekly_stats (week_start, user_id, count)
        VALUES (?, ?, 1)
        ON CONFLICT(week_start, user_id) DO UPDATE SET
            count = count + 1
        """,
        (week_start, user_id),
    )

    conn.commit()
    conn.close()


def mark_user_left(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET is_member = 0, left_at = ?, updated_at = ? WHERE user_id = ?",
        (now_iso(), now_iso(), user_id),
    )
    conn.commit()
    conn.close()


def get_user_id_by_username(username: str) -> Optional[int]:
    # Username lookup is not persisted in DB anymore.
    return None


def get_user_week_count(user_id: int, week_start: Optional[str] = None) -> int:
    week_start = week_start or week_start_for()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT count FROM weekly_stats WHERE week_start = ? AND user_id = ?",
        (week_start, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row["count"] if row else 0


def get_all_week_stats(week_start: Optional[str] = None, members_only: bool = True):
    week_start = week_start or week_start_for()
    conn = get_conn()
    cur = conn.cursor()

    query = (
        "SELECT u.user_id, u.username, u.display_name, u.is_member, "
        "COALESCE(w.count, 0) AS count "
        "FROM users u "
        "LEFT JOIN weekly_stats w ON u.user_id = w.user_id AND w.week_start = ? "
    )
    params = [week_start]

    if members_only:
        query += "WHERE u.is_member = 1 "

    query += "ORDER BY count DESC, u.display_name COLLATE NOCASE"

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_brief(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, display_name, is_member, last_message_at FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def delete_absent_over_30_days() -> int:
    cutoff = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id FROM users WHERE is_member = 0 AND left_at IS NOT NULL AND left_at <= ?",
        (cutoff,),
    )
    user_ids = [row["user_id"] for row in cur.fetchall()]

    if not user_ids:
        conn.close()
        return 0

    placeholders = ",".join("?" for _ in user_ids)
    cur.execute(f"DELETE FROM weekly_stats WHERE user_id IN ({placeholders})", user_ids)
    cur.execute(f"DELETE FROM rests WHERE user_id IN ({placeholders})", user_ids)
    cur.execute(f"DELETE FROM warns WHERE user_id IN ({placeholders})", user_ids)
    cur.execute(f"DELETE FROM mutes WHERE user_id IN ({placeholders})", user_ids)
    cur.execute(f"DELETE FROM users WHERE user_id IN ({placeholders})", user_ids)

    conn.commit()
    conn.close()
    return len(user_ids)


# admins

def add_admin(user_id: int, name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO admins (user_id, name) VALUES (?, ?)",
        (user_id, name),
    )
    conn.commit()
    conn.close()


def remove_admin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_admins():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, name FROM admins ORDER BY name COLLATE NOCASE")
    rows = cur.fetchall()
    conn.close()
    return rows


def is_admin(user_id: int, owner_id: int) -> bool:
    if user_id == owner_id:
        return True

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


# rests

def set_rest_until(user_id: int, role_name: str, expires_at: Optional[str], admin_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO rests (user_id, role_name, expires_at, created_at, created_by)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            role_name = excluded.role_name,
            expires_at = excluded.expires_at,
            created_at = excluded.created_at,
            created_by = excluded.created_by
        """,
        (user_id, role_name, expires_at, now_iso(), admin_id),
    )
    conn.commit()
    conn.close()


def set_rest(user_id: int, role_name: str, days: int, admin_id: int):
    expires_at = None
    if days > 0:
        expires_at = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    set_rest_until(user_id, role_name, expires_at, admin_id)


def remove_rest(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM rests WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def extend_rest(user_id: int, minutes: int) -> bool:
    if minutes <= 0:
        return False

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT expires_at FROM rests WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False

    now = datetime.now()
    current = row["expires_at"]
    if current:
        try:
            base = datetime.fromisoformat(current)
            if base < now:
                base = now
        except ValueError:
            base = now
    else:
        base = now

    expires_at = (base + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    cur.execute(
        "UPDATE rests SET expires_at = ?, created_at = ? WHERE user_id = ?",
        (expires_at, now_iso(), user_id),
    )
    conn.commit()
    conn.close()
    return True


def get_rest(user_id: int):
    _expire_old_rests()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rests WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_all_rests():
    _expire_old_rests()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.user_id, r.role_name, r.expires_at, u.username, u.display_name
        FROM rests r
        LEFT JOIN users u ON u.user_id = r.user_id
        ORDER BY r.created_at DESC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def is_on_rest(user_id: int) -> bool:
    return get_rest(user_id) is not None


def _expire_old_rests():
    conn = get_conn()
    cur = conn.cursor()
    now = now_iso()
    cur.execute("DELETE FROM rests WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
    conn.commit()
    conn.close()


# warns

def create_warn(
    user_id: int,
    admin_id: int,
    reason: str,
    warn_type: str = "manual",
    expires_at: Optional[str] = None,
    duration_minutes: int = 60 * 24 * 30,
) -> tuple[int, str]:
    if expires_at is None:
        expires_at = (datetime.now() + timedelta(minutes=max(1, duration_minutes))).isoformat(timespec="seconds")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO warns (user_id, admin_id, reason, warn_type, created_at, expires_at, active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (user_id, admin_id, reason, warn_type, now_iso(), expires_at),
    )
    warn_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(warn_id), expires_at


def remove_warn(warn_id: int) -> bool:
    _expire_old_warns()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE warns SET active = 0 WHERE id = ? AND active = 1", (warn_id,))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed > 0


def remove_latest_warn_by_user(user_id: int) -> Optional[int]:
    _expire_old_warns()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM warns WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    warn_id = int(row["id"])
    cur.execute("UPDATE warns SET active = 0 WHERE id = ?", (warn_id,))
    conn.commit()
    conn.close()
    return warn_id


def get_user_warns(user_id: int, active_only: bool = True):
    _expire_old_warns()
    conn = get_conn()
    cur = conn.cursor()
    query = (
        "SELECT id, user_id, admin_id, reason, warn_type, created_at, expires_at, active "
        "FROM warns WHERE user_id = ?"
    )
    params = [user_id]
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY id DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_warns(active_only: bool = True):
    _expire_old_warns()
    conn = get_conn()
    cur = conn.cursor()
    query = (
        "SELECT w.id, w.user_id, w.admin_id, w.reason, w.warn_type, w.created_at, w.expires_at, w.active, "
        "u.username, u.display_name "
        "FROM warns w "
        "LEFT JOIN users u ON u.user_id = w.user_id"
    )
    if active_only:
        query += " WHERE w.active = 1"
    query += " ORDER BY w.id DESC"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_active_warn_count(user_id: int) -> int:
    _expire_old_warns()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM warns WHERE user_id = ? AND active = 1", (user_id,))
    c = cur.fetchone()["c"]
    conn.close()
    return int(c)


def _expire_old_warns():
    conn = get_conn()
    cur = conn.cursor()
    now = now_iso()
    cur.execute(
        "UPDATE warns SET active = 0 WHERE active = 1 AND expires_at IS NOT NULL AND expires_at <= ?",
        (now,),
    )
    conn.commit()
    conn.close()


# inactivity

def get_inactive_candidates(days: int):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    now = now_iso()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT u.user_id, u.username, u.display_name, u.last_message_at,
               u.inactive_notice_at, u.inactive_warned_at
        FROM users u
        LEFT JOIN rests r ON r.user_id = u.user_id
                         AND (r.expires_at IS NULL OR r.expires_at > ?)
        WHERE u.is_member = 1
          AND u.last_message_at IS NOT NULL
          AND u.last_message_at <= ?
          AND r.user_id IS NULL
        """,
        (now, cutoff),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def mark_inactive_notice(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET inactive_notice_at = ? WHERE user_id = ?", (now_iso(), user_id))
    conn.commit()
    conn.close()


def mark_inactive_warned(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET inactive_warned_at = ? WHERE user_id = ?", (now_iso(), user_id))
    conn.commit()
    conn.close()


# cleanup

def get_cleanup_candidates(week_start: Optional[str] = None):
    week_start = week_start or week_start_for()
    now = now_iso()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT u.user_id, u.username, u.display_name, u.first_seen_at, COALESCE(w.count, 0) AS count
        FROM users u
        LEFT JOIN weekly_stats w ON w.user_id = u.user_id AND w.week_start = ?
        LEFT JOIN rests r ON r.user_id = u.user_id
                         AND (r.expires_at IS NULL OR r.expires_at > ?)
        WHERE u.is_member = 1
          AND r.user_id IS NULL
        ORDER BY count ASC, u.display_name COLLATE NOCASE
        """,
        (week_start, now),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# mutes

def set_mute(user_id: int, until_at: str, old_title: Optional[str], was_admin: bool, issued_by: int, reason: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mutes (user_id, until_at, old_title, was_admin, issued_by, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            until_at = excluded.until_at,
            old_title = excluded.old_title,
            was_admin = excluded.was_admin,
            issued_by = excluded.issued_by,
            reason = excluded.reason,
            created_at = excluded.created_at
        """,
        (user_id, until_at, old_title, 1 if was_admin else 0, issued_by, reason, now_iso()),
    )
    conn.commit()
    conn.close()


def remove_mute(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_mute(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mutes WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_expired_mutes(now: Optional[datetime] = None):
    now = now or datetime.now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mutes WHERE until_at <= ?", (now.isoformat(timespec="seconds"),))
    rows = cur.fetchall()
    conn.close()
    return rows


# complaints

def create_complaint(user_id: int, username: Optional[str], display_name: str, text: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO complaints (user_id, username, display_name, text, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, None, display_name, text, now_iso()),
    )
    complaint_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(complaint_id)


def get_user_complaints(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, username, display_name, text, created_at
        FROM complaints
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_complaints():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, username, display_name, text, created_at
        FROM complaints
        ORDER BY id DESC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_complaint(complaint_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed > 0
