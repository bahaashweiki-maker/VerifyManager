"""
admin/publishing_keyboards.py
-------------------------------
מקלדות InlineKeyboard של מודול הפרסום — אדמין בלבד.

כל פונקציה מחזירה InlineKeyboardMarkup מוכן לשליחה.
כפתורי back / cancel / delete / confirm מגיעים מ-admin.ui_helpers.
"""

from __future__ import annotations

from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from admin.publishing_states import cb, BUTTON_TYPES
from admin.ui_helpers import (
    back_button, cancel_button,
    kb_cancel,
    kb_confirm_delete,          # re-export — שאר המודולים יכולים לייבא מכאן
    kb_toggle_delete, kb_move_row,
)

# re-export כדי ש-publishing_admin לא יצטרך לייבא מ-ui_helpers ישירות
__all__ = [
    "kb_main_menu",
    "kb_home_menu",
    "kb_pages_list",
    "kb_page_view",
    "kb_confirm_delete",        # גנרי מ-ui_helpers
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
    """תפריט ראשי של מודול הפרסום."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 דף הבית",  callback_data=cb("home", "menu"))],
        [InlineKeyboardButton("📄 עמודים",    callback_data=cb("pages", "list", "root"))],
        [InlineKeyboardButton("❌ סגור",      callback_data=cb("close"))],
    ])


# ---------------------------------------------------------------------------
# דף הבית
# ---------------------------------------------------------------------------

def kb_home_menu(has_image: bool, has_text: bool, is_active: bool) -> InlineKeyboardMarkup:
    """תפריט עריכת דף הבית."""
    img_label    = "🖼 שנה תמונה"  if has_image else "🖼 הוסף תמונה"
    text_label   = "✏️ שנה טקסט"  if has_text  else "✏️ הוסף טקסט"
    toggle_label = "🔴 השבת"       if is_active else "🟢 הפעל"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(img_label,    callback_data=cb("home", "edit_image"))],
        [InlineKeyboardButton(text_label,   callback_data=cb("home", "edit_text"))],
        [InlineKeyboardButton("🎛 כפתורים", callback_data=cb("btn", "list", "home", 1))],
        [InlineKeyboardButton(toggle_label, callback_data=cb("home", "toggle"))],
    ]
    if has_image:
        rows.insert(1, [
            InlineKeyboardButton("🗑 מחק תמונה", callback_data=cb("home", "clear_image"))
        ])
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
    רשימת עמודי-בן.

    כפתורי "עמוד חדש" ו-"קטלוג חדש" מוצגים בשורות נפרדות
    כדי שהתוויות לא יקוצרו במסכים צרים.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for page in pages:
        icon   = "📂" if page["page_type"] == "catalog" else "📄"
        suffix = "" if page["is_active"] else " 🔇"
        rows.append([InlineKeyboardButton(
            f"{icon} {page['title']}{suffix}",
            callback_data=cb("page", "view", page["id"]),
        )])

    # שורה נפרדת לכל אחד מכפתורי היצירה
    rows.append([InlineKeyboardButton(
        "➕ עמוד חדש",
        callback_data=cb("page", "new", parent_id or 0),
    )])
    rows.append([InlineKeyboardButton(
        "📂 קטלוג חדש",
        callback_data=cb("page", "new_catalog", parent_id or 0),
    )])
    rows.append([back_button(back_cb)])
    return InlineKeyboardMarkup(rows)


def kb_page_view(
    page_id: int,
    is_active: bool,
    has_children: bool,
    parent_id: Optional[int],
) -> InlineKeyboardMarkup:
    """תפריט עמוד יחיד."""
    back_cb = cb("pages", "list", parent_id if parent_id is not None else "root")

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("✏️ ערוך כותרת", callback_data=cb("page", "edit_title", page_id))],
        [InlineKeyboardButton("🖼 ערוך תמונה",  callback_data=cb("page", "edit_image", page_id))],
        [InlineKeyboardButton("📝 ערוך טקסט",   callback_data=cb("page", "edit_text",  page_id))],
        [InlineKeyboardButton("🎛 כפתורים",     callback_data=cb("btn",  "list", "page", page_id))],
    ]
    if has_children:
        rows.append([InlineKeyboardButton(
            "📂 עמודי-בן", callback_data=cb("pages", "list", page_id)
        )])

    rows.append(kb_toggle_delete(
        toggle_cb=cb("page", "toggle", page_id),
        delete_cb=cb("page", "delete", page_id),
        is_active=is_active,
    ))
    rows.append(kb_move_row(
        up_cb=cb("page", "up", page_id),
        down_cb=cb("page", "down", page_id),
    ))
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
    """רשימת כפתורים."""
    _TYPE_ICON = {
        "text": "📝", "url": "🔗", "page_link": "📄",
        "phone": "📞", "email": "📧", "location": "📍", "share": "🔁",
    }
    rows: list[list[InlineKeyboardButton]] = []
    for btn in buttons:
        suffix = "" if btn["is_active"] else " 🔇"
        icon   = _TYPE_ICON.get(btn["button_type"], "•")
        rows.append([InlineKeyboardButton(
            f"{icon} {btn['label']}{suffix}",
            callback_data=cb("btn", "view", btn["id"]),
        )])

    rows.append([InlineKeyboardButton(
        "➕ כפתור חדש",
        callback_data=cb("btn", "new", owner_type, owner_id),
    )])
    rows.append([back_button(back_cb)])
    return InlineKeyboardMarkup(rows)


def kb_button_type_select(owner_type: str, owner_id: int) -> InlineKeyboardMarkup:
    """בחירת סוג כפתור."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(label, callback_data=cb("btn", "set_type", btype, owner_type, owner_id))]
        for btype, label in BUTTON_TYPES.items()
    ]
    rows.append([cancel_button(cb("btn", "list", owner_type, owner_id))])
    return InlineKeyboardMarkup(rows)


