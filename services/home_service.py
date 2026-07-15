"""
services/home_service.py
--------------------------
לוגיקה עסקית לדף הבית של מודול הפרסום.

מתווך בין handlers ל-repositories.
"""

from __future__ import annotations

import logging
from typing import Optional
import sqlite3

from repositories.home_repository import (
    get_home,
    set_home_image,
    set_home_text,
    set_home_active,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# קריאה
# ---------------------------------------------------------------------------

def get_home_data() -> Optional[sqlite3.Row]:
    """
    מחזיר את נתוני דף הבית.

    Returns:
        sqlite3.Row עם כל שדות publishing_home, או None בכשל.
    """
    return get_home()


# ---------------------------------------------------------------------------
# עדכון תמונה
# ---------------------------------------------------------------------------

def update_home_image(file_id: Optional[str]) -> bool:
    """
    מעדכן את תמונת דף הבית.

    Parameters:
        file_id: ה-file_id מטלגרם (str), או None לניקוי התמונה.

    Returns:
        True אם הצליח, False בכשל.
    """
    ok = set_home_image(file_id)
    if ok:
        logger.info("Home image updated: %s", file_id or "cleared")
    return ok


def clear_home_image() -> bool:
    """
    מנקה את תמונת דף הבית.

    Returns:
        True אם הצליח, False בכשל.
    """
    return update_home_image(None)


# ---------------------------------------------------------------------------
# עדכון טקסט
# ---------------------------------------------------------------------------

def update_home_text(text: Optional[str]) -> bool:
    """
    מעדכן את טקסט דף הבית.

    Parameters:
        text: הטקסט החדש (תומך ב-HTML), או None לניקוי.

    Returns:
        True אם הצליח, False בכשל.
    """
    ok = set_home_text(text)
    if ok:
        logger.info("Home text updated (%d chars)", len(text) if text else 0)
    return ok


def clear_home_text() -> bool:
    """
    מנקה את טקסט דף הבית.

    Returns:
        True אם הצליח, False בכשל.
    """
    return update_home_text(None)


# ---------------------------------------------------------------------------
# הפעלה / כיבוי
# ---------------------------------------------------------------------------

def toggle_home_active() -> Optional[bool]:
    """
    הופך את מצב הפעלת דף הבית.

    Returns:
        המצב החדש (True=פעיל, False=כבוי), או None בכשל.
    """
    home = get_home()
    if home is None:
        return None
    new_state = not bool(home["is_active"])
    ok = set_home_active(new_state)
    if ok:
        logger.info("Home page toggled -> %s", "active" if new_state else "inactive")
        return new_state
    return None


# ---------------------------------------------------------------------------
# בדיקת תקינות לפני פרסום
# ---------------------------------------------------------------------------

def home_is_publishable() -> tuple[bool, list[str]]:
    """
    בודק אם דף הבית ניתן לפרסום (יש לו לפחות תמונה או טקסט).

    Returns:
        (is_ok, list_of_warnings)
        - is_ok: True אם ניתן לפרסם
        - list_of_warnings: רשימת אזהרות (ריקה אם הכל תקין)
    """
    home = get_home()
    if home is None:
        return False, ["לא ניתן לקרוא את נתוני דף הבית"]

    warnings: list[str] = []
    if not home["image_file_id"] and not home["text"]:
        warnings.append("דף הבית ריק — הוסף תמונה או טקסט")

    return len(warnings) == 0, warnings