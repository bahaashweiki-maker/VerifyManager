"""
admin/admin.py
─────────────────────────────────────────────────────────────────────────────
פאנל ניהול ראשי — VerifyManager

ADMIN_ID מיובא מ-config/constants.py (לא מוגדר כאן) כדי למנוע Circular Import.
─────────────────────────────────────────────────────────────────────────────
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config.constants import ADMIN_ID
from services.admin_service import is_super_admin
from services.permission_service import has_permission


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    uid  = user.id

    if not is_super_admin(uid) and not has_permission(uid, "admin"):
        if update.callback_query:
            await update.callback_query.answer("⛔ אין לך הרשאה.", show_alert=True)
        else:
            await update.message.reply_text("⛔ אין לך הרשאה להיכנס למערכת הניהול.")
        return

    rows = [
        [InlineKeyboardButton("🪪 מערכת אימותים",  callback_data="ADMIN_VERIFY")],
    ]
    if is_super_admin(uid):
        rows.append([InlineKeyboardButton("👑 ניהול מנהלים", callback_data="ADMIN_MANAGERS")])
    rows += [
        [InlineKeyboardButton("📋 ניהול פרסומים",  callback_data="pub:main")],
        [InlineKeyboardButton("📢 פרסומים",         callback_data="ADMIN_BROADCAST")],
        [InlineKeyboardButton("👥 משתמשים",         callback_data="ADMIN_USERS")],
        [InlineKeyboardButton("📊 סטטיסטיקות",      callback_data="ADMIN_STATISTICS")],
        [InlineKeyboardButton("⚙️ הגדרות",          callback_data="ADMIN_SETTINGS")],
        [InlineKeyboardButton("🚪 יציאה",           callback_data="pub:user:home")],
    ]

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