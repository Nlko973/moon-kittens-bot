import sqlite3
from pathlib import Path

DB_PATH = Path("data/bot.db")


def get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # таблица сообщений
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        user_id INTEGER,
        username TEXT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (user_id)
    )
    """)

    # таблица админов
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        name TEXT
    )
    """)

    # безопасное добавление колонки name (если таблица старая)
    cur.execute("PRAGMA table_info(admins)")
    columns = [row[1] for row in cur.fetchall()]
    if "name" not in columns:
        cur.execute("ALTER TABLE admins ADD COLUMN name TEXT")

    conn.commit()
    conn.close()


# ===== СООБЩЕНИЯ =====

def add_message(user_id: int, username: str):
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


def get_all_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, count FROM messages ORDER BY count DESC")
    data = cur.fetchall()
    conn.close()
    return data


# ===== АДМИНЫ =====

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
    res = cur.fetchone()
    conn.close()
    return res is not None
