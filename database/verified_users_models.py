"""
database/verified_users_models.py
─────────────────────────────────────────────────────────────────────────────
טבלאות DB למודול ניהול מאומתים — VerifyManager

טבלאות:
    user_warnings           — אזהרות למאומת
    user_suspensions        — השעיות (פעילות + היסטוריה)
    user_messages_log       — לוג הודעות ששוגרו מהמנהל
    user_admin_notes        — הערות פנימיות של המנהל
    catalogs                — קטלוגים דינמיים (כולל קהל יעד והגדרות)
    user_type_assignments   — סוג המשתמש לכל מאומת
─────────────────────────────────────────────────────────────────────────────
"""

import logging

from database.database import get_connection

logger = logging.getLogger(__name__)


def init_verified_users_db() -> None:
    """יוצר את כל הטבלאות אם אינן קיימות, ומרחיב טבלאות קיימות בעמודות חדשות."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # ── אזהרות ────────────────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                reason      TEXT    NOT NULL,
                created_by  INTEGER,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── השעיות ────────────────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_suspensions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id      INTEGER NOT NULL,
                duration_key     TEXT    NOT NULL,
                suspended_until  TEXT,
                reason           TEXT,
                is_active        INTEGER DEFAULT 1,
                created_by       INTEGER,
                created_at       TEXT    DEFAULT (datetime('now')),
                lifted_at        TEXT
            )
        """)

        # ── לוג הודעות ────────────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_messages_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                message     TEXT    NOT NULL,
                sent_by     INTEGER,
                sent_at     TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── הערות פנימיות ─────────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_admin_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                note        TEXT    NOT NULL,
                created_by  INTEGER,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── קטלוגים ───────────────────────────────────────────────────────────
        # נוצרת עם כל העמודות המורחבות.
        # אם הטבלה כבר קיימת ללא העמודות החדשות — הן יתווספו ב-ALTER להלן.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS catalogs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                slug            TEXT    NOT NULL UNIQUE,
                name            TEXT    NOT NULL,
                audience        TEXT    NOT NULL DEFAULT 'custom',
                is_publishable  INTEGER NOT NULL DEFAULT 0,
                is_readonly     INTEGER NOT NULL DEFAULT 0,
                is_active       INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT    DEFAULT (datetime('now'))
            )
        """)

        # הוספת עמודות חדשות לטבלה קיימת — SQLite אינו תומך ב-IF NOT EXISTS
        # בפקודת ADD COLUMN, ולכן כל עמודה עטופה ב-try/except.
        _safe_add_columns(cursor, "catalogs", [
            ("audience",       "TEXT    NOT NULL DEFAULT 'custom'"),
            ("is_publishable", "INTEGER NOT NULL DEFAULT 0"),
            ("is_readonly",    "INTEGER NOT NULL DEFAULT 0"),
        ])

        # ── סוגי משתמש ────────────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_type_assignments (
                telegram_id  INTEGER PRIMARY KEY,
                type_key     TEXT    NOT NULL DEFAULT 'verified',
                assigned_by  INTEGER,
                assigned_at  TEXT    DEFAULT (datetime('now'))
            )
        """)

        # ── לוג פעולות ניהוליות ───────────────────────────────────────────────
        # מתעד פעולות שאין להן טבלה ייעודית: חסימה, שחרור חסימה, ביטול אימות.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_action_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                action      TEXT    NOT NULL,
                performed_by INTEGER,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)

        conn.commit()
    logger.info("verified_users_db initialized (v3 — action log added).")


# ─────────────────────────────────────────────────────────────────────────────
# עזר פנימי
# ─────────────────────────────────────────────────────────────────────────────

def _safe_add_columns(
    cursor,
    table: str,
    columns: list,
) -> None:
    """
    מנסה להוסיף כל עמודה לטבלה.
    אם העמודה כבר קיימת SQLite זורקת OperationalError — מתעלמים ממנה.
    """
    for col_name, col_def in columns:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # העמודה כבר קיימת — המשך
