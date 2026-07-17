"""
services/admin_service.py
─────────────────────────────────────────────────────────────────────────────
שכבת ניהול Super Admin + Admin — VerifyManager

ארכיטקטורה:
    Super Admin ← מוגדר ב-config (ADMIN_ID), לא בטבלת ההרשאות.
    Admin       ← כל משתמש עם הרשאת "admin" בטבלת user_permissions.
    הרשאות ספציפיות ← כל מחרוזת נוספת שהסופר-אדמין מקצה.

עקרון אחריות:
    שכבה זו מספקת כלים בלבד.
    הבדיקה "מי מורשה לקרוא לפונקציה זו" היא באחריות ה-handler,
    לא של השירות עצמו.

שימוש:
    from services.admin_service import is_super_admin, is_admin, promote_to_admin

    if is_super_admin(user_id):
        promote_to_admin(target_id, granted_by=user_id)

    if is_admin(user_id) and has_permission(user_id, "verify.review"):
        # מותר לסקור אימותים
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

from admin.admin import ADMIN_ID
from services.permission_service import (
    has_permission,
    grant_permission,
    revoke_permission,
    revoke_all_permissions,
    get_user_permissions,
    get_all_with_permission,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Super Admin — מזוהה לפי ADMIN_ID בלבד, ללא רישום בטבלה
# ─────────────────────────────────────────────────────────────────────────────

def is_super_admin(telegram_id: int) -> bool:
    """
    בודק האם המשתמש הוא הסופר-אדמין (בעל המערכת).
    הסופר-אדמין מוגדר לפי ADMIN_ID בקונפיגורציה בלבד.

    Parameters:
        telegram_id: מזהה הטלגרם לבדיקה.

    Returns:
        True אם הוא הסופר-אדמין, False אחרת.
    """
    return telegram_id == ADMIN_ID


# ─────────────────────────────────────────────────────────────────────────────
# Admin — כל מי שיש לו הרשאת "admin" בטבלה
# ─────────────────────────────────────────────────────────────────────────────

def is_admin(telegram_id: int) -> bool:
    """
    בודק האם המשתמש הוא מנהל (קיבל הרשאת "admin" מהסופר-אדמין).
    הסופר-אדמין נחשב גם כמנהל.

    Parameters:
        telegram_id: מזהה הטלגרם לבדיקה.

    Returns:
        True אם מנהל, False אחרת.
    """
    if is_super_admin(telegram_id):
        return True
    return has_permission(telegram_id, "admin")


def get_all_admins() -> list[int]:
    """
    מחזיר את רשימת ה-telegram_id של כל המנהלים הפעילים
    (לא כולל סופר-אדמין — הוא לא נרשם בטבלה).

    Returns:
        רשימת telegram_id.
    """
    return get_all_with_permission("admin")


# ─────────────────────────────────────────────────────────────────────────────
# ניהול מנהלים — רק הסופר-אדמין מורשה לקרוא לפונקציות אלו
# ─────────────────────────────────────────────────────────────────────────────

def promote_to_admin(telegram_id: int, granted_by: int | None = None) -> bool:
    """
    מקצה הרשאת "admin" למשתמש (הופך אותו למנהל).
    אין מגבלה על מספר המנהלים.

    Parameters:
        telegram_id: המשתמש שיהפוך למנהל.
        granted_by:  telegram_id של מי שנתן את ההרשאה (אופציונלי).

    Returns:
        True אם הצליח.

    הערה:
        ה-handler חייב לוודא is_super_admin(caller_id) לפני הקריאה.
    """
    logger.info("promote_to_admin: %s (by %s)", telegram_id, granted_by)
    return grant_permission(telegram_id, "admin", granted_by=granted_by)


def demote_admin(telegram_id: int) -> bool:
    """
    מוריד מנהל מתפקידו ומסיר את כל הרשאותיו.
    פעולה בלתי הפיכה — המנהל איבד גם את ההרשאות הספציפיות שקיבל.

    Parameters:
        telegram_id: המנהל שיורד מתפקידו.

    Returns:
        True אם הצליח.

    הערה:
        ה-handler חייב לוודא is_super_admin(caller_id) לפני הקריאה.
        אין להוריד את הסופר-אדמין — is_super_admin() צריך להיבדק לפני הקריאה.
    """
    logger.info("demote_admin: %s — revoking all permissions", telegram_id)
    result = revoke_all_permissions(telegram_id)
    return result >= 0


# ─────────────────────────────────────────────────────────────────────────────
# הרשאות ספציפיות — מה מנהל מורשה לעשות
# ─────────────────────────────────────────────────────────────────────────────

def grant_admin_permission(
    telegram_id: int,
    permission: str,
    granted_by: int | None = None,
) -> bool:
    """
    מקצה הרשאה ספציפית למנהל (למשל "verify.review", "publish.edit").
    ההרשאה היא מחרוזת חופשית לחלוטין — אין רשימה קבועה.

    Parameters:
        telegram_id: המנהל שמקבל את ההרשאה.
        permission:  שם ההרשאה (מחרוזת חופשית).
        granted_by:  telegram_id של מי שנתן את ההרשאה.

    Returns:
        True אם הצליח.

    הערה:
        ה-handler חייב לוודא is_super_admin(caller_id) לפני הקריאה.
    """
    logger.info(
        "grant_admin_permission: %s → %s (by %s)", telegram_id, permission, granted_by
    )
    return grant_permission(telegram_id, permission, granted_by=granted_by)


def revoke_admin_permission(telegram_id: int, permission: str) -> bool:
    """
    שולל הרשאה ספציפית ממנהל.

    Parameters:
        telegram_id: המנהל שממנו נשללת ההרשאה.
        permission:  שם ההרשאה.

    Returns:
        True אם הצליח.

    הערה:
        ה-handler חייב לוודא is_super_admin(caller_id) לפני הקריאה.
    """
    logger.info("revoke_admin_permission: %s ← %s", telegram_id, permission)
    return revoke_permission(telegram_id, permission)


def get_admin_permissions(telegram_id: int) -> list[str]:
    """
    מחזיר את כל ההרשאות של מנהל ספציפי.

    Parameters:
        telegram_id: מזהה המנהל.

    Returns:
        רשימת מחרוזות הרשאה, למשל ["admin", "verify.review", "publish.edit"].
    """
    return get_user_permissions(telegram_id)


# ─────────────────────────────────────────────────────────────────────────────
# ניהול משתמשים — הרשאות לכל סוג משתמש
# ─────────────────────────────────────────────────────────────────────────────

def grant_user_permission(
    telegram_id: int,
    permission: str,
    granted_by: int | None = None,
) -> bool:
    """
    מקצה הרשאה למשתמש רגיל (VIP, Merchant, Verified, וכו').
    ההרשאה היא מחרוזת חופשית — הסופר-אדמין בוחר את השם.

    Parameters:
        telegram_id: המשתמש שמקבל את ההרשאה.
        permission:  שם ההרשאה (מחרוזת חופשית).
        granted_by:  telegram_id של מי שנתן את ההרשאה.

    Returns:
        True אם הצליח.

    דוגמאות:
        grant_user_permission(user_id, "vip")
        grant_user_permission(user_id, "merchant")
        grant_user_permission(user_id, "verified")
        grant_user_permission(user_id, "catalog.electronics")
        grant_user_permission(user_id, "channel.main")
    """
    logger.info(
        "grant_user_permission: %s → %s (by %s)", telegram_id, permission, granted_by
    )
    return grant_permission(telegram_id, permission, granted_by=granted_by)


def revoke_user_permission(telegram_id: int, permission: str) -> bool:
    """
    שולל הרשאה ממשתמש רגיל.

    Parameters:
        telegram_id: המשתמש שממנו נשללת ההרשאה.
        permission:  שם ההרשאה.

    Returns:
        True אם הצליח.
    """
    logger.info("revoke_user_permission: %s ← %s", telegram_id, permission)
    return revoke_permission(telegram_id, permission)


def get_user_all_permissions(telegram_id: int) -> list[str]:
    """
    מחזיר את כל ההרשאות של משתמש.

    Parameters:
        telegram_id: מזהה המשתמש.

    Returns:
        רשימת מחרוזות הרשאה.
    """
    return get_user_permissions(telegram_id)
