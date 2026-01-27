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