def kb_button_view(
    btn_id: int,
    is_active: bool,
    owner_type: str,
    owner_id: int,
) -> InlineKeyboardMarkup:
    """
    תפריט כפתור יחיד.

    שורת ההזזה כוללת 4 כיוונים:
      ⬅️ ⬆️ ⬇️ ➡️
    ⬆️/⬇️ — מעביר את הכפתור לשורה מעל/מתחת (row_index).
    ⬅️/➡️ — מחליף עם שכן שמאל/ימין באותה שורה (sort_order).

    ➕ הוסף לימין — יוצר כפתור חדש באותו row_index.
    """
    back_cb = cb("btn", "list", owner_type, owner_id)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("✏️ ערוך תווית",   callback_data=cb("btn", "edit_label",  btn_id))],
        [InlineKeyboardButton("🔄 שנה סוג",       callback_data=cb("btn", "edit_type",   btn_id))],
        [InlineKeyboardButton("📋 ערוך ערך",      callback_data=cb("btn", "edit_value",  btn_id))],
        [InlineKeyboardButton("📋 שכפל",          callback_data=cb("btn", "duplicate",   btn_id))],
        [InlineKeyboardButton("➕ הוסף לימין",    callback_data=cb("btn", "add_to_row",  btn_id))],
        kb_move_row(
            up_cb=cb("btn", "up",    btn_id),
            down_cb=cb("btn", "down", btn_id),
            left_cb=cb("btn", "left", btn_id),
            right_cb=cb("btn", "right", btn_id),
        ),
        kb_toggle_delete(
            toggle_cb=cb("btn", "toggle", btn_id),
            delete_cb=cb("btn", "delete", btn_id),
            is_active=is_active,
        ),
        [back_button(back_cb)],
    ]
    return InlineKeyboardMarkup(rows)


def kb_button_type_change(btn_id: int) -> InlineKeyboardMarkup:
    """בחירת סוג חדש לכפתור קיים (עדכון, לא יצירה)."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(label, callback_data=cb("btn", "apply_type", btype, btn_id))]
        for btype, label in BUTTON_TYPES.items()
    ]
    rows.append([cancel_button(cb("btn", "view", btn_id))])
    return InlineKeyboardMarkup(rows)


def kb_select_target_page(pages: list, btn_id: int) -> InlineKeyboardMarkup:
    """בחירת עמוד יעד לכפתור page_link."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(page["title"], callback_data=cb("btn", "set_target", btn_id, page["id"]))]
        for page in pages
    ]
    rows.append([cancel_button(cb("btn", "view", btn_id))])
    return InlineKeyboardMarkup(rows)


def kb_wait_input(back_cb: str) -> InlineKeyboardMarkup:
    """
    מקלדת סטנדרטית לכל מצב 'ממתין לקלט':
    כפתור ביטול אחד שחוזר אחורה.
    """
    return kb_cancel(back_cb)