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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
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

def add_admin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def del_admin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_admins():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM admins")
    data = [row[0] for row in cur.fetchall()]
    conn.close()
    return data


def is_admin(user_id: int, owner_id: int):
    return user_id == owner_id or user_id in get_admins()
