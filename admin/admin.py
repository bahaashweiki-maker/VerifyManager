from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# החלף ל-ID שלך
ADMIN_ID = 1751674910


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ אין לך הרשאה להיכנס למערכת הניהול."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪪 מערכת אימותים", callback_data="ADMIN_VERIFY")],
        [InlineKeyboardButton("📢 פרסומים", callback_data="ADMIN_BROADCAST")],
        [InlineKeyboardButton("👥 משתמשים", callback_data="ADMIN_USERS")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="ADMIN_STATISTICS")],
        [InlineKeyboardButton("⚙️ הגדרות", callback_data="ADMIN_SETTINGS")],
        [InlineKeyboardButton("🚪 יציאה", callback_data="HOME")]
    ])

    await update.message.reply_text(
        "👨‍💼 <b>מערכת ניהול</b>\n\n"
        "ברוך הבא למערכת הניהול.\n\n"
        "בחר את המערכת שברצונך לנהל:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )