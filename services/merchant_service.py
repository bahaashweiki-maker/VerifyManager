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

from database.database import get_connection
from repositories.merchant_channels_repository import list_channels_by_keys
from repositories.merchant_publication_repository import (
    list_merchant_allowed_channels,
    list_merchant_multi_allowed_channels,
    list_merchant_required_channels,
)
from services.permission_service import has_permission, get_user_permissions
from services.verified_users_service import get_user_general_permissions

logger = logging.getLogger(__name__)

# קידומת הרשאות הסוחר — כל הרשאה שמתחילה בה שייכת לפאנל הסוחר
MERCHANT_PREFIX = "merchant."

MERCHANT_CAPABILITY_LABELS: dict[str, str] = {
    "user.merchant.start": "▶️ אזור סוחר: התחל פרסום",
    "user.merchant.schedule": "⏱️ אזור סוחר: תזמון פרסום",
    "user.merchant.required": "🔐 אזור סוחר: חובת הצטרפות",
    "user.merchant.channels": "📡 אזור סוחר: הערוצים שלי",
    "user.merchant.publications": "🗂️ אזור סוחר: הפרסומים שלי",
    "user.merchant.status": "🛡️ אזור סוחר: סטטוס הרשאות",
    "user.publish.multi": "🧩 פרסום נוסף במקביל",
    "user.media.image": "🖼 העלאת תמונה",
    "user.media.video": "🎥 העלאת וידאו",
    "user.media.animation": "🌀 העלאת אנימציה",
    "user.media.document": "📄 העלאת מסמך",
    "user.media.audio": "🎵 העלאת אודיו",
    "user.review.write": "⭐ הגשת חוות דעת",
    "user.review.reply": "💬 מענה לחוות דעת",
    "user.store.view": "🛍 צפייה בחנות",
    "user.store.sell": "🛒 מכירה בחנות",
    "user.store.manage": "⚙️ ניהול חנות",
}


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
    # Compatibility: some flows mark merchant via user_type_assignments
    # without granting explicit "merchant" permission.
    if has_permission(telegram_id, "merchant"):
        return True
    try:
        from services.verified_users_service import get_user_type

        return get_user_type(telegram_id) == "merchant"
    except Exception:
        return False


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


def list_merchant_profiles() -> list[dict]:
    """Return merchant users based on verified user type assignments."""
    try:
        with get_connection() as conn:
            conn.row_factory = _row_factory
            rows = conn.execute(
                """
                SELECT
                    uta.telegram_id,
                    COALESCE(u.full_name, v.full_name) AS full_name,
                    COALESCE(u.username, v.username) AS username,
                    uta.assigned_at
                FROM user_type_assignments uta
                LEFT JOIN users u ON u.telegram_id = uta.telegram_id
                LEFT JOIN (
                    SELECT vv.telegram_id, vv.full_name, vv.username
                    FROM verifications vv
                    INNER JOIN (
                        SELECT telegram_id, MAX(id) AS max_id
                        FROM verifications
                        GROUP BY telegram_id
                    ) latest
                        ON latest.telegram_id = vv.telegram_id
                       AND latest.max_id = vv.id
                ) v ON v.telegram_id = uta.telegram_id
                WHERE uta.type_key = 'merchant'
                ORDER BY COALESCE(u.full_name, v.full_name, u.username, v.username, CAST(uta.telegram_id AS TEXT)) COLLATE NOCASE ASC
                """
            ).fetchall()
        return rows
    except Exception as exc:
        logger.error("list_merchant_profiles failed: %s", exc)
        return []


def get_merchant_profile(telegram_id: int) -> dict | None:
    profiles = list_merchant_profiles()
    return next((row for row in profiles if int(row.get("telegram_id") or 0) == int(telegram_id)), None)


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    data = dict(zip(fields, row))
    full_name = data.get("full_name")
    username = data.get("username")
    telegram_id = data.get("telegram_id")
    if full_name:
        display_name = full_name
    elif username:
        display_name = f"@{username}"
    else:
        display_name = str(telegram_id)
    data["display_name"] = display_name
    return data


def get_merchant_capability_flags(telegram_id: int) -> dict[str, bool]:
    """Return boolean flags for the connected merchant user.* permissions."""
    perms = set(get_user_general_permissions(telegram_id))
    return {key: (key in perms) for key in MERCHANT_CAPABILITY_LABELS}


def can_merchant_start_publication(telegram_id: int) -> bool:
    flags = get_merchant_capability_flags(telegram_id)
    return bool(flags.get("user.merchant.start"))


def list_merchant_allowed_channel_records(telegram_id: int) -> list[dict]:
    return list_channels_by_keys(list_merchant_allowed_channels(telegram_id))


def list_merchant_required_channel_records(telegram_id: int) -> list[dict]:
    return list_channels_by_keys(list_merchant_required_channels(telegram_id))


def list_merchant_multi_allowed_channel_records(telegram_id: int) -> list[dict]:
    return list_channels_by_keys(list_merchant_multi_allowed_channels(telegram_id))
