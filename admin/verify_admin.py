from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.verify_admin_service import (
    get_pending_verifications,
    get_approved_verifications,
    get_rejected_verifications,
    get_blocked_verifications,
    get_verification_by_id,
    approve_verification,
    reject_verification,
    block_verification,
    delete_verification,
    get_verification_stats,
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
        
    # ======================================
    # משתמשים מאומתים
    # ======================================
    if data == "VERIFY_APPROVED":

        verifications = get_approved_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין משתמשים מאומתים."
            )
            return

        first_verify = verifications[0]

        data = f"OPEN_VERIFY_{first_verify['id']}"
    # ======================================
    # אימותים שנדחו
    # ======================================
    if data == "VERIFY_REJECTED":

        verifications = get_rejected_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין אימותים שנדחו."
            )
            return

        first_verify = verifications[0]

        data = f"OPEN_VERIFY_{first_verify['id']}"
        
            # ======================================
    # משתמשים חסומים
    # ======================================
    if data == "VERIFY_BLOCKED":

        verifications = get_blocked_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין משתמשים חסומים."
            )
            return

        first_verify = verifications[0]

        data = f"OPEN_VERIFY_{first_verify['id']}" 
    # ======================================
    # פתיחת אימות בודד
    # ======================================
    if data.startswith("OPEN_VERIFY_"):
        
        print("CALLBACK DATA =", data)
        verification_id = int(data.split("_")[-1])
        print("VERIFICATION ID =", verification_id)
        verify = get_verification_by_id(verification_id)
        
        
        if verify["status"] == "pending":
           verifications = get_pending_verifications()

        elif verify["status"] == "approved":
            verifications = get_approved_verifications()

        elif verify["status"] == "rejected":
            verifications = get_rejected_verifications()

        elif verify["status"] == "blocked":
            verifications = get_blocked_verifications()

        else:
            verifications = []

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
    # אשר אימות
    # ======================================
    if data.startswith("VERIFY_APPROVE_"):

        verification_id = int(data.split("_")[-1])

        approve_verification(verification_id)

        verify = get_verification_by_id(verification_id)

        await context.bot.send_message(
            chat_id=verify["telegram_id"],
            text=(
                "🎉 האימות שלך אושר בהצלחה!\n\n"
                "כעת החשבון שלך מאומת וניתן להשתמש בכל שירותי המערכת.\n\n"
                "תודה שבחרת בנו 🦋"
            )
        )

        await query.answer(
            "✅ האימות אושר בהצלחה.",
            show_alert=True
        )

        return

        # ======================================
        # דחה אימות (placeholder)
        # ======================================
        if data.startswith("VERIFY_REJECT_"):
            await query.answer("❌ בקרוב.", show_alert=True)
            return
            
            # ======================================
    # דחה אימות
    # ======================================
    if data.startswith("VERIFY_REJECT_"):

        verification_id = int(data.split("_")[-1])

        reject_verification(verification_id)

        verify = get_verification_by_id(verification_id)

        await context.bot.send_message(
            chat_id=verify["telegram_id"],
            text=(
                "❌ האימות שלך נדחה.\n\n"
                "ניתן להגיש אימות חדש עם מסמכים ברורים יותר.\n\n"
                "תודה שבחרת בנו 🦋"
            )
        )

        await query.answer(
            "❌ האימות נדחה.",
            show_alert=True
        )

        return
           
        # ======================================
        # חסום משתמש
        # ======================================
    if data.startswith("VERIFY_BLOCK_"):

            verification_id = int(data.split("_")[-1])

            block_verification(verification_id)

            verify = get_verification_by_id(verification_id)

            await context.bot.send_message(
                chat_id=verify["telegram_id"],
                text=(
                    "🚫 החשבון שלך נחסם.\n\n"
                    "לא ניתן להשתמש במערכת בשלב זה.\n\n"
                    "אם לדעתך מדובר בטעות, ניתן ליצור קשר עם הנהלת המערכת.\n\n"
                    "תודה שבחרת בנו 🦋"
                )
            )

            await query.answer(
                "🚫 המשתמש נחסם.",
                show_alert=True
            )

            return
            
    # ======================================
    # שלח הודעה
    # ======================================
    if data.startswith("VERIFY_MESSAGE_"):

        verification_id = int(data.split("_")[-1])

        context.user_data["message_verification_id"] = verification_id

        await query.message.reply_text(
            "✍️ כתוב עכשיו את ההודעה שברצונך לשלוח למשתמש."
        )

        return

    # ======================================
    # מחק אימות
    # ======================================
    if data.startswith("VERIFY_DELETE_"):

        verification_id = int(data.split("_")[-1])

        verify = get_verification_by_id(verification_id)

        delete_verification(verification_id)
        
        
        await query.answer(
            "🗑 האימות נמחק.",
            show_alert=True
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
