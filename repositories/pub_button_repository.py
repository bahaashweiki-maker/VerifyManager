"""
repositories/pub_button_repository.py
----------------------------------------
גישה ל-DB עבור טבלת publishing_buttons של מודול הפרסום.

⚠️  קובץ זה נפרד מ-button_repository.py הקיים במערכת —
    אין קשר בין הטבלאות ואין ייבוא ממנו.

כל פונקציה:
- משתמשת ב-get_connection() כ-context manager (with).
- מחזירה ערך בטוח (None / [] / False / -1) בכשל.
- רושמת שגיאות ל-logger.
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

def pub_get_buttons_for_home(home_id: int = 1) -> list:
    """
    מחזיר את כל כפתורי דף הבית, ממוינים לפי sort_order.

    Parameters:
        home_id: תמיד 1 (singleton) — נמסר לשלמות הממשק.
    """
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM publishing_buttons"
                " WHERE home_id = ?"
                " ORDER BY sort_order ASC, id ASC",
                (home_id,),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.error("pub_get_buttons_for_home(%d) failed: %s", home_id, exc, exc_info=True)
        return []


def pub_get_buttons_for_page(page_id: int) -> list:
    """
    מחזיר את כל כפתורי עמוד, ממוינים לפי sort_order.
    """
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM publishing_buttons"
                " WHERE page_id = ?"
                " ORDER BY sort_order ASC, id ASC",
                (page_id,),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.error("pub_get_buttons_for_page(%d) failed: %s", page_id, exc, exc_info=True)
        return []


def pub_get_button_by_id(btn_id: int) -> Optional[sqlite3.Row]:
    """
    מחזיר כפתור יחיד לפי id.

    Returns:
        sqlite3.Row או None אם לא נמצא / בכשל.
    """
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM publishing_buttons WHERE id = ?", (btn_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("pub_get_button_by_id(%d) failed: %s", btn_id, exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# יצירה
# ---------------------------------------------------------------------------

def pub_create_button(
    label: str,
    button_type: str = "text",
    value: Optional[str] = None,
    home_id: Optional[int] = None,
    page_id: Optional[int] = None,
    target_page_id: Optional[int] = None,
    row_index: Optional[int] = None,
) -> int:
    """
    יוצר כפתור חדש.

    בדיוק אחד מ-home_id / page_id חייב להיות מסופק (CHECK constraint בDB).

    Parameters:
        label:          תווית הכפתור.
        button_type:    'text' | 'url' | 'page_link' | 'phone' | 'email' | 'location' | 'share'.
        value:          ערך הכפתור (URL, טקסט, מס' טלפון, ...).
        home_id:        1 אם שייך לדף הבית, None אחרת.
        page_id:        מזהה עמוד אם שייך לעמוד, None אחרת.
        target_page_id: לכפתורי page_link — מזהה עמוד היעד.
        row_index:      שורה להוסיף אליה. None = שורה חדשה אחרי האחרונה.

    Returns:
        id הכפתור החדש, או -1 בכשל.
    """
    try:
        with get_connection() as conn:
            owner_col = "home_id" if home_id is not None else "page_id"
            owner_val = home_id   if home_id is not None else page_id

            # sort_order = מקסימום קיים + 1 עבור אותו owner
            row = conn.execute(
                f"SELECT COALESCE(MAX(sort_order), -1) FROM publishing_buttons WHERE {owner_col} = ?",
                (owner_val,),
            ).fetchone()
            next_order = (row[0] + 1) if row else 0

            # row_index: אם לא נמסר — שורה חדשה אחרי האחרונה
            if row_index is None:
                ri_row = conn.execute(
                    f"SELECT COALESCE(MAX(row_index), -1) FROM publishing_buttons WHERE {owner_col} = ?",
                    (owner_val,),
                ).fetchone()
                row_index = (ri_row[0] + 1) if ri_row else 0

            cur = conn.execute(
                "INSERT INTO publishing_buttons"
                " (label, button_type, value, home_id, page_id, target_page_id, sort_order, row_index)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (label, button_type, value, home_id, page_id, target_page_id, next_order, row_index),
            )
            conn.commit()
            new_id: int = cur.lastrowid  # type: ignore[assignment]
        logger.info("pub_create_button: created id=%d label='%s'", new_id, label)
        return new_id
    except sqlite3.Error as exc:
        logger.error("pub_create_button failed: %s", exc, exc_info=True)
        return -1


# ---------------------------------------------------------------------------
# עדכון
# ---------------------------------------------------------------------------

def pub_update_button_label(btn_id: int, label: str) -> bool:
    """עדכון תווית כפתור."""
    return _update_btn_field(btn_id, "label", label)


def pub_update_button_value(btn_id: int, value: Optional[str]) -> bool:
    """עדכון ערך כפתור."""
    return _update_btn_field(btn_id, "value", value)


def pub_update_button_type(btn_id: int, button_type: str) -> bool:
    """עדכון סוג כפתור."""
    return _update_btn_field(btn_id, "button_type", button_type)


def pub_update_button_target_page(btn_id: int, target_page_id: Optional[int]) -> bool:
    """עדכון עמוד יעד לכפתור page_link."""
    return _update_btn_field(btn_id, "target_page_id", target_page_id)


def pub_toggle_button_active(btn_id: int) -> bool:
    """מחליף מצב הפעלה של כפתור."""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE publishing_buttons"
                " SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END,"
                "     updated_at = CURRENT_TIMESTAMP"
                " WHERE id = ?",
                (btn_id,),
            )
            conn.commit()
        return True
    except sqlite3.Error as exc:
        logger.error("pub_toggle_button_active(%d) failed: %s", btn_id, exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# סדר
# ---------------------------------------------------------------------------

def pub_move_button_up(btn_id: int) -> bool:
    """מחליף sort_order עם הכפתור שלפניו (sort_order קטן יותר)."""
    return _swap_btn_order(btn_id, direction="up")


def pub_move_button_down(btn_id: int) -> bool:
    """מחליף sort_order עם הכפתור שאחריו (sort_order גדול יותר)."""
    return _swap_btn_order(btn_id, direction="down")


def pub_move_button_left(btn_id: int) -> bool:
    """מחליף sort_order עם השכן השמאלי באותה שורה (sort_order קטן יותר, row_index זהה)."""
    return _swap_btn_in_row(btn_id, direction="left")


def pub_move_button_right(btn_id: int) -> bool:
    """מחליף sort_order עם השכן הימני באותה שורה (sort_order גדול יותר, row_index זהה)."""
    return _swap_btn_in_row(btn_id, direction="right")


# ---------------------------------------------------------------------------
# שכפול
# ---------------------------------------------------------------------------

def pub_duplicate_button(btn_id: int) -> int:
    """
    משכפל כפתור קיים — מוסיף אחריו עם אותם שדות + "(עותק)" בתווית.

    Returns:
        id הכפתור החדש, או -1 בכשל.
    """
    try:
        with get_connection() as conn:
            btn = conn.execute(
                "SELECT * FROM publishing_buttons WHERE id = ?", (btn_id,)
            ).fetchone()
            if btn is None:
                logger.warning("pub_duplicate_button: id=%d not found", btn_id)
                return -1

            cur = conn.execute(
                "INSERT INTO publishing_buttons"
                " (label, button_type, value, home_id, page_id, target_page_id,"
                "  sort_order, row_index, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{btn['label']} (עותק)",
                    btn["button_type"],
                    btn["value"],
                    btn["home_id"],
                    btn["page_id"],
                    btn["target_page_id"],
                    btn["sort_order"] + 1,   # מיד אחרי המקור
                    btn["row_index"],
                    btn["is_active"],
                ),
            )
            conn.commit()
            new_id: int = cur.lastrowid  # type: ignore[assignment]
        logger.info("pub_duplicate_button: duplicated %d -> %d", btn_id, new_id)
        return new_id
    except sqlite3.Error as exc:
        logger.error("pub_duplicate_button(%d) failed: %s", btn_id, exc, exc_info=True)
        return -1


# ---------------------------------------------------------------------------
# מחיקה
# ---------------------------------------------------------------------------

def pub_delete_button(btn_id: int) -> bool:
    """
    מוחק כפתור לפי id.

    Returns:
        True אם נמחק, False בכשל.
    """
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM publishing_buttons WHERE id = ?", (btn_id,)
            )
            conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            logger.info("pub_delete_button: deleted id=%d", btn_id)
        else:
            logger.warning("pub_delete_button: id=%d not found", btn_id)
        return deleted
    except sqlite3.Error as exc:
        logger.error("pub_delete_button(%d) failed: %s", btn_id, exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# פנימי
# ---------------------------------------------------------------------------

def _update_btn_field(btn_id: int, field: str, value: object) -> bool:
    try:
        with get_connection() as conn:
            cur = conn.execute(
                f"UPDATE publishing_buttons"
                f" SET {field} = ?, updated_at = CURRENT_TIMESTAMP"
                f" WHERE id = ?",
                (value, btn_id),
            )
            conn.commit()
            ok = cur.rowcount > 0
        if not ok:
            logger.warning("_update_btn_field: id=%d not found", btn_id)
        return ok
    except sqlite3.Error as exc:
        logger.error(
            "_update_btn_field(%s, id=%d) failed: %s", field, btn_id, exc, exc_info=True
        )
        return False


def _swap_btn_in_row(btn_id: int, direction: str) -> bool:
    """מחליף sort_order עם שכן באותה שורה (row_index זהה). left=קטן יותר, right=גדול יותר."""
    try:
        with get_connection() as conn:
            btn = conn.execute(
                "SELECT sort_order, row_index, home_id, page_id"
                " FROM publishing_buttons WHERE id = ?",
                (btn_id,),
            ).fetchone()
            if btn is None:
                return False

            current   = btn["sort_order"]
            row_index = btn["row_index"]
            home_id   = btn["home_id"]
            page_id   = btn["page_id"]
            owner_col = "home_id" if home_id is not None else "page_id"
            owner_val = home_id   if home_id is not None else page_id

            op      = "<" if direction == "left" else ">"
            ord_dir = "DESC" if direction == "left" else "ASC"

            neighbour = conn.execute(
                f"SELECT id, sort_order FROM publishing_buttons"
                f" WHERE {owner_col} = ? AND row_index = ? AND sort_order {op} ?"
                f" ORDER BY sort_order {ord_dir} LIMIT 1",
                (owner_val, row_index, current),
            ).fetchone()

            if neighbour is None:
                return False

            conn.execute(
                "UPDATE publishing_buttons SET sort_order = ? WHERE id = ?",
                (neighbour["sort_order"], btn_id),
            )
            conn.execute(
                "UPDATE publishing_buttons SET sort_order = ? WHERE id = ?",
                (current, neighbour["id"]),
            )
            conn.commit()
        return True
    except sqlite3.Error as exc:
        logger.error("_swap_btn_in_row(%d, %s) failed: %s", btn_id, direction, exc, exc_info=True)
        return False


def _swap_btn_order(btn_id: int, direction: str) -> bool:
    """מחליף sort_order עם השכן (up=קטן יותר, down=גדול יותר)."""
    try:
        with get_connection() as conn:
            btn = conn.execute(
                "SELECT sort_order, home_id, page_id FROM publishing_buttons WHERE id = ?",
                (btn_id,),
            ).fetchone()
            if btn is None:
                return False

            current   = btn["sort_order"]
            home_id   = btn["home_id"]
            page_id   = btn["page_id"]
            owner_col = "home_id" if home_id is not None else "page_id"
            owner_val = home_id   if home_id is not None else page_id

            op  = "<" if direction == "up" else ">"
            ord_dir = "DESC" if direction == "up" else "ASC"

            neighbour = conn.execute(
                f"SELECT id, sort_order FROM publishing_buttons"
                f" WHERE {owner_col} = ? AND sort_order {op} ?"
                f" ORDER BY sort_order {ord_dir} LIMIT 1",
                (owner_val, current),
            ).fetchone()

            if neighbour is None:
                return False  # כבר בקצה

            conn.execute(
                "UPDATE publishing_buttons SET sort_order = ? WHERE id = ?",
                (neighbour["sort_order"], btn_id),
            )
            conn.execute(
                "UPDATE publishing_buttons SET sort_order = ? WHERE id = ?",
                (current, neighbour["id"]),
            )
            conn.commit()
        return True
    except sqlite3.Error as exc:
        logger.error("_swap_btn_order(%d, %s) failed: %s", btn_id, direction, exc, exc_info=True)
        return False
