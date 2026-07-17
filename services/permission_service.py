"""
services/permission_service.py
─────────────────────────────────────────────────────────────────────────────
מנהל ההרשאות המרכזי — VerifyManager Permission Manager

עקרון הפעולה:
    הרשאה היא מחרוזת חופשית לחלוטין.
    המערכת לא מכירה ולא מגבילה אילו מחרוזות תקינות.
    כל מודול בוחר את שמות ההרשאות שלו באופן עצמאי.

כלל מרכזי:
    כל בדיקת הרשאה עוברת דרך has_permission() בלבד.
    אין לבדוק תפקידים קשיחים (is_admin=1 וכד') — רק מחרוזת הרשאה.

שימוש בסיסי:
    from services.permission_service import has_permission

    if has_permission(user_id, "כל.מחרוזת.שתרצה"):
        ...

הוספת הרשאה חדשה:
    אין צורך לשנות קובץ זה.
    פשוט קרא ל-grant_permission(user_id, "שם.ההרשאה") ובדוק עם has_permission().
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import sqlite3

from database.database import get_connection

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# בדיקת הרשאה — הפונקציה המרכזית
# ─────────────────────────────────────────────────────────────────────────────

def has_permission(telegram_id: int, permission: str) -> bool:
    """
    בודקת האם למשתמש יש הרשאה מסוימת.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.
        permission:  שם ההרשאה (למשל "verify.review", "admin").

    Returns:
        True אם ההרשאה קיימת, False אחרת.

    דוגמה:
        if has_permission(user_id, "publish.edit"):
            # מאפשר עריכה
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT 1
                FROM user_permissions
                WHERE telegram_id = ? AND permission = ?
                LIMIT 1
                """,
                (telegram_id, permission),
            )
            return cursor.fetchone() is not None
    except sqlite3.Error as exc:
        logger.error(
            "has_permission(%s, %s) failed: %s", telegram_id, permission, exc
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# הקצאת הרשאה
# ─────────────────────────────────────────────────────────────────────────────

def grant_permission(
    telegram_id: int,
    permission: str,
    granted_by: int | None = None,
) -> bool:
    """
    מקצה הרשאה למשתמש.
    אם ההרשאה כבר קיימת — לא קורה כלום (ללא שגיאה).

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.
        permission:  שם ההרשאה.
        granted_by:  telegram_id של מי שנתן את ההרשאה (אופציונלי).

    Returns:
        True אם הצליח, False אם נכשל.

    דוגמה:
        grant_permission(user_id, "verify.review", granted_by=admin_id)
    """
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_permissions
                    (telegram_id, permission, granted_by)
                VALUES (?, ?, ?)
                """,
                (telegram_id, permission, granted_by),
            )
            conn.commit()
        logger.info(
            "grant_permission: %s → %s (by %s)", telegram_id, permission, granted_by
        )
        return True
    except sqlite3.Error as exc:
        logger.error(
            "grant_permission(%s, %s) failed: %s", telegram_id, permission, exc
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# שלילת הרשאה
# ─────────────────────────────────────────────────────────────────────────────

def revoke_permission(telegram_id: int, permission: str) -> bool:
    """
    שוללת הרשאה ממשתמש.
    אם ההרשאה לא קיימת — לא קורה כלום.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.
        permission:  שם ההרשאה.

    Returns:
        True אם הצליח, False אם נכשל.

    דוגמה:
        revoke_permission(user_id, "publish.edit")
    """
    try:
        with get_connection() as conn:
            conn.execute(
                """
                DELETE FROM user_permissions
                WHERE telegram_id = ? AND permission = ?
                """,
                (telegram_id, permission),
            )
            conn.commit()
        logger.info("revoke_permission: %s ← %s", telegram_id, permission)
        return True
    except sqlite3.Error as exc:
        logger.error(
            "revoke_permission(%s, %s) failed: %s", telegram_id, permission, exc
        )
        return False


def revoke_all_permissions(telegram_id: int) -> int:
    """
    שוללת את כל ההרשאות של משתמש.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.

    Returns:
        מספר ההרשאות שנמחקו, או -1 אם נכשל.

    דוגמה:
        count = revoke_all_permissions(user_id)
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM user_permissions WHERE telegram_id = ?",
                (telegram_id,),
            )
            conn.commit()
            count = cursor.rowcount
        logger.info("revoke_all_permissions: %s → %d removed", telegram_id, count)
        return count
    except sqlite3.Error as exc:
        logger.error(
            "revoke_all_permissions(%s) failed: %s", telegram_id, exc
        )
        return -1


# ─────────────────────────────────────────────────────────────────────────────
# שאילתות
# ─────────────────────────────────────────────────────────────────────────────

def get_user_permissions(telegram_id: int) -> list[str]:
    """
    מחזירה את רשימת כל ההרשאות של משתמש.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.

    Returns:
        רשימת מחרוזות הרשאה, או [] אם אין / נכשל.

    דוגמה:
        perms = get_user_permissions(user_id)
        # ["admin", "verify.review"]
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT permission
                FROM user_permissions
                WHERE telegram_id = ?
                ORDER BY granted_at ASC
                """,
                (telegram_id,),
            )
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        logger.error(
            "get_user_permissions(%s) failed: %s", telegram_id, exc
        )
        return []


def get_all_with_permission(permission: str) -> list[int]:
    """
    מחזירה את כל מזהי הטלגרם שיש להם הרשאה מסוימת.

    Parameters:
        permission: שם ההרשאה.

    Returns:
        רשימת telegram_id, או [] אם אין / נכשל.

    דוגמה:
        reviewers = get_all_with_permission("verify.review")
        # [123456789, 987654321]
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT telegram_id
                FROM user_permissions
                WHERE permission = ?
                ORDER BY granted_at ASC
                """,
                (permission,),
            )
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        logger.error(
            "get_all_with_permission(%s) failed: %s", permission, exc
        )
        return []
