import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/bot.db")
DB_PATH.parent.mkdir(exist_ok=True)


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # сообщения за текущий месяц
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        count INTEGER DEFAULT 0
    )
    """)

    # админы
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        name TEXT
    )
    """)

    # мета (для хранения текущего месяца)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    conn.close()


# ─────────────────────────────
# ГЛОБАЛЬНЫЙ СБРОС МЕСЯЦА
# ─────────────────────────────
def check_month_reset():
    conn = get_conn()
    cur = conn.cursor()

    current_month = datetime.now().strftime("%Y-%m")

    cur.execute(
        "SELECT value FROM meta WHERE key = 'current_month'"
    )
    row = cur.fetchone()

    if not row:
        # первый запуск
        cur.execute(
            "INSERT INTO meta (key, value) VALUES ('current_month', ?)",
            (current_month,)
        )
    elif row[0] != current_month:
        # месяц сменился → сброс у всех
        cur.execute("DELETE FROM messages")
        cur.execute(
            "UPDATE meta SET value = ? WHERE key = 'current_month'",
            (current_month,)
        )

    conn.commit()
    conn.close()


# ─────────────────────────────
# СООБЩЕНИЯ
# ─────────────────────────────
def add_message(user_id: int, username: str):
    check_month_reset()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT count FROM messages WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()

    if row:
        cur.execute(
            "UPDATE messages SET count = count + 1 WHERE user_id = ?",
            (user_id,)
        )
    else:
        cur.execute(
            "INSERT INTO messages (user_id, username, count) VALUES (?, ?, 1)",
            (user_id, username)
        )

    conn.commit()
    conn.close()


def get_user_count(user_id: int) -> int:
    check_month_reset()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT count FROM messages WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def get_all():
    check_month_reset()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, count FROM messages ORDER BY count DESC"
    )
    data = cur.fetchall()
    conn.close()
    return data


# ─────────────────────────────
# АДМИНЫ
# ─────────────────────────────
def add_admin(user_id: int, name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO admins (user_id, name) VALUES (?, ?)",
        (user_id, name)
    )
    conn.commit()
    conn.close()


def remove_admin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM admins WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()


def get_admins():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, name FROM admins"
    )
    data = cur.fetchall()
    conn.close()
    return data


def is_admin(user_id: int, owner_id: int) -> bool:
    if user_id == owner_id:
        return True

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM admins WHERE user_id = ?",
        (user_id,)
    )
    res = cur.fetchone()
    conn.close()
    return res is not None
