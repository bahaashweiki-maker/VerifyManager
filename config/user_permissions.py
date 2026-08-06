"""
config/user_permissions.py
─────────────────────────────────────────────────────────────────────────────
הרשאות משתמשים מאומתים — נפרד לחלוטין מהרשאות מנהלים.

כלל:
    * קובץ זה = הרשאות מה המשתמש רשאי לעשות (יכולות).
    * config/permissions.py = הרשאות מנהל (גישה לפאנל).
    * לעולם לא לערבב בין השניים.

מפתח:
    כל מפתח מתחיל בקידומת "user." כדי לאפשר הפרדה ברורה בטבלת
    user_permissions — גם אם שתי המערכות חולקות את אותה טבלה.

הוספת הרשאה עתידית:
    הוסף רשומה אחת בלבד לרשימה → היא תופיע אוטומטית במסך ניהול ההרשאות
    של המאומתים. אין צורך לשנות שום קובץ אחר.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

USER_PERMISSIONS: list[dict[str, str]] = [

    # ─── אזור סוחר (כפתורים בפאנל) ─────────────────────────────────────────
    {"key": "user.merchant.start",      "label": "▶️ כפתור: התחל פרסום"},
    {"key": "user.merchant.schedule",   "label": "⏱️ כפתור: תזמון פרסום"},
    {"key": "user.merchant.required",   "label": "🔐 כפתור: חובת הצטרפות"},
    {"key": "user.merchant.channels",   "label": "📡 כפתור: הערוצים שלי"},
    {"key": "user.merchant.publications","label": "🗂️ כפתור: הפרסומים שלי"},
    {"key": "user.merchant.status",     "label": "🛡️ כפתור: סטטוס הרשאות"},
    {"key": "user.publish.multi",       "label": "🧩 פרסומים מרובים במקביל"},

    # ─── מדיה ────────────────────────────────────────────────────────────────
    {"key": "user.media.image",         "label": "🖼 העלאת תמונות"},
    {"key": "user.media.video",         "label": "🎥 העלאת וידאו"},
    {"key": "user.media.animation",     "label": "🌀 העלאת אנימציה"},
    {"key": "user.media.document",      "label": "📄 העלאת מסמך"},
    {"key": "user.media.audio",         "label": "🎵 העלאת אודיו"},

    # ─── תקשורת ──────────────────────────────────────────────────────────────
    {"key": "user.msg.send",            "label": "💬 שליחת הודעות"},
    {"key": "user.msg.reply",           "label": "💭 תגובות"},
    {"key": "user.msg.react",           "label": "❤️ אינטראקציות"},
    {"key": "user.msg.broadcast",       "label": "📣 שידור לעוקבים"},

    # ─── קטלוגים ─────────────────────────────────────────────────────────────
    {"key": "user.catalog.use",         "label": "📂 שימוש בקטלוגים"},
    {"key": "user.catalog.manage",      "label": "🗂 ניהול קטלוג אישי"},

    # ─── קבלת תוכן ───────────────────────────────────────────────────────────
    {"key": "user.receive.publish",     "label": "📢 קבלת פרסומים"},
    {"key": "user.receive.newsletter",  "label": "📬 קבלת ניוזלטר"},

    # ─── ביקורות ─────────────────────────────────────────────────────────────
    {"key": "user.review.write",        "label": "⭐ כתיבת ביקורת"},
    {"key": "user.review.reply",        "label": "💬 מענה לביקורת"},

    # ─── חנות ────────────────────────────────────────────────────────────────
    {"key": "user.store.view",          "label": "🛍 צפייה בחנות"},
    {"key": "user.store.sell",          "label": "🛒 מכירה בחנות"},
    {"key": "user.store.manage",        "label": "⚙️ ניהול חנות"},

    # ─── פרופיל ──────────────────────────────────────────────────────────────
    {"key": "user.profile.edit",        "label": "👤 עריכת פרופיל"},
    {"key": "user.profile.verified_badge", "label": "✅ תג מאומת"},

    # ─── מודולים עתידיים ─────────────────────────────────────────────────────
    {"key": "user.future.access",       "label": "🚀 גישה למודולים עתידיים"},
    {"key": "user.future.beta",         "label": "🧪 גישה לפיצ'רים בבטא"},
]

# מפתחות בלבד — לשימוש נוח בבדיקות ובשירותים
USER_PERMISSION_KEYS: frozenset[str] = frozenset(p["key"] for p in USER_PERMISSIONS)
