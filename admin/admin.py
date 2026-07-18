"""
admin/admin.py
─────────────────────────────────────────────────────────────────────────────
פאנל הניהול הראשי.

הכפתורים נוצרים אוטומטית מ-config/permissions.py → ADMIN_MODULES.
להוסיף מודול חדש: הוסף רשומה ל-ADMIN_MODULES בלבד — אין לגעת בקובץ זה.
─────────────────────────────────────────────────────────────────────────────
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config.permissions import ADMIN_MODULES
from services.admin_service import is_super_admin
from services.permission_service import has_permission

# מיוצא — נדרש ע"י admin_service
ADMIN_ID = 1751674910


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    user = update.effective_user
    uid  = user.id

    # בדיקת הרשאת כניסה בסיסית
    if not is_super_admin(uid) and not has_permission(uid, "admin"):
        if update.callback_query:
            await update.callback_query.answer("⛔ אין לך הרשאה.", show_alert=True)
        else:
            await update.message.reply_text("⛔ אין לך הרשאה להיכנס למערכת הניהול.")
        return

    is_super = is_super_admin(uid)

    # ── בניית כפתורים אוטומטית מ-ADMIN_MODULES ───────────────────────────────
    rows = []

    # ניהול מנהלים — רק סופר-אדמין, תמיד ראשון
    if is_super:
        rows.append([InlineKeyboardButton("👑 ניהול מנהלים", callback_data="ADMIN_MANAGERS")])

    # מודולים לפי הגדרה ב-config/permissions.py
    for module in ADMIN_MODULES:
        # is_super → גישה לכל. אחרת: מספיק הרשאה אחת מ-requires
        if is_super or any(has_permission(uid, r) for r in module["requires"]):
            rows.append([InlineKeyboardButton(module["label"], callback_data=module["callback"])])

    rows.append([InlineKeyboardButton("🚪 יציאה", callback_data="pub:user:home")])

    keyboard = InlineKeyboardMarkup(rows)
    text = (
        "👨‍💼 <b>מערכת ניהול</b>\n\n"
        "ברוך הבא למערכת הניהול.\n\n"
        "בחר את המערכת שברצונך לנהל:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    try:
        await update.message.delete()
    except Exception:
        pass

    await update.message.reply_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
