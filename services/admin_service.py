"""
services/admin_service.py
─────────────────────────────────────────────────────────────────────────────
שכבת ניהול Super Admin + Admin — VerifyManager

ארכיטקטורה:
    Super Admin ← מוגדר ב-config/constants.py (ADMIN_ID), לא בטבלת ההרשאות.
    Admin       ← כל משתמש עם הרשאת "admin" בטבלת user_permissions.
    הרשאות ספציפיות ← כל מחרוזת נוספת שהסופר-אדמין מקצה.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

from config.constants import ADMIN_ID
from database.database import get_connection
from services.permission_service import (
    has_permission,
    grant_permission,
    revoke_permission,
    revoke_all_permissions,
    get_user_permissions,
    get_all_with_permission,
)

logger = logging.getLogger(__name__)


def is_super_admin(telegram_id: int) -> bool:
    return telegram_id == ADMIN_ID


def is_admin(telegram_id: int) -> bool:
    if is_super_admin(telegram_id):
        return True
    return has_permission(telegram_id, "admin")


def get_all_admins() -> list[int]:
    return get_all_with_permission("admin")


def get_admin_profile(telegram_id: int) -> dict:
    """מחזיר פרופיל תצוגה של מנהל לפי telegram_id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT full_name, username FROM users WHERE telegram_id = ? LIMIT 1",
            (telegram_id,),
        ).fetchone()
        admin_row = conn.execute(
            """
            SELECT granted_at
            FROM user_permissions
            WHERE telegram_id = ? AND permission = 'admin'
            ORDER BY granted_at DESC
            LIMIT 1
            """,
            (telegram_id,),
        ).fetchone()

    full_name = row["full_name"] if row else None
    username = row["username"] if row else None
    granted_at = admin_row["granted_at"] if admin_row else None

    if full_name:
        display_name = full_name
    elif username:
        display_name = f"@{username}"
    else:
        display_name = str(telegram_id)

    return {
        "telegram_id": telegram_id,
        "full_name": full_name,
        "username": username,
        "display_name": display_name,
        "granted_at": granted_at,
    }


def get_all_admin_profiles() -> list[dict]:
    """מחזיר רשימת פרופילי תצוגה לכל המנהלים הפעילים."""
    return [get_admin_profile(admin_id) for admin_id in get_all_admins()]


def promote_to_admin(telegram_id: int, granted_by: int | None = None) -> bool:
    logger.info("promote_to_admin: %s (by %s)", telegram_id, granted_by)
    return grant_permission(telegram_id, "admin", granted_by=granted_by)


def demote_admin(telegram_id: int) -> bool:
    logger.info("demote_admin: %s — revoking all permissions", telegram_id)
    result = revoke_all_permissions(telegram_id)
    return result >= 0


def grant_admin_permission(
    telegram_id: int,
    permission: str,
    granted_by: int | None = None,
) -> bool:
    logger.info("grant_admin_permission: %s → %s (by %s)", telegram_id, permission, granted_by)
    return grant_permission(telegram_id, permission, granted_by=granted_by)


def revoke_admin_permission(telegram_id: int, permission: str) -> bool:
    logger.info("revoke_admin_permission: %s ← %s", telegram_id, permission)
    return revoke_permission(telegram_id, permission)


def get_admin_permissions(telegram_id: int) -> list[str]:
    return get_user_permissions(telegram_id)


def grant_user_permission(
    telegram_id: int,
    permission: str,
    granted_by: int | None = None,
) -> bool:
    logger.info("grant_user_permission: %s → %s (by %s)", telegram_id, permission, granted_by)
    return grant_permission(telegram_id, permission, granted_by=granted_by)


def revoke_user_permission(telegram_id: int, permission: str) -> bool:
    logger.info("revoke_user_permission: %s ← %s", telegram_id, permission)
    return revoke_permission(telegram_id, permission)


def get_user_all_permissions(telegram_id: int) -> list[str]:
    return get_user_permissions(telegram_id)