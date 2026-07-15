"""
repositories/pub_page_repository.py
--------------------------------------
גישה ל-DB עבור טבלת publishing_pages של מודול הפרסום.

⚠️  קובץ זה נפרד מ-page_repository.py הקיים במערכת —
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

def pub_get_pages_by_parent(parent_id: Optional[int]) -> list:
    """
    מחזיר את כל עמודי-הבן של parent_id, ממוינים לפי sort_order.

    Parameters:
        parent_id: מזהה עמוד-אב, או None לעמודים ברמה ראשונה.

    Returns:
        רשימת sqlite3.Row (ריקה בכשל).
    """
    try:
        with get_connection() as conn:
            if parent_id is None:
                rows = conn.execute(
                    "SELECT * FROM publishing_pages"
                    " WHERE parent_id IS NULL"
                    " ORDER BY sort_order ASC, id ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM publishing_pages"
                    " WHERE parent_id = ?"
                    " ORDER BY sort_order ASC, id ASC",
                    (parent_id,),
                ).fetchall()
        return rows
    except sqlite3.Error as exc:
        logger.error("pub_get_pages_by_parent(%s) failed: %s", parent_id, exc, exc_info=True)
        return []


def pub_get_page_by_id(page_id: int) -> Optional[sqlite3.Row]:
    """
    מחזיר עמוד יחיד לפי id.

    Returns:
        sqlite3.Row או None אם לא נמצא / בכשל.
    """
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM publishing_pages WHERE id = ?", (page_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("pub_get_page_by_id(%d) failed: %s", page_id, exc, exc_info=True)
        return None


def pub_get_all_pages() -> list:
    """
    מחזיר את כל העמודים, ממוינים לפי sort_order.

    שימושי לבחירת עמוד יעד לכפתור page_link.
    """
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM publishing_pages ORDER BY sort_order ASC, id ASC"
            ).fetchall()
    except sqlite3.Error as exc:
        logger.error("pub_get_all_pages failed: %s", exc, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# יצירה
# ---------------------------------------------------------------------------

def pub_create_page(
    title: str,
    page_type: str = "page",
    parent_id: Optional[int] = None,
) -> int:
    """
    יוצר עמוד חדש.

    Parameters:
        title:     כותרת העמוד.
        page_type: 'page' | 'catalog'.
        parent_id: מזהה עמוד-אב (None = רמה ראשונה).

    Returns:
        id של העמוד החדש, או -1 בכשל.
    """
    try:
        with get_connection() as conn:
            # sort_order = מקסימום קיים + 1 באותה רמה
            row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM publishing_pages"
                " WHERE parent_id IS ?" if parent_id is None
                else "SELECT COALESCE(MAX(sort_order), -1) FROM publishing_pages"
                     " WHERE parent_id = ?",
                (None if parent_id is None else parent_id,),
            ).fetchone()
            next_order = (row[0] + 1) if row else 0

            cur = conn.execute(
                "INSERT INTO publishing_pages (title, page_type, parent_id, sort_order)"
                " VALUES (?, ?, ?, ?)",
                (title, page_type, parent_id, next_order),
            )
            conn.commit()
            new_id: int = cur.lastrowid  # type: ignore[assignment]
        logger.info("pub_create_page: created id=%d title='%s'", new_id, title)
        return new_id
    except sqlite3.Error as exc:
        logger.error("pub_create_page failed: %s", exc, exc_info=True)
        return -1


# ---------------------------------------------------------------------------
# עדכון
# ---------------------------------------------------------------------------

def pub_update_page_title(page_id: int, title: str) -> bool:
    """עדכון כותרת עמוד."""
    return _update_page_field(page_id, "title", title)


def pub_update_page_image(page_id: int, file_id: Optional[str]) -> bool:
    """עדכון תמונת עמוד (file_id טלגרם, או None לניקוי)."""
    return _update_page_field(page_id, "image_file_id", file_id)


def pub_update_page_text(page_id: int, text: Optional[str]) -> bool:
    """עדכון טקסט עמוד."""
    return _update_page_field(page_id, "text", text)


def pub_toggle_page_active(page_id: int) -> bool:
    """מחליף מצב הפעלה של עמוד."""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE publishing_pages"
                " SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END,"
                "     updated_at = CURRENT_TIMESTAMP"
                " WHERE id = ?",
                (page_id,),
            )
            conn.commit()
        return True
    except sqlite3.Error as exc:
        logger.error("pub_toggle_page_active(%d) failed: %s", page_id, exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# סדר
# ---------------------------------------------------------------------------

def pub_move_page_up(page_id: int) -> bool:
    """
    מחליף את sort_order של העמוד עם קודמו באותה רמה.

    Returns:
        True אם הוחלף, False אם העמוד כבר ראשון / בכשל.
    """
    return _swap_sort_order(page_id, direction="up")


def pub_move_page_down(page_id: int) -> bool:
    """
    מחליף את sort_order של העמוד עם העמוד אחריו באותה רמה.

    Returns:
        True אם הוחלף, False אם העמוד כבר אחרון / בכשל.
    """
    return _swap_sort_order(page_id, direction="down")


# ---------------------------------------------------------------------------
# מחיקה
# ---------------------------------------------------------------------------

def pub_delete_page(page_id: int) -> bool:
    """
    מוחק עמוד וכל עמודי-הבן והכפתורים שלו (CASCADE).

    PRAGMA foreign_keys=ON נדרש — מופעל ב-get_connection().

    Returns:
        True אם נמחק, False בכשל.
    """
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM publishing_pages WHERE id = ?", (page_id,)
            )
            conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            logger.info("pub_delete_page: deleted id=%d (cascade)", page_id)
        else:
            logger.warning("pub_delete_page: id=%d not found", page_id)
        return deleted
    except sqlite3.Error as exc:
        logger.error("pub_delete_page(%d) failed: %s", page_id, exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# פנימי
# ---------------------------------------------------------------------------

def _update_page_field(page_id: int, field: str, value: object) -> bool:
    try:
        with get_connection() as conn:
            cur = conn.execute(
                f"UPDATE publishing_pages"
                f" SET {field} = ?, updated_at = CURRENT_TIMESTAMP"
                f" WHERE id = ?",
                (value, page_id),
            )
            conn.commit()
            ok = cur.rowcount > 0
        if not ok:
            logger.warning("_update_page_field: id=%d not found", page_id)
        return ok
    except sqlite3.Error as exc:
        logger.error(
            "_update_page_field(%s, id=%d) failed: %s", field, page_id, exc, exc_info=True
        )
        return False


def _swap_sort_order(page_id: int, direction: str) -> bool:
    """מחליף sort_order עם השכן (up = sort_order קטן יותר, down = גדול יותר)."""
    try:
        with get_connection() as conn:
            page = conn.execute(
                "SELECT sort_order, parent_id FROM publishing_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            if page is None:
                return False

            current_order = page["sort_order"]
            parent_id     = page["parent_id"]

            # מצא שכן בכיוון המבוקש
            if direction == "up":
                neighbour = conn.execute(
                    "SELECT id, sort_order FROM publishing_pages"
                    " WHERE parent_id IS ? AND sort_order < ?"
                    " ORDER BY sort_order DESC LIMIT 1"
                    if parent_id is None else
                    "SELECT id, sort_order FROM publishing_pages"
                    " WHERE parent_id = ? AND sort_order < ?"
                    " ORDER BY sort_order DESC LIMIT 1",
                    (parent_id, current_order),
                ).fetchone()
            else:
                neighbour = conn.execute(
                    "SELECT id, sort_order FROM publishing_pages"
                    " WHERE parent_id IS ? AND sort_order > ?"
                    " ORDER BY sort_order ASC LIMIT 1"
                    if parent_id is None else
                    "SELECT id, sort_order FROM publishing_pages"
                    " WHERE parent_id = ? AND sort_order > ?"
                    " ORDER BY sort_order ASC LIMIT 1",
                    (parent_id, current_order),
                ).fetchone()

            if neighbour is None:
                return False  # כבר בקצה

            # החלפה
            conn.execute(
                "UPDATE publishing_pages SET sort_order = ? WHERE id = ?",
                (neighbour["sort_order"], page_id),
            )
            conn.execute(
                "UPDATE publishing_pages SET sort_order = ? WHERE id = ?",
                (current_order, neighbour["id"]),
            )
            conn.commit()
        return True
    except sqlite3.Error as exc:
        logger.error("_swap_sort_order(%d, %s) failed: %s", page_id, direction, exc, exc_info=True)
        return False