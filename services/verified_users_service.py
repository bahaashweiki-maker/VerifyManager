"""
services/verified_users_service.py
─────────────────────────────────────────────────────────────────────────────
כל הלוגיקה למודול ניהול מאומתים.

הרשאות כלליות מנותבות דרך permission_service הקיים.
הרשאות קטלוג = 'catalog.{slug}' בטבלת user_permissions.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from database.database import get_connection
from services.permission_service import (
    get_user_permissions,
    grant_permission,
    revoke_permission,
)

logger = logging.getLogger(__name__)

# ── סוגי משתמש ───────────────────────────────────────────────────────────────
USER_TYPES: dict = {
    "verified": {"emoji": "👤", "label": "מאומת רגיל"},
    "merchant": {"emoji": "🏪", "label": "סוחר"},
    "vip":      {"emoji": "⭐", "label": "VIP"},
    "vip_plus": {"emoji": "💎", "label": "VIP+"},
    "business": {"emoji": "🏢", "label": "בית עסק"},
    "partner":  {"emoji": "🤝", "label": "שותף"},
}

# ── קהלי יעד לקטלוג ──────────────────────────────────────────────────────────
CATALOG_AUDIENCES: dict = {
    "all":      "כולם",
    "verified": "מאומתים",
    "merchant": "סוחרים",
    "vip":      "VIP",
    "business": "בית עסק",
    "custom":   "מותאם אישית",
}

# ── תוויות השעיה ──────────────────────────────────────────────────────────────
SUSPEND_LABELS: dict = {
    "1d":   "יום אחד",
    "7d":   "שבוע",
    "30d":  "חודש",
    "perm": "קבוע",
}

_SUSPEND_DAYS: dict = {
    "1d":   1,
    "7d":   7,
    "30d":  30,
    "perm": None,
}


# ─────────────────────────────────────────────────────────────────────────────
# שליפת מאומתים
# ─────────────────────────────────────────────────────────────────────────────

def get_all_verified_users() -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute("""
            SELECT
                v.id,
                v.telegram_id,
                v.full_name,
                v.username,
                v.status,
                v.created_at,
                COALESCE(uta.type_key, 'none') AS type_key
            FROM verifications v
            LEFT JOIN user_type_assignments uta
                ON uta.telegram_id = v.telegram_id
            WHERE v.id IN (
                SELECT MAX(id)
                FROM verifications
                WHERE status IN ('approved', 'blocked', 'rejected')
                GROUP BY telegram_id
            )
            ORDER BY v.created_at DESC
        """)
        return cur.fetchall()


def get_verified_users_count() -> int:
    with get_connection() as conn:
        cur = conn.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT MAX(id) as id
                FROM verifications
                WHERE status IN ('approved','blocked','rejected')
                GROUP BY telegram_id
            )
        """)
        return cur.fetchone()[0]


def get_verified_user_by_id(verification_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM verifications WHERE id = ?",
            (verification_id,),
        )
        return cur.fetchone()


# ─────────────────────────────────────────────────────────────────────────────
# סוג משתמש
# ─────────────────────────────────────────────────────────────────────────────

def get_user_type(telegram_id: int) -> str:
    """
    מחזיר את מפתח סוג המשתמש.

    ברירת מחדל: 'none' — משתמש שלא הוקצה לו סוג מפורש בטבלת
    user_type_assignments לא יקבל גישה אוטומטית לקטלוגים עם
    audience='verified' או כל audience ספציפי אחר.
    רק קטלוגים עם audience='all' יהיו גלויים לו.
    """
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT type_key FROM user_type_assignments WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = cur.fetchone()
            result = row[0] if row else "none"
            return result
    except Exception as exc:
        logger.error("get_user_type(%s) failed: %s", telegram_id, exc)
        return "none"


