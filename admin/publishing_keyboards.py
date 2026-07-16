"""
admin/publishing_keyboards.py
-------------------------------
מקלדות InlineKeyboard של מודול הפרסום — אדמין בלבד.

עקרונות עיצוב:
  • כל פעולה — שורה משלה. אין צפיפות.
  • סדר עקבי בכל מסך: עריכה → תוכן → סדר → ניהול → ניווט.
  • מינוח אחיד: "◀️ חזור" בכל מקום, ללא ערבוב עם "ביטול".
  • כפתורי ⬆️ למעלה / ⬇️ למטה עם תווית מפורשת.
"""

from __future__ import annotations

from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from admin.publishing_states import cb, BUTTON_TYPES
from admin.ui_helpers import (
    back_button, cancel_button,
    kb_cancel,
    kb_confirm_delete,
    kb_toggle_delete, kb_move_row,
)

__all__ = [
    "kb_main_menu",
    "kb_home_menu",
    "kb_pages_list",
    "kb_page_view",
    "kb_confirm_delete",
    "kb_buttons_list",
    "kb_button_type_select",
    "kb_button_type_change",
    "kb_button_view",
    "kb_select_target_page",
    "kb_wait_input",
]

# ---------------------------------------------------------------------------
# תפריט ראשי
# ---------------------------------------------------------------------------

