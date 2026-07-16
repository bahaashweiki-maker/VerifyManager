from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# החלף ל-ID שלך
ADMIN_ID = 1751674910


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if user.id != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer(
                "⛔ אין לך הרשאה.",
                show_alert=True
            )
        else:
            await update.message.reply_text(
                "⛔ אין לך הרשאה להיכנס למערכת הניהול."
            )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪪 מערכת אימותים",  callback_data="ADMIN_VERIFY")],
        [InlineKeyboardButton("📋 ניהול פרסומים",   callback_data="pub:main")],
        [InlineKeyboardButton("📢 פרסומים",         callback_data="ADMIN_BROADCAST")],
        [InlineKeyboardButton("👥 משתמשים",         callback_data="ADMIN_USERS")],
        [InlineKeyboardButton("📊 סטטיסטיקות",      callback_data="ADMIN_STATISTICS")],
        [InlineKeyboardButton("⚙️ הגדרות",           callback_data="ADMIN_SETTINGS")],
        [InlineKeyboardButton("🚪 יציאה",            callback_data="pub:user:home")],
    ])

    text = (
        "👨‍💼 <b>מערכת ניהול</b>\n\n"
        "ברוך הבא למערכת הניהול.\n\n"
        "בחר את המערכת שברצונך לנהל:"
    )

    # תמיד delete + send — עקבי עם publishing_renderer ומונע קריסה
    # כשההודעה הקודמת הייתה תמונה (edit_message_text נכשל על הודעות מדיה).
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        try:
            await update.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )