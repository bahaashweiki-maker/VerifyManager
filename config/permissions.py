"""
config/permissions.py
─────────────────────────────────────────────────────────────────────────────
רשימת ההרשאות הידועות במערכת — VerifyManager

PERMISSIONS משמש את admin/admin_manager.py להצגת מסך הרשאות גרפי.
כל הרשאה היא dict עם שני שדות:
    key   — המחרוזת שנשמרת ב-DB ומועברת ל-has_permission()
    label — הטקסט שמוצג למנהל בממשק הגרפי

הוספת הרשאה חדשה: הוסף dict לרשימה בלבד. אין צורך לשנות קוד אחר.
─────────────────────────────────────────────────────────────────────────────
"""

PERMISSIONS: list[dict] = [
    {"key": "admin",          "label": "👨‍💼 גישה לפאנל ניהול"},
    {"key": "verify.review",  "label": "🪪 ניהול אימותים"},
    {"key": "publish.manage", "label": "📋 ניהול פרסומים"},
    {"key": "broadcast.send", "label": "📢 שליחת פרסומים"},
    {"key": "users.manage",   "label": "👥 ניהול משתמשים"},
    {"key": "stats.view",     "label": "📊 צפייה בסטטיסטיקות"},
    {"key": "settings.edit",  "label": "⚙️ עריכת הגדרות"},
]