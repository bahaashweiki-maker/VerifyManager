"""
admin/publishing_keyboards.py
-------------------------------
מקלדות InlineKeyboard של מודול הפרסום — אדמין בלבד.

כל פונקציה מחזירה InlineKeyboardMarkup מוכן לשליחה.
כפתורי back / cancel / delete / confirm מגיעים מ-admin.ui_helpers.

עקרונות עיצוב:
  • תוויות מציגות מצב חי (✅ / ריק / פעיל / כבוי) — לא רק שם הפעולה.
  • ⚠️ מסמן פעולות הרסניות (מחק) — שורה נפרדת, תמיד לפני חזור.
  • כפתור הפעל/השבת מראה את המצב הנוכחי ואת הפעולה הבאה.
  • כפתורי ניווט (חזור / ביטול) — שורה אחרונה, תווית עם הקשר ספציפי.
  • כפתורי כיוון קשורים (⬆️⬇️ / ⬅️➡️) — מותר באותה שורה.
  • פעולות משלימות — מותר לאגד זוג בשורה אחת; פעולות עצמאיות — שורה בפני עצמה.
"""

from __future__ import annotations

from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from admin.publishing_states import cb, BUTTON_TYPES
from admin.ui_helpers import (
    back_button, cancel_button,
    kb_cancel,
    kb_confirm_delete,          # re-export — שאר המודולים יכולים לייבא מכאן
    kb_move_row,
)

# re-export כדי ש-publishing_admin לא יצטרך לייבא מ-ui_helpers ישירות
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
    "kb_catalog_audience_select",
]


# ---------------------------------------------------------------------------
# תפריט ראשי
# ---------------------------------------------------------------------------

def kb_main_menu() -> InlineKeyboardMarkup:
    """תפריט ראשי של מודול הפרסום."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 ניהול דף הבית",  callback_data=cb("home", "menu"))],
        [InlineKeyboardButton("📄 ניהול עמודים",    callback_data=cb("pages", "list", "root"))],
        [InlineKeyboardButton("✖️ סגור",             callback_data=cb("close"))],
    ])


# ---------------------------------------------------------------------------
# דף הבית
# ---------------------------------------------------------------------------

def kb_home_menu(has_image: bool, has_text: bool, is_active: bool) -> InlineKeyboardMarkup:
    """
    תפריט עריכת דף הבית.

    כל תווית מציגה את המצב הנוכחי של השדה (יש / אין) לצד שם הפעולה,
    כך שהאדמין רואה מיד מה מוגדר ומה חסר — ללא צורך לפתוח כל שדה.
    """
    img_label  = "🎞 מדיה  ✅"          if has_image else "🎞 מדיה  ─  לחץ להוספה"
    text_label = "✏️ טקסט  ✅"          if has_text  else "✏️ טקסט  ─  לחץ להוספה"
    toggle_label = (
        "🟢 כרגע פעיל  ─  לחץ להשבתה"  if is_active
        else "🔴 כרגע כבוי  ─  לחץ להפעלה"
    )

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(img_label,  callback_data=cb("home", "edit_image"))],
    ]
    if has_image:
        rows.append([InlineKeyboardButton("🗑 הסר מדיה", callback_data=cb("home", "clear_image"))])
    rows += [
        [InlineKeyboardButton(text_label,   callback_data=cb("home", "edit_text"))],
        [InlineKeyboardButton("🎛 ניהול כפתורים", callback_data=cb("btn", "list", "home", 1))],
        [InlineKeyboardButton(toggle_label, callback_data=cb("home", "toggle"))],
        [back_button(cb("main"), "◀️ תפריט ראשי")],
    ]
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

    עמודים לא פעילים מסומנים ב-🔇 בסוף השורה.
    כפתורי יצירה — כל אחד בשורה נפרדת (תוויות ארוכות, צריך רוחב מלא).
    """
    rows: list[list[InlineKeyboardButton]] = []
    for page in pages:
        icon   = "📂" if page["page_type"] == "catalog" else "📄"
        suffix = "" if page["is_active"] else "  🔇"
        rows.append([InlineKeyboardButton(
            f"{icon} {page['title']}{suffix}",
            callback_data=cb("page", "view", page["id"]),
        )])

    back_label = "◀️ חזור לתפריט ראשי" if parent_id is None else "◀️ חזור לקטלוג"
    rows.append([InlineKeyboardButton("➕ עמוד חדש",  callback_data=cb("page", "new",         parent_id or 0))])
    rows.append([InlineKeyboardButton("📂 קטלוג חדש", callback_data=cb("page", "new_catalog", parent_id or 0))])
    rows.append([back_button(back_cb, back_label)])
    return InlineKeyboardMarkup(rows)


def kb_page_view(
    page_id: int,
    is_active: bool,
    has_children: bool,
    parent_id: Optional[int],
    page_type: str = "page",
) -> InlineKeyboardMarkup:
    """
    תפריט עמוד יחיד — תומך בעמוד רגיל ובקטלוג.

    page_type="catalog":
      • "📂 עמודי-בן" עולה לשורה ראשונה, רוחב מלא — זו המטרה העיקרית של קטלוג.
      • תוויות (כותרת / מחק) מותאמות לקטלוג.
    page_type="page" (ברירת מחדל):
      • כותרת+טקסט בשורה אחת, מדיה+כפתורים בשורה אחת.
      • "📂 עמודי-בן" מוצג בתחתית הקטע הראשי, רק אם יש ילדים.

    כל ה-callback_data זהים לשני הסוגים.
    """
    is_catalog = (page_type == "catalog")
    back_cb     = cb("pages", "list", parent_id if parent_id is not None else "root")
    toggle_label = (
        "🟢 כרגע פעיל  ─  לחץ להשבתה" if is_active
        else "🔴 כרגע כבוי  ─  לחץ להפעלה"
    )

    if is_catalog:
        # ── קטלוג ──────────────────────────────────────────────────────────
        # "עמודי-בן" עולה לשורה ראשונה, רוחב מלא — ההדגשה הויזואלית של קטלוג.
        # התווית מציגה מצב חי (✅ יש תוכן / ריק) בדיוק כפי שנעשה ב-kb_home_menu.
        children_label = "📂 עמודי-בן  ✅" if has_children else "📂 עמודי-בן  ─  ריק"
        rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton(children_label,                                        callback_data=cb("pages", "list", page_id))],
            [InlineKeyboardButton("✏️ שם קטלוג",  callback_data=cb("page", "edit_title", page_id))],
            [InlineKeyboardButton("📝 טקסט",       callback_data=cb("page", "edit_text",  page_id))],
            [InlineKeyboardButton("🎞 מדיה",       callback_data=cb("page", "edit_image", page_id))],
            [InlineKeyboardButton("🎛 כפתורים",    callback_data=cb("btn",  "list", "page", page_id))],
            [InlineKeyboardButton("👥 הרשאות צפייה", callback_data=cb("catalog", "edit_audience", page_id))],
            [InlineKeyboardButton("🔄 שנה קטלוג",    callback_data=cb("catalog", "relink",        page_id))],
        ]
    else:
        # ── עמוד רגיל ──────────────────────────────────────────────────────
        rows = [
            [InlineKeyboardButton("✏️ כותרת",     callback_data=cb("page", "edit_title", page_id))],
            [InlineKeyboardButton("📝 טקסט",      callback_data=cb("page", "edit_text",  page_id))],
            [InlineKeyboardButton("🎞 מדיה",      callback_data=cb("page", "edit_image", page_id))],
            [InlineKeyboardButton("🎛 כפתורים",   callback_data=cb("btn",  "list", "page", page_id))],
        ]
        if has_children:
            rows.append([InlineKeyboardButton(
                "📂 עמודי-בן", callback_data=cb("pages", "list", page_id),
            )])

    # ── משותף לשני הסוגים ──────────────────────────────────────────────────
    delete_label = "⚠️ מחק קטלוג" if is_catalog else "⚠️ מחק עמוד"
    rows += [
        kb_move_row(
            up_cb=cb("page", "up", page_id),
            down_cb=cb("page", "down", page_id),
        ),
        [InlineKeyboardButton(toggle_label,  callback_data=cb("page", "toggle", page_id))],
        [InlineKeyboardButton(delete_label,  callback_data=cb("page", "delete", page_id))],
        [back_button(back_cb, "◀️ חזור לרשימת עמודים")],
    ]
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# בחירת audience לקטלוג
# ---------------------------------------------------------------------------

def kb_catalog_audience_select(
    mode: str,
    audiences: dict,
    back_cb: str,
) -> InlineKeyboardMarkup:
    """
    מקלדת לבחירת audience (מי רואה את הקטלוג).

    mode:
      "new"            — בעת יצירת קטלוג חדש → callback: pub:catalog:new_audience:<key>
      "edit:<page_id>" — בעת עריכת קטלוג קיים → callback: pub:catalog:apply_audience:<page_id>:<key>

    audiences: מילון {key: תווית} — בד"כ CATALOG_AUDIENCES מ-verified_users_service.
    back_cb:   callback_data לכפתור ◀️ ביטול.
    """
    is_edit = mode.startswith("edit:")
    page_id = mode.split(":")[1] if is_edit else None

    rows = []
    for key, label in audiences.items():
        if is_edit:
            data = cb("catalog", "apply_audience", page_id, key)
        else:
            data = cb("catalog", "new_audience", key)
        rows.append([InlineKeyboardButton(label, callback_data=data)])

    rows.append([back_button(back_cb, "◀️ ביטול")])
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
    """רשימת כפתורים — כל כפתור בשורה עצמאית, סוג מסומן באייקון."""
    _TYPE_ICON = {
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
        suffix = "" if btn["is_active"] else "  🔇"
        icon   = _TYPE_ICON.get(btn["button_type"], "•")
        rows.append([InlineKeyboardButton(
            f"{icon} {btn['label']}{suffix}",
            callback_data=cb("btn", "view", btn["id"]),
        )])

    back_label = "◀️ חזור לדף הבית" if owner_type == "home" else "◀️ חזור לעמוד"
    rows.append([InlineKeyboardButton("➕ כפתור חדש", callback_data=cb("btn", "new", owner_type, owner_id))])
    rows.append([back_button(back_cb, back_label)])
    return InlineKeyboardMarkup(rows)


def kb_button_type_select(owner_type: str, owner_id: int) -> InlineKeyboardMarkup:
    """בחירת סוג כפתור חדש — כל סוג בשורה עצמאית."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(label, callback_data=cb("btn", "set_type", btype, owner_type, owner_id))]
        for btype, label in BUTTON_TYPES.items()
    ]
    rows.append([cancel_button(cb("btn", "list", owner_type, owner_id), "✖️ ביטול")])
    return InlineKeyboardMarkup(rows)


def kb_button_view(
    btn_id: int,
    is_active: bool,
    owner_type: str,
    owner_id: int,
) -> InlineKeyboardMarkup:
    """
    תפריט כפתור יחיד.

    תווית + סוג — זוג משלים בשורה אחת.
    שכפול + הוסף לשורה — זוג משלים בשורה אחת.
    ⬅️⬆️⬇️➡️ — ארבעת הכיוונים בשורה אחת:
        ⬆️/⬇️ = שינוי שורה (row_index) | ⬅️/➡️ = החלפה באותה שורה (sort_order).
    מצב + מחיקה — שורות נפרדות בתחתית.
    """
    back_cb = cb("btn", "list", owner_type, owner_id)
    toggle_label = (
        "🟢 כרגע פעיל  ─  לחץ להשבתה" if is_active
        else "🔴 כרגע כבוי  ─  לחץ להפעלה"
    )

    rows: list[list[InlineKeyboardButton]] = [
        # תווית + סוג — שתי תכונות בסיסיות
        [
            InlineKeyboardButton("✏️ תווית",  callback_data=cb("btn", "edit_label", btn_id)),
            InlineKeyboardButton("🔄 סוג",    callback_data=cb("btn", "edit_type",  btn_id)),
        ],
        [InlineKeyboardButton("📋 ערוך ערך", callback_data=cb("btn", "edit_value", btn_id))],
        # שכפול + הוסף לשורה — שתי פעולות מיקום משלימות
        [
            InlineKeyboardButton("📑 שכפל",          callback_data=cb("btn", "duplicate",  btn_id)),
            InlineKeyboardButton("➕ הוסף לאותה שורה", callback_data=cb("btn", "add_to_row", btn_id)),
        ],
        kb_move_row(                                  # ⬅️⬆️⬇️➡️ — ארבעת הכיוונים
            up_cb=cb("btn", "up",    btn_id),
            down_cb=cb("btn", "down", btn_id),
            left_cb=cb("btn", "left", btn_id),
            right_cb=cb("btn", "right", btn_id),
        ),
        [InlineKeyboardButton(toggle_label,    callback_data=cb("btn", "toggle", btn_id))],
        [InlineKeyboardButton("⚠️ מחק כפתור", callback_data=cb("btn", "delete",  btn_id))],
        [back_button(back_cb, "◀️ חזור לרשימת כפתורים")],
    ]
    return InlineKeyboardMarkup(rows)


def kb_button_type_change(btn_id: int) -> InlineKeyboardMarkup:
    """בחירת סוג חדש לכפתור קיים (עדכון, לא יצירה) — כל סוג בשורה עצמאית."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(label, callback_data=cb("btn", "apply_type", btype, btn_id))]
        for btype, label in BUTTON_TYPES.items()
    ]
    rows.append([cancel_button(cb("btn", "view", btn_id), "✖️ ביטול")])
    return InlineKeyboardMarkup(rows)


def kb_select_target_page(pages: list, btn_id: int) -> InlineKeyboardMarkup:
    """בחירת עמוד יעד לכפתור page_link — כל עמוד בשורה עצמאית."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(page["title"], callback_data=cb("btn", "set_target", btn_id, page["id"]))]
        for page in pages
    ]
    rows.append([cancel_button(cb("btn", "view", btn_id), "✖️ ביטול")])
    return InlineKeyboardMarkup(rows)


def kb_wait_input(back_cb: str) -> InlineKeyboardMarkup:
    """
    מקלדת סטנדרטית לכל מצב 'ממתין לקלט':
    כפתור ביטול אחד שחוזר אחורה.
    """
    return kb_cancel(back_cb)

