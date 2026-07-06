from database.database import get_connection


def get_user_by_telegram_id(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )

    user = cursor.fetchone()

    conn.close()
    return user


def create_user(telegram_id: int, full_name: str, username: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO users
        (telegram_id, full_name, username)
        VALUES (?, ?, ?)
    """, (
        telegram_id,
        full_name,
        username
    ))

    conn.commit()
    conn.close()


def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users")

    users = cursor.fetchall()

    conn.close()
    return users