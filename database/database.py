import sqlite3
import os

DB_NAME = "database/verify_manager.db"


def get_connection():
    os.makedirs("database", exist_ok=True)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# יצירת טבלת אימותים אם לא קיימת
def create_tables():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            id_photo TEXT,
            selfie TEXT,
            social TEXT,
            video TEXT,
            code TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# שליפת אימותים לפי סטטוס
def get_verifications_by_status(status):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM verifications WHERE status = ? ORDER BY id DESC", (status,))
    rows = cur.fetchall()

    conn.close()
    return rows


# שליפת אימות לפי ID
def get_verification_by_id(verif_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM verifications WHERE id = ?", (verif_id,))
    row = cur.fetchone()

    conn.close()
    return row


# עדכון סטטוס אימות
def update_verification_status(verif_id, new_status):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("UPDATE verifications SET status = ? WHERE id = ?", (new_status, verif_id))
    conn.commit()
    conn.close()


# מחיקת אימות
def delete_verification(verif_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM verifications WHERE id = ?", (verif_id,))
    conn.commit()
    conn.close()