def set_user_type(
    telegram_id: int,
    type_key: str,
    assigned_by: int = None,
) -> bool:
    """שומר / מעדכן את סוג המשתמש."""
    if type_key not in USER_TYPES:
        logger.warning("set_user_type: unknown type_key '%s'", type_key)
        return False
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO user_type_assignments (telegram_id, type_key, assigned_by)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE
                    SET type_key    = excluded.type_key,
                        assigned_by = excluded.assigned_by,
                        assigned_at = datetime('now')
                """,
                (telegram_id, type_key, assigned_by),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("set_user_type(%s, %s) failed: %s", telegram_id, type_key, exc)
        return False


def get_user_type_display(telegram_id: int) -> str:
    """
    מחזיר מחרוזת תצוגה כגון '⭐ VIP'.

    אם type_key הוא 'none' (לא הוגדר) — מחזיר '⬜ לא מוגדר'.
    לא נופל על 'verified' כברירת מחדל, כדי שהמנהל לא יתבלבל.
    """
    key  = get_user_type(telegram_id)
    info = USER_TYPES.get(key)
    if info is None:
        return "⬜ לא מוגדר"
    return f"{info['emoji']} {info['label']}"


# ─────────────────────────────────────────────────────────────────────────────
# ביטול אימות
# ─────────────────────────────────────────────────────────────────────────────

def revoke_verification(verification_id: int, performed_by: int = None) -> bool:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT telegram_id FROM verifications WHERE id = ?",
                (verification_id,),
            ).fetchone()

            telegram_id = row[0] if row else None
            conn.execute(
                "UPDATE verifications SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (verification_id,),
            )

            # הסרת גישות שניתנו למשתמש מאומת:
            # - סוג משתמש (מבטל קטלוגים אוטומטיים לפי audience)
            # - הרשאות user.* ו-catalog.* (כולל הקצאות ידניות לקטלוגים)
            if telegram_id is not None:
                conn.execute(
                    "DELETE FROM user_type_assignments WHERE telegram_id = ?",
                    (telegram_id,),
                )
                conn.execute(
                    """
                    DELETE FROM user_permissions
                    WHERE telegram_id = ?
                      AND (permission LIKE 'user.%' OR permission LIKE 'catalog.%')
                    """,
                    (telegram_id,),
                )

            conn.commit()
        if row:
            _log_action(row[0], "revoke", performed_by=performed_by)
        return True
    except Exception as exc:
        logger.error("revoke_verification failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# חסימה / שחרור
# ─────────────────────────────────────────────────────────────────────────────

def block_verified_user(verification_id: int, performed_by: int = None) -> bool:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT telegram_id FROM verifications WHERE id = ?",
                (verification_id,),
            ).fetchone()
            conn.execute(
                "UPDATE verifications SET status = 'blocked' WHERE id = ?",
                (verification_id,),
            )
            conn.commit()
        if row:
            _log_action(row[0], "block", performed_by=performed_by)
        return True
    except Exception as exc:
        logger.error("block_verified_user failed: %s", exc)
        return False


def unblock_verified_user(verification_id: int, performed_by: int = None) -> bool:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT telegram_id FROM verifications WHERE id = ?",
                (verification_id,),
            ).fetchone()
            conn.execute(
                "UPDATE verifications SET status = 'approved' WHERE id = ?",
                (verification_id,),
            )
            conn.commit()
        if row:
            _log_action(row[0], "unblock", performed_by=performed_by)
        return True
    except Exception as exc:
        logger.error("unblock_verified_user failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# אזהרות
# ─────────────────────────────────────────────────────────────────────────────

def add_warning(telegram_id: int, reason: str, created_by: int = None) -> bool:
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO user_warnings (telegram_id, reason, created_by)
                   VALUES (?, ?, ?)""",
                (telegram_id, reason, created_by),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("add_warning failed: %s", exc)
        return False


def get_warnings(telegram_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM user_warnings WHERE telegram_id = ? ORDER BY created_at DESC",
            (telegram_id,),
        )
        return cur.fetchall()


def get_warning_by_id(warning_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM user_warnings WHERE id = ?", (warning_id,)
        )
        return cur.fetchone()


def get_warnings_count(telegram_id: int) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM user_warnings WHERE telegram_id = ?",
            (telegram_id,),
        )
        return cur.fetchone()[0]


def delete_warning(warning_id: int) -> bool:
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM user_warnings WHERE id = ?", (warning_id,))
            conn.commit()
        return True
    except Exception as exc:
        logger.error("delete_warning failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# השעיות
# ─────────────────────────────────────────────────────────────────────────────

def suspend_user(
    telegram_id: int,
    duration_key: str,
    reason: str = None,
    created_by: int = None,
) -> bool:
    days  = _SUSPEND_DAYS.get(duration_key)
    until = (
        (datetime.utcnow() + timedelta(days=days)).isoformat()
        if days is not None
        else None
    )
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE user_suspensions SET is_active = 0 WHERE telegram_id = ? AND is_active = 1",
                (telegram_id,),
            )
            conn.execute(
                """INSERT INTO user_suspensions
                       (telegram_id, duration_key, suspended_until, reason, created_by)
                   VALUES (?, ?, ?, ?, ?)""",
                (telegram_id, duration_key, until, reason, created_by),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("suspend_user failed: %s", exc)
        return False


def lift_suspension(telegram_id: int) -> bool:
    try:
        with get_connection() as conn:
            conn.execute(
                """UPDATE user_suspensions
                   SET is_active = 0, lifted_at = datetime('now')
                   WHERE telegram_id = ? AND is_active = 1""",
                (telegram_id,),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("lift_suspension failed: %s", exc)
        return False


def get_active_suspension(telegram_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """SELECT * FROM user_suspensions
               WHERE telegram_id = ? AND is_active = 1
               ORDER BY created_at DESC LIMIT 1""",
            (telegram_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["suspended_until"]:
            try:
                until = datetime.fromisoformat(row["suspended_until"])
                if datetime.utcnow() > until:
                    lift_suspension(telegram_id)
                    return None
            except Exception:
                pass
        return row


def is_suspended(telegram_id: int) -> bool:
    return get_active_suspension(telegram_id) is not None


# ─────────────────────────────────────────────────────────────────────────────
# הרשאות משתמש — user.* בלבד (נפרד לחלוטין מהרשאות מנהל)
# ─────────────────────────────────────────────────────────────────────────────

def get_user_general_permissions(telegram_id: int) -> list:
    """
    מחזיר הרשאות משתמש בלבד — כל הרשאה שמפתחה מתחיל ב-'user.'.
    הרשאות מנהל (admin, verify.review וכו') לעולם לא יוחזרו כאן.
    """
    return [
        p for p in get_user_permissions(telegram_id)
        if p.startswith("user.")
    ]


def grant_general_permission(
    telegram_id: int, key: str, granted_by: int = None
) -> None:
    grant_permission(telegram_id, key, granted_by=granted_by)


def revoke_general_permission(telegram_id: int, key: str) -> None:
    revoke_permission(telegram_id, key)


# ─────────────────────────────────────────────────────────────────────────────
# קטלוגים — שליפה
# ─────────────────────────────────────────────────────────────────────────────

def get_all_catalogs() -> list:
    """שליפת כל הקטלוגים הפעילים (כולל כל השדות המורחבים)."""
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM catalogs WHERE is_active = 1 ORDER BY name"
        )
        return cur.fetchall()


def get_catalog_by_id(catalog_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM catalogs WHERE id = ?", (catalog_id,)
        )
        return cur.fetchone()


def get_custom_catalogs() -> list:
    """קטלוגים שהקצאתם ידנית (audience = 'custom')."""
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM catalogs WHERE is_active = 1 AND audience = 'custom' ORDER BY name"
        )
        return cur.fetchall()


def get_auto_catalogs_for_user(telegram_id: int) -> list:
    """
    מחזיר קטלוגים שהמשתמש מקבל אוטומטית לפי סוג המשתמש שלו.
    לא כוללת קטלוגים עם audience='custom'.
    """
    type_key = get_user_type(telegram_id)
    catalogs = get_all_catalogs()
    return [
        cat for cat in catalogs
        if cat.get("audience", "custom") != "custom"
        and _audience_matches(cat.get("audience", "custom"), type_key)
    ]


def _audience_matches(audience: str, type_key: str) -> bool:
    """
    בודק אם קהל יעד של קטלוג מתאים לסוג משתמש.

    טבלת התאמות:
      audience='all'      → כולם (כולל type_key='none')
      audience='verified' → רק מי שהוקצה לו type_key='verified' מפורשות
      audience='vip'      → type_key='vip' או 'vip_plus'
      audience='vip_plus' → type_key='vip_plus' בלבד
      audience='merchant' → type_key='merchant' בלבד
      audience='business' → type_key='business' בלבד
      audience='partner'  → type_key='partner' בלבד
      audience='custom'   → לא מטופל כאן (נסנן ב-get_auto_catalogs_for_user)
    """
    if audience == "all":
        return True
    if audience == "vip" and type_key == "vip_plus":
        return True  # VIP+ מקבל גם קטלוגי VIP
    return audience == type_key


# ─────────────────────────────────────────────────────────────────────────────
# קטלוגים — CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_catalog(
    name: str,
    slug: str = None,
    audience: str = "custom",
    is_publishable: bool = False,
    is_readonly: bool = False,
) -> Optional[int]:
    """
    יוצר קטלוג חדש. מחזיר את ה-id שנוצר, או None אם נכשל.
    אם slug לא סופק — נגזר אוטומטית מה-name.
    """
    if not slug:
        slug = _slugify(name)
    if audience not in CATALOG_AUDIENCES:
        audience = "custom"
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO catalogs (slug, name, audience, is_publishable, is_readonly)
                   VALUES (?, ?, ?, ?, ?)""",
                (slug, name, audience, int(is_publishable), int(is_readonly)),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as exc:
        logger.error("create_catalog failed: %s", exc)
        return None


def update_catalog(
    catalog_id: int,
    name: str = None,
    audience: str = None,
    is_publishable: bool = None,
    is_readonly: bool = None,
    is_active: bool = None,
) -> bool:
    """מעדכן שדות של קטלוג קיים. מעדכן רק שדות שסופקו (לא None)."""
    fields, values = [], []

    if name is not None:
        fields.append("name = ?"); values.append(name)
    if audience is not None and audience in CATALOG_AUDIENCES:
        fields.append("audience = ?"); values.append(audience)
    if is_publishable is not None:
        fields.append("is_publishable = ?"); values.append(int(is_publishable))
    if is_readonly is not None:
        fields.append("is_readonly = ?"); values.append(int(is_readonly))
    if is_active is not None:
        fields.append("is_active = ?"); values.append(int(is_active))

    if not fields:
        return True  # אין מה לעדכן

    values.append(catalog_id)
    try:
        with get_connection() as conn:
            conn.execute(
                f"UPDATE catalogs SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("update_catalog(%s) failed: %s", catalog_id, exc)
        return False


def delete_catalog(catalog_id: int) -> bool:
    """מסמן קטלוג כלא-פעיל (soft delete)."""
    return update_catalog(catalog_id, is_active=False)


# ─────────────────────────────────────────────────────────────────────────────
# הרשאות קטלוג — הקצאה ידנית (רק custom)
# ─────────────────────────────────────────────────────────────────────────────

def get_user_catalog_slugs(telegram_id: int) -> set:
    perms = get_user_permissions(telegram_id)
    return {
        p[len("catalog."): ] for p in perms if p.startswith("catalog.")
    }


def toggle_catalog_permission(
    telegram_id: int, slug: str, granted_by: int = None
) -> bool:
    """מחזיר True אם הרשאה הופעלה, False אם בוטלה."""
    key       = f"catalog.{slug}"
    user_cats = get_user_catalog_slugs(telegram_id)
    if slug in user_cats:
        revoke_permission(telegram_id, key)
        return False
    else:
        grant_permission(telegram_id, key, granted_by=granted_by)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# הודעות
# ─────────────────────────────────────────────────────────────────────────────

def log_message(telegram_id: int, message: str, sent_by: int = None) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO user_messages_log (telegram_id, message, sent_by) VALUES (?,?,?)",
                (telegram_id, message, sent_by),
            )
            conn.commit()
    except Exception as exc:
        logger.error("log_message failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# הערות מנהל
# ─────────────────────────────────────────────────────────────────────────────

def add_admin_note(
    telegram_id: int, note: str, created_by: int = None
) -> bool:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO user_admin_notes (telegram_id, note, created_by) VALUES (?,?,?)",
                (telegram_id, note, created_by),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("add_admin_note failed: %s", exc)
        return False


def get_admin_notes(telegram_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM user_admin_notes WHERE telegram_id = ? ORDER BY created_at DESC",
            (telegram_id,),
        )
        return cur.fetchall()


def get_admin_note_by_id(note_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM user_admin_notes WHERE id = ?", (note_id,)
        )
        return cur.fetchone()


def delete_admin_note(note_id: int) -> bool:
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM user_admin_notes WHERE id = ?", (note_id,))
            conn.commit()
        return True
    except Exception as exc:
        logger.error("delete_admin_note failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# היסטוריה
# ─────────────────────────────────────────────────────────────────────────────

_HISTORY_ICON = {
    "warning":    "⚠️",
    "suspension": "⏸️",
    "unsuspend":  "🔓",
    "block":      "🚫",
    "unblock":    "✅",
    "message":    "💬",
    "note":       "📝",
    "revoke":     "❌",
}

_HISTORY_LABEL = {
    "warning":    "אזהרה נוספה",
    "suspension": "הושעה",
    "unsuspend":  "השעיה בוטלה",
    "block":      "נחסם",
    "unblock":    "חסימה שוחררה",
    "message":    "הודעה נשלחה",
    "note":       "הערה נוספה",
    "revoke":     "אימות בוטל",
}


def get_user_history(telegram_id: int, limit: int = 25) -> list:
    """מרכז היסטוריה מכמה טבלאות לתצוגה מאוחדת."""
    rows = []

    with get_connection() as conn:
        conn.row_factory = _row_factory

        for r in conn.execute(
            "SELECT created_at FROM user_warnings WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchall():
            rows.append({"type": "warning", "created_at": r["created_at"]})

        for r in conn.execute(
            "SELECT created_at, duration_key, lifted_at FROM user_suspensions WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchall():
            rows.append({
                "type":        "suspension",
                "created_at":  r["created_at"],
                "label_extra": SUSPEND_LABELS.get(r["duration_key"], r["duration_key"]),
            })
            if r["lifted_at"]:
                rows.append({"type": "unsuspend", "created_at": r["lifted_at"]})

        for r in conn.execute(
            "SELECT sent_at FROM user_messages_log WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchall():
            rows.append({"type": "message", "created_at": r["sent_at"]})

        for r in conn.execute(
            "SELECT created_at FROM user_admin_notes WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchall():
            rows.append({"type": "note", "created_at": r["created_at"]})

        for r in conn.execute(
            "SELECT action, created_at FROM user_action_log WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchall():
            rows.append({"type": r["action"], "created_at": r["created_at"]})

    rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    result = []
    for r in rows[:limit]:
        t     = r["type"]
        label = _HISTORY_LABEL.get(t, t)
        if "label_extra" in r:
            label += f" ({r['label_extra']})"
        result.append({
            "icon":       _HISTORY_ICON.get(t, "•"),
            "label":      label,
            "created_at": r.get("created_at", ""),
        })

    return result


# ─────────────────────────────────────────────────────────────────────────────
# עזר
# ─────────────────────────────────────────────────────────────────────────────

def _log_action(
    telegram_id: int, action: str, performed_by: int = None
) -> None:
    """
    מתעד פעולה ניהולית בטבלת user_action_log.
    action: 'block' | 'unblock' | 'revoke'
    """
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO user_action_log (telegram_id, action, performed_by) VALUES (?,?,?)",
                (telegram_id, action, performed_by),
            )
            conn.commit()
    except Exception as exc:
        logger.error("_log_action(%s, %s) failed: %s", telegram_id, action, exc)


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))


def _slugify(text: str) -> str:
    """ממיר שם חופשי ל-slug תקין (אותיות קטנות, קווים תחתונים, ללא תווים מיוחדים)."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "_", text)
    text = re.sub(r"-+", "_", text)
    return text[:40] or "catalog"