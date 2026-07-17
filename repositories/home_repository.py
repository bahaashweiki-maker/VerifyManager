"""
repositories/home_repository.py
---------------------------------
גישה ישירה לטבלת publishing_home (singleton — תמיד id=1).

כל פונקציה מחזירה ערך בטוח (None / False) בכשל ורושמת ללוג.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from database.database import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# שליפה
# ---------------------------------------------------------------------------

def get_home() -> Optional[sqlite3.Row]:
    """
    מחזיר את שורת דף הבית (id=1).

    Returns:
        sqlite3.Row או None בשגיאה.
    """
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM publishing_home WHERE id = 1"
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("get_home failed: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# עדכון מדיה
# ---------------------------------------------------------------------------

def set_home_media(file_id: Optional[str], media_type: str = "photo") -> bool:
    """
    מעדכן את image_file_id ואת media_type של דף הבית בטרנזקציה אחת.

    Parameters:
        file_id:    file_id של המדיה מטלגרם, או None לניקוי.
        media_type: סוג המדיה — 'photo' | 'animation' | 'video'.
                    ברירת מחדל: 'photo'.

    Returns:
        True אם עודכן, False בשגיאה.
    """
    _VALID_MEDIA_TYPES = {
        "photo", "video", "animation", "audio",
        "voice", "document", "video_note", "sticker",
    }
    if media_type not in _VALID_MEDIA_TYPES:
        logger.warning(
            "set_home_media: unknown media_type '%s', defaulting to 'photo'", media_type
        )
        media_type = "photo"
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "UPDATE publishing_home"
                " SET image_file_id = ?, media_type = ?, updated_at = CURRENT_TIMESTAMP"
                " WHERE id = 1",
                (file_id, media_type),
            )
            conn.commit()
            updated = cur.rowcount > 0
        if not updated:
            logger.warning("set_home_media: singleton row (id=1) not found")
        return updated
    except sqlite3.Error as exc:
        logger.error("set_home_media failed: %s", exc, exc_info=True)
        return False


def set_home_image(file_id: Optional[str]) -> bool:
    """
    מעדכן את image_file_id של דף הבית (תאימות לאחור).

    Wrapper ל-set_home_media עם media_type='photo'.

    Parameters:
        file_id: file_id של תמונה מטלגרם, או None לניקוי.

    Returns:
        True אם עודכן, False בשגיאה.
    """
    return set_home_media(file_id, media_type="photo")


# ---------------------------------------------------------------------------
# עדכון טקסט
# ---------------------------------------------------------------------------

def set_home_text(text: Optional[str]) -> bool:
    """
    מעדכן את טקסט דף הבית.

    Parameters:
        text: הטקסט החדש, או None לניקוי.

    Returns:
        True אם עודכן, False בשגיאה.
    """
    return _update_home_field("text", text)


# ---------------------------------------------------------------------------
# הפעלה / כיבוי
# ---------------------------------------------------------------------------

def set_home_active(is_active: bool) -> bool:
    """
    מפעיל / מכבה את דף הבית.

    Parameters:
        is_active: True להפעלה, False לכיבוי.

    Returns:
        True אם עודכן, False בשגיאה.
    """
    return _update_home_field("is_active", int(is_active))


# ---------------------------------------------------------------------------
# פנימי
# ---------------------------------------------------------------------------

def _update_home_field(field: str, value: object) -> bool:
    """
    מעדכן שדה יחיד בשורת ה-singleton.

    field חייב להיות שם עמודה ידוע — הפונקציה אינה חשופה ל-SQL injection
    כי היא נקראת רק מפונקציות ציבוריות בקובץ זה.
    """
    try:
        with get_connection() as conn:
            cur = conn.execute(
                f"UPDATE publishing_home"
                f" SET {field} = ?, updated_at = CURRENT_TIMESTAMP"
                f" WHERE id = 1",
                (value,),
            )
            conn.commit()
            updated = cur.rowcount > 0
        if not updated:
            logger.warning("_update_home_field: singleton row (id=1) not found")
        return updated
    except sqlite3.Error as exc:
        logger.error(
            "_update_home_field(%s) failed: %s", field, exc, exc_info=True
        )
        return False
