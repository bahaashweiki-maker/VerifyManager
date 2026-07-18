"""
database/permission_models.py
─────────────────────────────────────────────────────────────────────────────
טבלת הרשאות מרכזית — VerifyManager Permission System

מטרה:
    מגדירה טבלה אחת (user_permissions) שמקשרת בין telegram_id לרשימת הרשאות.
    הרשאות הן מחרוזות חופשיות לחלוטין — אין רשימה קבועה, אין enum, אין validation.
    כל מודול מגדיר את ההרשאות שלו באופן עצמאי בעת הצורך.

שימוש בהפעלה:
    from database.permission_models import init_permissions_db
    init_permissions_db()

הטבלה:
    user_permissions
    ├── id          — מזהה ייחודי פנימי
    ├── telegram_id — מזהה הטלגרם של המשתמש
    ├── permission  — מחרוזת חופשית כלשהי ("admin", "verify.review", ...)
    ├── granted_by  — telegram_id של מי שנתן את ההרשאה (אופציונלי)
    └── granted_at  — תאריך ושעת המתן

הרחבה:
    להוספת הרשאה חדשה — אין צורך לשנות קובץ זה כלל.
    פשוט קרא ל-grant_permission(user_id, "כל.מחרוזת.שתרצה").
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import sqlite3

from database.database import get_connection

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_permissions (
    id          INTEGER   PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER   NOT NULL,
    permission  TEXT      NOT NULL,
    granted_by  INTEGER   DEFAULT NULL,
    granted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(telegram_id, permission)
);

CREATE INDEX IF NOT EXISTS idx_permissions_telegram_id
    ON user_permissions (telegram_id);

CREATE INDEX IF NOT EXISTS idx_permissions_permission
    ON user_permissions (permission);
"""


def init_permissions_db() -> bool:
    """
    יוצר את טבלת user_permissions אם אינה קיימת.
    בטוח לקריאה חוזרת בכל הפעלה (idempotent).

    Returns:
        True אם הצליח, False אם נכשל.
    """
    try:
        with get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
        logger.info("Permission DB initialized successfully.")
        return True
    except sqlite3.Error as exc:
        logger.critical("init_permissions_db failed: %s", exc, exc_info=True)
        return False