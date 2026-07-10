from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.verify_admin_service import (
    get_pending_verifications,
    get_verification_by_id,
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

            verification_id = verify["id"]
            telegram_id = verify["telegram_id"]
            status = verify["status"]

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
    # פתיחת אימות בודד
    # ======================================
    if data.startswith("OPEN_VERIFY_"):
        
        print("CALLBACK DATA =", data)
        verification_id = int(data.split("_")[-1])
        print("VERIFICATION ID =", verification_id)
        verify = get_verification_by_id(verification_id)
        print("VERIFY =", verify)
        
        print("VERIFY ID =", verify["id"])
        print("VERIFY STATUS =", verify["status"])

        if not verify:
            await query.edit_message_text("⚠️ האימות לא נמצא.")
            return
        print("REACHED TEXT")

        text = (
            f"🔍 <b>פרטי אימות #{verify['id']}</b>\n\n"
            f"👤 Telegram ID: <code>{verify['telegram_id']}</code>\n"
            f"🔗 רשת חברתית: {verify['social'] or '—'}\n"
            f"🔑 קוד: {verify['code'] or '—'}\n"
            f"📌 סטטוס: {verify['status']}\n"
            f"🕐 נוצר: {verify['created_at']}\n"
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
    # הצגת תעודת זהות
    # ======================================
    if data.startswith("VIEW_ID_"):

        verification_id = int(data.split("_")[-1])
        verify = get_verification_by_id(verification_id)

        if not verify or not verify["id_photo"]:
            await query.answer("⚠️ אין תמונת תעודת זהות.", show_alert=True)
            return

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=verify["id_photo"],
            caption="🪪 תמונת תעודת זהות"
        )

        return
    # ======================================
    # הצגת צילום מסך רשת חברתית
    # ======================================
    if data.startswith("VIEW_SOCIAL_"):

        verification_id = int(data.split("_")[-1])
        verify = get_verification_by_id(verification_id)

        if not verify or not verify.get("social"):
            await query.answer("⚠️ אין צילום מסך.", show_alert=True)
            return

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=verify["social"],
            caption="📱 צילום מסך רשת חברתית"
        )

        return

    # ======================================
    # הצגת סלפי
    # ======================================
    if data.startswith("VIEW_SELFIE_"):

        verification_id = int(data.split("_")[-1])
        verify = get_verification_by_id(verification_id)

        if not verify or not verify["selfie"]:
            await query.answer("⚠️ אין תמונת סלפי.", show_alert=True)
            return

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=verify["selfie"],
            caption="🤳 סלפי"
        )

        return

    # ======================================
    # הצגת סרטון
    # ======================================
    if data.startswith("VIEW_VIDEO_"):

        verification_id = int(data.split("_")[-1])
        verify = get_verification_by_id(verification_id)

        if not verify or not verify["video"]:
            await query.answer("⚠️ אין סרטון.", show_alert=True)
            return

        await context.bot.send_video(
            chat_id=query.message.chat_id,
            video=verify["video"],
            caption="🎥 סרטון"
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
