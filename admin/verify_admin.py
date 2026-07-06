from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.verify_admin_service import (
    get_pending_verifications,
)


async def verify_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    # ======================================
    # אימותים ממתינים
    # ======================================
    if data == "VERIFY_PENDING":

        verifications = get_pending_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין כרגע אימותים ממתינים."
            )
            return

        keyboard = []

        text = "⏳ <b>אימותים ממתינים</b>\n\n"

        for verify in verifications:

            verification_id = verify[0]
            telegram_id = verify[1]
            status = verify[6]

            text += (
                f"🆔 אימות #{verification_id}\n"
                f"👤 {telegram_id}\n"
                f"📌 {status}\n\n"
            )

            keyboard.append([
                InlineKeyboardButton(
                    f"🔍 פתח אימות #{verification_id}",
                    callback_data=f"OPEN_VERIFY_{verification_id}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "⬅️ חזרה",
                callback_data="ADMIN_VERIFY"
            )
        ])

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

        return

    # ======================================
    # תפריט ראשי
    # ======================================

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏳ אימותים ממתינים", callback_data="VERIFY_PENDING")],
        [InlineKeyboardButton("✅ משתמשים מאומתים", callback_data="VERIFY_APPROVED")],
        [InlineKeyboardButton("❌ אימותים שנדחו", callback_data="VERIFY_REJECTED")],
        [InlineKeyboardButton("🚫 משתמשים חסומים", callback_data="VERIFY_BLOCKED")],
        [InlineKeyboardButton("📊 סטטיסטיקת אימותים", callback_data="VERIFY_STATS")],
        [InlineKeyboardButton("🏠 חזרה למערכת הניהול", callback_data="ADMIN_HOME")]
    ])

    await query.edit_message_text(
        text=(
            "🪪 <b>מערכת ניהול אימותים</b>\n\n"
            "ברוכים הבאים למערכת ניהול האימותים.\n\n"
            "בחר פעולה:"
        ),
        reply_markup=keyboard,
        parse_mode="HTML"
    )