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
    # אימותים ממתינים — הצגת רשימה
    # ======================================
    if data == "VERIFY_PENDING":

        verifications = get_pending_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין כרגע אימותים ממתינים."
            )
            return

        # [תיקון ניווט] שמירת מקור הניווט כדי שכפתור "חזרה" יחזיר לרשימה הנכונה
        context.user_data["verify_source"] = "VERIFY_PENDING"

        buttons = []
        for v in verifications:
            label = f"👤 {v['full_name'] or v['username'] or 'משתמש לא ידוע'} (#{v['id']})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"OPEN_VERIFY_{v['id']}")])

        buttons.append([InlineKeyboardButton("🏠 חזרה למערכת הניהול", callback_data="ADMIN_HOME")])

        keyboard = InlineKeyboardMarkup(buttons)

        await query.edit_message_text(
            text=f"⏳ <b>אימותים ממתינים</b> ({len(verifications)})\n\nבחר אימות לצפייה:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    # ======================================
    # משתמשים מאומתים — הצגת רשימה
    # ======================================
    if data == "VERIFY_APPROVED":

        verifications = get_approved_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין משתמשים מאומתים."
            )
            return

        # [תיקון ניווט] שמירת מקור הניווט כדי שכפתור "חזרה" יחזיר לרשימה הנכונה
        context.user_data["verify_source"] = "VERIFY_APPROVED"

        buttons = []
        for v in verifications:
            label = f"👤 {v['full_name'] or v['username'] or 'משתמש לא ידוע'} (#{v['id']})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"OPEN_VERIFY_{v['id']}")])

        buttons.append([InlineKeyboardButton("🏠 חזרה למערכת הניהול", callback_data="ADMIN_HOME")])

        keyboard = InlineKeyboardMarkup(buttons)

        await query.edit_message_text(
            text=f"✅ <b>משתמשים מאומתים</b> ({len(verifications)})\n\nבחר אימות לצפייה:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    # ======================================
    # אימותים שנדחו — הצגת רשימה
    # ======================================
    if data == "VERIFY_REJECTED":

        verifications = get_rejected_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין אימותים שנדחו."
            )
            return

        # [תיקון ניווט] שמירת מקור הניווט כדי שכפתור "חזרה" יחזיר לרשימה הנכונה
        context.user_data["verify_source"] = "VERIFY_REJECTED"

        buttons = []
        for v in verifications:
            label = f"👤 {v['full_name'] or v['username'] or 'משתמש לא ידוע'} (#{v['id']})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"OPEN_VERIFY_{v['id']}")])

        buttons.append([InlineKeyboardButton("🏠 חזרה למערכת הניהול", callback_data="ADMIN_HOME")])

        keyboard = InlineKeyboardMarkup(buttons)

        await query.edit_message_text(
            text=f"❌ <b>אימותים שנדחו</b> ({len(verifications)})\n\nבחר אימות לצפייה:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    # ======================================
    # משתמשים חסומים — הצגת רשימה
    # ======================================
    if data == "VERIFY_BLOCKED":

        verifications = get_blocked_verifications()

        if not verifications:
            await query.edit_message_text(
                "📭 אין משתמשים חסומים."
            )
            return

        # [תיקון ניווט] שמירת מקור הניווט כדי שכפתור "חזרה" יחזיר לרשימה הנכונה
        context.user_data["verify_source"] = "VERIFY_BLOCKED"

        buttons = []
        for v in verifications:
            label = f"👤 {v['full_name'] or v['username'] or 'משתמש לא ידוע'} (#{v['id']})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"OPEN_VERIFY_{v['id']}")])

        buttons.append([InlineKeyboardButton("🏠 חזרה למערכת הניהול", callback_data="ADMIN_HOME")])

        keyboard = InlineKeyboardMarkup(buttons)

        await query.edit_message_text(
            text=f"🚫 <b>משתמשים חסומים</b> ({len(verifications)})\n\nבחר אימות לצפייה:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    # ======================================
    # פתיחת אימות בודד
    # ======================================
    if data.startswith("OPEN_VERIFY_"):
        
        
        verification_id = int(data.split("_")[-1])
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
        
        if not verify:
            await query.edit_message_text("⚠️ האימות לא נמצא.")
            return

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

        # [תיקון ניווט] קריאת מקור הניווט מ-context.user_data
        # נשמר בעת לחיצה על VERIFY_PENDING / VERIFY_APPROVED / VERIFY_REJECTED / VERIFY_BLOCKED
        # כך כפתור "חזרה" תמיד חוזר לרשימה הנכונה, ולא תמיד ל-VERIFY_PENDING
        back_target = context.user_data.get("verify_source", "VERIFY_PENDING")

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
                # [תיקון ניווט] back_target = הרשימה הנכונה לפי מקור הניווט השמור
                InlineKeyboardButton("⬅️ חזרה לרשימת האימותים", callback_data=back_target),
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
    # סטטיסטיקות אימותים
    # ======================================
    if data == "VERIFY_STATS":

        stats = get_verification_stats()

        total = 0
        pending = 0
        approved = 0
        rejected = 0
        blocked = 0

        for row in stats:
            status = row["status"]
            count = row["total"]

            total += count

            if status == "pending":
                pending = count
            elif status == "approved":
                approved = count
            elif status == "rejected":
                rejected = count
            elif status == "blocked":
                blocked = count

        text = (
            "📊 <b>סטטיסטיקת אימותים</b>\n\n"
            f"👥 סך הכול אימותים: <b>{total}</b>\n\n"
            f"⏳ ממתינים: <b>{pending}</b>\n"
            f"✅ מאומתים: <b>{approved}</b>\n"
            f"❌ נדחו: <b>{rejected}</b>\n"
            f"🚫 חסומים: <b>{blocked}</b>"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ חזרה למערכת ניהול האימותים",
                    callback_data="ADMIN_VERIFY"
                )
            ]
        ])

        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        return
    # ======================================
    # חזרה למערכת הניהול
    # ======================================
    if data == "ADMIN_HOME":
        from admin.admin import admin_panel
        await admin_panel(update, context)
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