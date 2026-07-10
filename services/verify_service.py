# services/verify_service.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.engine.page_engine import PageEngine
import random
from datetime import datetime
from database.database import create_verification

ADMIN_CHAT_ID = 1751674910   # לשנות למזהה המנהל


# -----------------------------
# תפריט הבית (חובה כדי שהביטול יעבוד)
# -----------------------------
async def show_home_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 התחלת אימות", callback_data="START_VERIFY")],
        [InlineKeyboardButton("ℹ️ מידע", callback_data="INFO")]
    ])

    # אם הביטול הגיע מכפתור
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "🏠 חזרת לדף הבית.\nבחר פעולה:",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            "🏠 חזרת לדף הבית.\nבחר פעולה:",
            reply_markup=keyboard
        )


# -----------------------------
# כפתור ביטול
# -----------------------------
def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ביטול אימות", callback_data="CANCEL_VERIFY")]
    ])


# -----------------------------
# ביטול תהליך האימות
# -----------------------------
async def cancel_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.callback_query.from_user
    user_id = user.id

    # מחיקת סטטוס האימות
    context.user_data.pop(user_id, None)

    # מחיקת הודעת האימות עצמה
    try:
        await context.bot.delete_message(
            update.callback_query.message.chat_id,
            update.callback_query.message.message_id
        )
    except:
        pass

    # חזרה לדף הבית
    await PageEngine.show_page(update, context, "HOME")


# -----------------------------
# התחלת אימות – שלב 1
# -----------------------------
async def start_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id

    verify_code = random.randint(1000, 9999)

    context.user_data[user_id] = {
        "step": 1,
        "media": {},
        "verify_code": verify_code,
        "last_bot_msg": None
    }
      
     
    text = (
        "💠 *לקוח יקר,*\n\n"
        "התחלנו את תהליך האימות שלך.\n\n"
        "📸 *שלב 1 מתוך 4*\n"
        "נא שלח *תמונה ברורה* של אמצעי הזיהוי שלך:\n"
        "• תעודת זהות\n"
        "• דרכון\n"
        "• רישיון נהיגה\n\n"
        "⚠️ יש לשלוח *תמונה בלבד*."
    )

    msg = await query.message.reply_text(text, parse_mode="Markdown", reply_markup=cancel_keyboard())
    context.user_data[user_id]["last_bot_msg"] = msg.message_id


# -----------------------------
# תהליך האימות – כל השלבים
# -----------------------------
async def process_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    chat_id = update.message.chat_id

    state = context.user_data.get(user_id)
    if not state:
        await update.message.reply_text("❗ לא התחלת תהליך אימות.")
        return

    step = state["step"]
    last_bot_msg = state["last_bot_msg"]

    # מחיקת הודעות
    async def cleanup():
        try:
            await context.bot.delete_message(chat_id, update.message.message_id)
        except:
            pass
        try:
            await context.bot.delete_message(chat_id, last_bot_msg)
        except:
            pass

    # -----------------------------
    # שלב 1 – תמונת תעודה
    # -----------------------------
    if step == 1:
        if not update.message.photo:
            await update.message.reply_text("❌ עליך לשלוח *תמונה בלבד*.", parse_mode="Markdown")
            return

        state["media"]["id_photo"] = update.message.photo[-1].file_id
        await cleanup()

        msg = await context.bot.send_message(
            chat_id,
            "✔️ התמונה התקבלה.\n\n"
            "📸 *שלב 2 מתוך 4*\n"
            "נא שלח צילום מסך של Facebook או Instagram שלך.",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        state["step"] = 2
        state["last_bot_msg"] = msg.message_id
        return

    # -----------------------------
    # שלב 2 – צילום מסך
    # -----------------------------
    if step == 2:
        if not update.message.photo:
            await update.message.reply_text("❌ עליך לשלוח *תמונה בלבד*.", parse_mode="Markdown")
            return

        state["media"]["social"] = update.message.photo[-1].file_id
        await cleanup()

        msg = await context.bot.send_message(
            chat_id,
            "✔️ התמונה התקבלה.\n\n"
            "🤳 *שלב 3 מתוך 4*\n"
            "נא שלח תמונת סלפי ברורה שלך.",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        state["step"] = 3
        state["last_bot_msg"] = msg.message_id
        return

    # -----------------------------
    # שלב 3 – סלפי
    # -----------------------------
    if step == 3:
        if not update.message.photo:
            await update.message.reply_text("❌ עליך לשלוח *תמונה בלבד*.", parse_mode="Markdown")
            return

        state["media"]["selfie"] = update.message.photo[-1].file_id
        await cleanup()

        msg = await context.bot.send_message(
            chat_id,
            f"✔️ התמונה התקבלה.\n\n"
            f"🎥 *שלב 4 מתוך 4*\n"
            f"נא שלח סרטון עגול שבו אתה אומר את המספר:\n*{state['verify_code']}*",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        state["step"] = 4
        state["last_bot_msg"] = msg.message_id
        return

    # -----------------------------
    # שלב 4 – סרטון עגול
    # -----------------------------
    if step == 4:
        if not (update.message.video_note or update.message.video):
            await update.message.reply_text("❌ עליך לשלוח *סרטון עגול* בלבד.", parse_mode="Markdown")
            return

        state["media"]["video"] = (
            update.message.video_note.file_id if update.message.video_note else update.message.video.file_id
        )

        await cleanup()

        # הודעה יפה ללקוח
        await context.bot.send_message(
            chat_id,
            "✨ *לקוח יקר,*\n\n"
            "האימות שלך התקבל בהצלחה על ידי צוות הבדיקה שלנו.\n"
            "אנחנו מטפלים בבקשה שלך בעדיפות גבוהה.\n\n"
            "📢 תקבל עדכון ברגע שהאימות יאושר.\n"
            "תודה על שיתוף הפעולה 🙏",
            parse_mode="Markdown"
        )

        # שליחת הכל למנהל
        await send_to_admin(update, context, state)

        state["step"] = "DONE"
        return


# -----------------------------
# שליחת המדיה למנהל
# -----------------------------
async def send_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
    user = update.message.from_user
    user_id = user.id

    # קודם שומרים את האימות במסד
    print("FULL NAME =", user.full_name)
    print("USERNAME =", user.username)
    verification_id = create_verification(
        telegram_id=user_id,
        
        full_name=user.full_name,
        username=user.username,
        id_photo=state["media"]["id_photo"],
        selfie=state["media"]["selfie"],
        social=state["media"]["social"],
        video=state["media"]["video"],
        code=str(state["verify_code"])
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔍 פתח אימות",
                callback_data=f"OPEN_VERIFY_{verification_id}"
            )
        ]
    ])
    
    now = datetime.now()
    text = (
    "🚨 התקבל אימות חדש\n\n"
    f"🪪 מספר אימות: #{verification_id}\n\n"
    f"👤 שם מלא: {user.full_name}\n"
    f"🔗 Username: @{user.username if user.username else 'אין'}\n"
    f"🆔 Telegram ID: {user_id}\n\n"
    f"📅 תאריך: {now.strftime('%d/%m/%Y')}\n"
    f"🕒 שעה: {now.strftime('%H:%M:%S')}\n\n"
    "📌 סטטוס: ממתין לאישור\n\n"
    "👇 לחץ על הכפתור לפתיחת האימות."
)

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=text,
        reply_markup=keyboard
    )