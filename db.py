import sqlite3
from datetime import datetime

DB_PATH = "data/stats.db"


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        count INTEGER
    )
    """)

    # ⬇️ ДОБАВЛЕНО поле name, user_id сохранён
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        name TEXT
    )
    """)

    conn.commit()
    conn.close()


def add_message(user_id: int, username: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO messages (user_id, username, count)
    VALUES (?, ?, 1)
    ON CONFLICT(user_id) DO UPDATE SET
        count = count + 1,
        username = excluded.username
    """, (user_id, username))

    conn.commit()
    conn.close()


def get_all_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, count FROM messages")
    data = cur.fetchall()
    conn.close()
    return data


def clear_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM messages")
    conn.commit()
    conn.close()


# ---- ADMINS ----

# ⬇️ ИЗМЕНЕНО: добавлено имя (старые ID не трогаются)
def add_admin(user_id: int, name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO admins (user_id, name) VALUES (?, ?)",
        (user_id, name)
    )
    conn.commit()
    conn.close()


def del_admin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ⬇️ ИЗМЕНЕНО: возвращаем ID + имя
def get_admins():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, name FROM admins")
    data = cur.fetchall()
    conn.close()
    return data


def is_admin(user_id: int, owner_id: int):
    if user_id == owner_id:
        return True

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()

    return result is not None
