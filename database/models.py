from database.database import get_connection


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    print("TABLES CREATED")

    # משתמשים
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        full_name TEXT,
        username TEXT,
        is_admin INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # אימותים
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        id_photo TEXT,
        selfie TEXT,
        social TEXT,
        video TEXT,
        code TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # עמודים
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_key TEXT UNIQUE,
        title TEXT,
        text TEXT,
        image TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # כפתורים
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS buttons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_key TEXT,
        title TEXT,
        target_page TEXT,
        order_index INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()