def kb_main_menu() -> InlineKeyboardMarkup:
    """תפריט ראשי — כניסה למודול הפרסום."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 דף הבית",          callback_data=cb("home", "menu"))],
        [InlineKeyboardButton("📄 עמודים וקטלוגים", callback_data=cb("pages", "list", "root"))],
        [InlineKeyboardButton("❌ סגור",              callback_data=cb("close"))],
    ])


# ---------------------------------------------------------------------------
# דף הבית
# ---------------------------------------------------------------------------

def kb_home_menu(has_image: bool, has_text: bool, is_active: bool) -> InlineKeyboardMarkup:
    """
    תפריט עריכת דף הבית.

    מבנה: תוכן → כפתורים → הגדרות → ניווט.
    """
    img_label    = "🖼 שנה תמונה"  if has_image else "🖼 הוסף תמונה"
    text_label   = "✏️ שנה טקסט"  if has_text  else "✏️ הוסף טקסט"
    toggle_label = "🔴 השבת דף הבית" if is_active else "🟢 הפעל דף הבית"

    rows: list[list[InlineKeyboardButton]] = []

    # ── תוכן ──
    rows.append([InlineKeyboardButton(img_label,  callback_data=cb("home", "edit_image"))])
    if has_image:
        rows.append([InlineKeyboardButton("🗑 הסר תמונה", callback_data=cb("home", "clear_image"))])
    rows.append([InlineKeyboardButton(text_label, callback_data=cb("home", "edit_text"))])

    # ── כפתורים ──
    rows.append([InlineKeyboardButton("🎛 ניהול כפתורים", callback_data=cb("btn", "list", "home", 1))])

    # ── הגדרות ──
    rows.append([InlineKeyboardButton(toggle_label, callback_data=cb("home", "toggle"))])

    # ── ניווט ──
    rows.append([back_button(cb("main"))])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# עמודים
# ---------------------------------------------------------------------------

def kb_pages_list(
    pages: list,
    parent_id: Optional[int],
    back_cb: str,
) -> InlineKeyboardMarkup:
    """
    רשימת עמודים/קטלוגים.

    כל פריט — שורה מלאה. כפתורי הוספה נפרדים ולא צפופים.
    """
    rows: list[list[InlineKeyboardButton]] = []

    for page in pages:
        icon   = "📂" if page["page_type"] == "catalog" else "📄"
        status = "" if page["is_active"] else " 🔇"
        rows.append([InlineKeyboardButton(
            f"{icon} {page['title']}{status}",
            callback_data=cb("page", "view", page["id"]),
        )])

    # ── הוספה ──
    rows.append([InlineKeyboardButton("➕ עמוד חדש",    callback_data=cb("page", "new",         parent_id or 0))])
    rows.append([InlineKeyboardButton("📂 קטלוג חדש",   callback_data=cb("page", "new_catalog", parent_id or 0))])

    # ── ניווט ──
    rows.append([back_button(back_cb)])
    return InlineKeyboardMarkup(rows)


def kb_page_view(
    page_id: int,
    is_active: bool,
    has_children: bool,
    parent_id: Optional[int],
) -> InlineKeyboardMarkup:
    """
    מסך עמוד יחיד.

    מבנה: עריכה → תוכן → סדר → ניהול → ניווט.
    """
    back_cb = cb("pages", "list", parent_id if parent_id is not None else "root")

    rows: list[list[InlineKeyboardButton]] = []

    # ── עריכה ──
    rows.append([InlineKeyboardButton("✏️ ערוך כותרת", callback_data=cb("page", "edit_title", page_id))])
    rows.append([InlineKeyboardButton("🖼 ערוך תמונה",  callback_data=cb("page", "edit_image", page_id))])
    rows.append([InlineKeyboardButton("📝 ערוך טקסט",   callback_data=cb("page", "edit_text",  page_id))])

    # ── תוכן ──
    rows.append([InlineKeyboardButton("🎛 ניהול כפתורים", callback_data=cb("btn", "list", "page", page_id))])
    if has_children:
        rows.append([InlineKeyboardButton("📂 עמודי-בן", callback_data=cb("pages", "list", page_id))])

    # ── סדר ──
    rows.append(kb_move_row(
        up_cb=cb("page", "up",   page_id),
        down_cb=cb("page", "down", page_id),
    ))

    # ── ניהול ──
    rows.append(kb_toggle_delete(
        toggle_cb=cb("page", "toggle", page_id),
        delete_cb=cb("page", "delete", page_id),
        is_active=is_active,
    ))

    # ── ניווט ──
    rows.append([back_button(back_cb)])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# כפתורים
# ---------------------------------------------------------------------------

def kb_buttons_list(
    buttons: list,
    owner_type: str,
    owner_id: int,
    back_cb: str,
) -> InlineKeyboardMarkup:
    """
    רשימת כפתורים — כל כפתור שורה מלאה עם אייקון לפי סוג.
    """
    _ICON = {
        "text":      "📝",
        "url":       "🔗",
        "page_link": "📄",
        "phone":     "📞",
        "email":     "📧",
        "location":  "📍",
        "share":     "🔁",
    }
    rows: list[list[InlineKeyboardButton]] = []

    for btn in buttons:
        status = "" if btn["is_active"] else " 🔇"
        icon   = _ICON.get(btn["button_type"], "•")
        rows.append([InlineKeyboardButton(
            f"{icon} {btn['label']}{status}",
            callback_data=cb("btn", "view", btn["id"]),
        )])

    # ── הוספה ──
    rows.append([InlineKeyboardButton("➕ כפתור חדש", callback_data=cb("btn", "new", owner_type, owner_id))])

    # ── ניווט ──
    rows.append([back_button(back_cb)])
    return InlineKeyboardMarkup(rows)


def kb_button_view(
    btn_id: int,
    is_active: bool,
    owner_type: str,
    owner_id: int,
) -> InlineKeyboardMarkup:
    """
    מסך כפתור יחיד.

    מבנה: עריכה → פעולות → סדר → ניהול → ניווט.
    אייקון שכפול (📑) שונה מ-ערוך ערך (📋) למניעת בלבול.
    """
    back_cb = cb("btn", "list", owner_type, owner_id)

    rows: list[list[InlineKeyboardButton]] = []

    # ── עריכה ──
    rows.append([InlineKeyboardButton("✏️ ערוך תווית", callback_data=cb("btn", "edit_label", btn_id))])
    rows.append([InlineKeyboardButton("📋 ערוך ערך",   callback_data=cb("btn", "edit_value", btn_id))])
    rows.append([InlineKeyboardButton("🔄 שנה סוג",    callback_data=cb("btn", "edit_type",  btn_id))])

    # ── פעולות ──
    rows.append([InlineKeyboardButton("📑 שכפל כפתור", callback_data=cb("btn", "duplicate", btn_id))])

    # ── סדר ──
    rows.append(kb_move_row(
        up_cb=cb("btn", "up",   btn_id),
        down_cb=cb("btn", "down", btn_id),
    ))

    # ── ניהול ──
    rows.append(kb_toggle_delete(
        toggle_cb=cb("btn", "toggle", btn_id),
        delete_cb=cb("btn", "delete", btn_id),
        is_active=is_active,
    ))

    # ── ניווט ──
    rows.append([back_button(back_cb)])
    return InlineKeyboardMarkup(rows)


def kb_button_type_select(owner_type: str, owner_id: int) -> InlineKeyboardMarkup:
    """בחירת סוג כפתור — כל סוג שורה משלו."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(label, callback_data=cb("btn", "set_type", btype, owner_type, owner_id))]
        for btype, label in BUTTON_TYPES.items()
    ]
    rows.append([back_button(cb("btn", "list", owner_type, owner_id))])
    return InlineKeyboardMarkup(rows)


def kb_button_type_change(btn_id: int) -> InlineKeyboardMarkup:
    """בחירת סוג חדש לכפתור קיים."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(label, callback_data=cb("btn", "apply_type", btype, btn_id))]
        for btype, label in BUTTON_TYPES.items()
    ]
    rows.append([back_button(cb("btn", "view", btn_id))])
    return InlineKeyboardMarkup(rows)


def kb_select_target_page(pages: list, btn_id: int) -> InlineKeyboardMarkup:
    """בחירת עמוד יעד לכפתור page_link — כל עמוד שורה משלו."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"{'📂' if page['page_type'] == 'catalog' else '📄'} {page['title']}",
            callback_data=cb("btn", "set_target", btn_id, page["id"]),
        )]
        for page in pages
    ]
    rows.append([back_button(cb("btn", "view", btn_id))])
    return InlineKeyboardMarkup(rows)


def kb_wait_input(back_cb: str) -> InlineKeyboardMarkup:
    """
    מקלדת בכל מצב 'ממתין לקלט'.
    כפתור חזרה בלבד — ברור שהפעולה לא מחויבת.
    """
    return kb_cancel(back_cb)