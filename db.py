import sqlite3

conn = sqlite3.connect("data/stats.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users_stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            message_count INTEGER
        )
    """)
    conn.commit()

def add_user(user_id, username):
    cursor.execute("""
        INSERT OR IGNORE INTO users_stats
        VALUES (?, ?, 0)
    """, (user_id, username))
    conn.commit()

def increment(user_id, username):
    add_user(user_id, username)
    cursor.execute("""
        UPDATE users_stats
        SET message_count = message_count + 1,
            username = ?
        WHERE user_id = ?
    """, (username, user_id))
    conn.commit()

def get_all():
    cursor.execute("""
        SELECT username, message_count
        FROM users_stats
        ORDER BY message_count DESC
    """)
    return cursor.fetchall()

def clear_all():
    cursor.execute("DELETE FROM users_stats")
    conn.commit()

def create_admins_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()


def add_admin(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def remove_admin(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_admins() -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM admins")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]


def is_admin(user_id: int, owner_id: int) -> bool:
    if user_id == owner_id:
        return True
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result is not None
