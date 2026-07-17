"""
services/merchant_service.py
─────────────────────────────────────────────────────────────────────────────
שירות פאנל הסוחר — VerifyManager Merchant Service

מצב נוכחי:
    תשתית בלבד. לא מחובר לבוט עדיין.
    חיבור יתבצע בשלב נפרד לאחר בדיקות.

עקרון מרכזי:
    השירות הזה אינו מכיר רשימת הרשאות קבועה.
    הוא לא יודע אילו כפתורים יהיו בפאנל ומה הם יעשו.
    כל ההרשאות הן מחרוזות חופשיות שנשמרות בטבלה.

    ה-handler הוא שמחליט:
        - אילו הרשאות מייצגות אילו כפתורים.
        - מה מוצג כשהרשאה קיימת / לא קיימת.

    כך ניתן להוסיף עשרות הרשאות ("merchant.X") בלי לשנות קובץ זה.

ארכיטקטורה:
    is_merchant()             → האם המשתמש בכלל בסוחר?
    get_merchant_permissions()→ אילו הרשאות סוחר יש לו? (רשימה דינמית)
    has_merchant_permission() → האם הרשאה ספציפית קיימת?

שימוש (לאחר חיבור לבוט):
    from services.merchant_service import (
        is_merchant,
        get_merchant_permissions,
        has_merchant_permission,
    )

    if is_merchant(user_id):
        perms = get_merchant_permissions(user_id)
        # perms = ["merchant.publish.bot", "merchant.listings.view", ...]
        # ה-handler בונה את המקלדת לפי perms — אין לוגיקה כאן
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

from services.permission_service import has_permission, get_user_permissions

logger = logging.getLogger(__name__)

# קידומת הרשאות הסוחר — כל הרשאה שמתחילה בה שייכת לפאנל הסוחר
MERCHANT_PREFIX = "merchant."


# ─────────────────────────────────────────────────────────────────────────────
# בדיקת גישה לפאנל
# ─────────────────────────────────────────────────────────────────────────────

def is_merchant(telegram_id: int) -> bool:
    """
    בודק האם למשתמש יש גישה לפאנל הסוחר.
    דורש את ההרשאה הבסיסית "merchant" בלבד.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.

    Returns:
        True אם יש גישה לפאנל, False אחרת.
    """
    return has_permission(telegram_id, "merchant")


# ─────────────────────────────────────────────────────────────────────────────
# שאילתת הרשאות דינמית
# ─────────────────────────────────────────────────────────────────────────────

def get_merchant_permissions(telegram_id: int) -> list[str]:
    """
    מחזיר את כל הרשאות הסוחר שיש למשתמש — בלי להניח מה הן.

    לוגיקה:
        מסנן מכל ההרשאות של המשתמש את אלה שמתחילות ב-"merchant."
        (לא כולל "merchant" עצמה — זו הרשאת הבסיס בלבד).

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.

    Returns:
        רשימת מחרוזות הרשאה, למשל:
            ["merchant.publish.bot", "merchant.listings.view", "merchant.stats"]
        ריקה אם אין הרשאות ספציפיות (רק הרשאת "merchant" הבסיסית).

    דוגמה:
        perms = get_merchant_permissions(user_id)
        for perm in perms:
            # ה-handler מחליט מה לעשות עם כל הרשאה
    """
    all_perms = get_user_permissions(telegram_id)
    return [p for p in all_perms if p.startswith(MERCHANT_PREFIX)]


def has_merchant_permission(telegram_id: int, permission: str) -> bool:
    """
    בודק האם למשתמש יש הרשאת סוחר ספציפית.
    עטיפה נוחה על has_permission() עבור שימוש בהנדלרים.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.
        permission:  שם ההרשאה המלא (כולל הקידומת, למשל "merchant.publish.bot").

    Returns:
        True אם ההרשאה קיימת, False אחרת.

    דוגמה:
        if has_merchant_permission(user_id, "merchant.publish.bot"):
            # הצג כפתור פרסום בבוט
    """
    return has_permission(telegram_id, permission)
