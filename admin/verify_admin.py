from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.verify_admin_service import (
    get_pending_verifications,
    get_verification_by_id,
    get_verification_index,
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

        first_verify = verifications[0]
        
        data = f"OPEN_VERIFY_{first_verify['id']}"

       
        # ממשיך ישר לפתיחת האימות הראשון
        verify = first_verify
        verification_id = verify["id"]
        print("AUTO OPEN =", verification_id) 
    # ======================================
    # פתיחת אימות בודד
    # ======================================
    if data.startswith("OPEN_VERIFY_"):
        
        print("CALLBACK DATA =", data)
        verification_id = int(data.split("_")[-1])
        print("VERIFICATION ID =", verification_id)
        verify = get_verification_by_id(verification_id)
        
        
        verifications = get_pending_verifications()
        current_index = get_verification_index(verifications, verification_id)
        total = len(verifications)

        print(current_index, "/", total)
                
    
        print(verify.keys())
        print("VERIFY =", verify)
        
        print("VERIFY ID =", verify["id"])
        print("VERIFY STATUS =", verify["status"])

        if not verify:
            await query.edit_message_text("⚠️ האימות לא נמצא.")
            return
        print("REACHED TEXT")

        text = (
    f"📄 <b>אימות {current_index + 1} מתוך {total}</b>\n"
    f"🔎 <b>פרטי אימות #{verify['id']}</b>\n\n"
    
    f"🆔 <b>Telegram ID:</b> <code>{verify['telegram_id']}</code>\n\n"
    f"👤 <b>שם מלא:</b> {verify['full_name'] or '-'}\n"
    f"🔗 <b>Username:</b> @{verify['username'] or '-'}\n\n"
    f"🆔 <b>מספר אימות:</b> <code>{verify['id']}</code>\n\n"

    f"📅 <b>תאריך:</b> {verify['created_at'][:10]}\n"
    f"🕒 <b>שעה:</b> {verify['created_at'][11:19]}\n\n"

    f"🔑 <b>קוד אימות:</b> {verify['code'] or '-'}\n"
    f"📌 <b>סטטוס:</b> {verify['status']}"
)

        vid = verify["id"]

        keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🪪 תעודת זהות", callback_data=f"VIEW_ID_{vid}"),
                    InlineKeyboardButton("🤳 סלפי", callback_data=f"VIEW_SELFIE_{vid}"),
                ],
                [
                    InlineKeyboardButton("📱 צילום מסך", callback_data=f"VIEW_SOCIAL_{vid}"),
                    InlineKeyboardButton("🎥 סרטון", callback_data=f"VIEW_VIDEO_{vid}"),
                ],
            [
                InlineKeyboardButton("✅ אשר אימות",  callback_data=f"VERIFY_APPROVE_{vid}"),
                InlineKeyboardButton("❌ דחה אימות",  callback_data=f"VERIFY_REJECT_{vid}"),
                InlineKeyboardButton("🚫 חסום משתמש", callback_data=f"VERIFY_BLOCK_{vid}"),
            ],
            [
                InlineKeyboardButton("💬 שלח הודעה", callback_data=f"VERIFY_MESSAGE_{vid}"),
                InlineKeyboardButton("🗑 מחק אימות",  callback_data=f"VERIFY_DELETE_{vid}"),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ הקודם",
                    callback_data=f"OPEN_VERIFY_{verifications[current_index - 1]['id']}"
                ) if current_index > 0 else InlineKeyboardButton(" ", callback_data="IGNORE"),

                InlineKeyboardButton(
                    "➡️ הבא",
                    callback_data=f"OPEN_VERIFY_{verifications[current_index + 1]['id']}"
                ) if current_index < total - 1 else InlineKeyboardButton(" ", callback_data="IGNORE"),
            ],
            [
                InlineKeyboardButton("⬅️ חזרה לרשימת האימותים", callback_data="VERIFY_PENDING"),
            ],
        ])

        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        return

    
    # ======================================
    # אשר אימות (placeholder)
    # ======================================
    if data.startswith("VERIFY_APPROVE_"):
        await query.answer("✅ בקרוב.", show_alert=True)
        return

    # ======================================
    # דחה אימות (placeholder)
    # ======================================
    if data.startswith("VERIFY_REJECT_"):
        await query.answer("❌ בקרוב.", show_alert=True)
        return

    # ======================================
    # חסום משתמש (placeholder)
    # ======================================
    if data.startswith("VERIFY_BLOCK_"):
        await query.answer("🚫 בקרוב.", show_alert=True)
        return

    # ======================================
    # שלח הודעה (placeholder)
    # ======================================
    if data.startswith("VERIFY_MESSAGE_"):
        await query.answer("💬 בקרוב.", show_alert=True)
        return

    # ======================================
    # מחק אימות (placeholder)
    # ======================================
    if data.startswith("VERIFY_DELETE_"):
        await query.answer("🗑 בקרוב.", show_alert=True)
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
