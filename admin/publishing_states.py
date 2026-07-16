"""
admin/publishing_states.py
----------------------------
קבועי states ל-ConversationHandler של מודול הפרסום + helpers לבניית callback_data.

ייבוא:
    from admin.publishing_states import (
        PUB_STATES, cb, parse_cb,
        S_HOME_EDIT_TEXT, S_HOME_EDIT_IMAGE, ...
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Prefix אחיד לכל callback_data של המודול
# ---------------------------------------------------------------------------

_PREFIX = "pub"


def cb(*parts: str | int) -> str:
    """
    בונה callback_data עם prefix 'pub:'.

    דוגמאות:
        cb("main")              -> "pub:main"
        cb("page", "edit", 7)  -> "pub:page:edit:7"
    """
    return _PREFIX + ":" + ":".join(str(p) for p in parts)


def parse_cb(data: str) -> list[str]:
    """
    מפרק callback_data לרכיביו (ללא ה-prefix).

    דוגמה:
        parse_cb("pub:page:edit:7") -> ["page", "edit", "7"]
    """
    parts = data.split(":")
    # מסיר את ה-prefix הראשון
    return parts[1:] if parts[0] == _PREFIX else parts


# ---------------------------------------------------------------------------
# States — 17 מצבים
# ---------------------------------------------------------------------------

# --- דף הבית ---
S_HOME_MENU          = 0   # תפריט עריכת דף הבית
S_HOME_WAIT_IMAGE    = 1   # ממתין לתמונה חדשה
S_HOME_WAIT_TEXT     = 2   # ממתין לטקסט חדש

# --- עמודים ---
S_PAGES_LIST         = 3   # רשימת עמודים (עם parent_id נוכחי)
S_PAGE_VIEW          = 4   # תצוגת עמוד יחיד
S_PAGE_WAIT_TITLE    = 5   # ממתין לשם עמוד חדש / ערוך
S_PAGE_WAIT_IMAGE    = 6   # ממתין לתמונה לעמוד
S_PAGE_WAIT_TEXT     = 7   # ממתין לטקסט לעמוד

# --- כפתורים ---
S_BTN_LIST           = 8   # רשימת כפתורים לעמוד / דף בית
S_BTN_VIEW           = 9   # תצוגת כפתור יחיד
S_BTN_WAIT_LABEL     = 10  # ממתין לתווית כפתור
S_BTN_WAIT_VALUE     = 11  # ממתין לערך הכפתור (URL / טקסט / ...)
S_BTN_SELECT_TYPE    = 12  # בחירת סוג כפתור
S_BTN_SELECT_PAGE    = 13  # בחירת עמוד יעד (לכפתור page_link)

# --- כללי ---
S_CONFIRM_DELETE     = 14  # אישור מחיקה
S_SELECT_PARENT      = 15  # בחירת עמוד-אב
S_MAIN_MENU          = 16  # תפריט ראשי של מודול הפרסום

# מילון נוחות לשימוש ב-ConversationHandler
PUB_STATES: dict[int, list] = {
    state: [] for state in range(17)
}


# ---------------------------------------------------------------------------
# סוגי כפתורים חוקיים
# ---------------------------------------------------------------------------

BUTTON_TYPES: dict[str, str] = {
    "text":      "📝 הודעת טקסט",
    "url":       "🔗 קישור חיצוני",
    "page_link": "📄 ניווט לעמוד",
    "phone":     "📞 מספר טלפון",
    "email":     "📧 כתובת מייל",
    "location":  "📍 מיקום",
    "share":     "🔁 שיתוף הבוט",
}

BUTTON_TYPE_LABELS = list(BUTTON_TYPES.keys())