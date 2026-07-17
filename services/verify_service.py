# services/verify_service.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.engine.page_engine import PageEngine
import random
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from database.database import create_verification
from app.engine.publishing_renderer import render_home
from services.verify_admin_service import get_latest_verification_by_telegram_id

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
    success = await render_home(context.bot, update.callback_query.message.chat_id)
    if not success:
        await PageEngine.show_page(update, context, "HOME")


# -----------------------------
# התחלת אימות – שלב 1
# -----------------------------
async def start_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    is_media_msg = query.message.effective_attachment is not None

    # בדיקה האם למשתמש יש Username
    if not user.username:

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 חזרה", callback_data="pub:user:home")]
        ])

        if is_media_msg:
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                query.message.chat_id,
                "⚠️ *לא ניתן להתחיל את תהליך האימות.*\n\n"
                "כדי להגיש בקשת אימות יש להגדיר *שם משתמש* בטלגרם.\n\n"
                "שם משתמש הוא השם שמתחיל בסימן @.\n\n"
                "לאחר שתגדיר שם משתמש,\n"
                "חזור לבוט ולחץ שוב על *התחל אימות*.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            await query.edit_message_text(
                "⚠️ *לא ניתן להתחיל את תהליך האימות.*\n\n"
                "כדי להגיש בקשת אימות יש להגדיר *שם משתמש* בטלגרם.\n\n"
                "שם משתמש הוא השם שמתחיל בסימן @.\n\n"
                "לאחר שתגדיר שם משתמש,\n"
                "חזור לבוט ולחץ שוב על *התחל אימות*.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        return

    # -------------------------------------------------------
    # בדיקת סטטוס בקשת האימות האחרונה של המשתמש
    # -------------------------------------------------------
    existing = get_latest_verification_by_telegram_id(user_id)
    if existing and existing["status"] in ("pending", "approved", "blocked"):
        _messages = {
            "pending":  "⏳ *בקשת האימות שלך כבר נמצאת בבדיקה.*\n\nנחזור אליך בהקדם האפשרי.\nתודה על סבלנותך 🙏",
            "approved": "✅ *החשבון שלך כבר מאומת.*\n\nאין צורך להגיש בקשה נוספת.",
            "blocked":  "🚫 *החשבון שלך חסום.*\n\nלא ניתן להגיש בקשת אימות.",
        }
        back_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 חזרה", callback_data="pub:user:home")]
        ])
        if is_media_msg:
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                query.message.chat_id,
                _messages[existing["status"]],
                parse_mode="Markdown",
                reply_markup=back_keyboard
            )
        else:
            await query.edit_message_text(
                _messages[existing["status"]],
                parse_mode="Markdown",
                reply_markup=back_keyboard
            )
        return
    # rejected / אין רשומה → ממשיכים לתהליך הרגיל

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
    
    # ניקוי הודעות מחוץ לתהליך האימות
    state = context.user_data.get(user_id)

    if not state:
        try:
            await context.bot.delete_message(chat_id, update.message.message_id)
        except:
            pass

        warning = await update.message.reply_text(
            "⚠️ הבוט פועל באמצעות הכפתורים בלבד."
        )

        await asyncio.sleep(2)

        try:
            await context.bot.delete_message(chat_id, warning.message_id)
        except:
            pass

        return
    
    # =====================================
    # הודעה מהמנהל למשתמש
    # =====================================
    if (
        user_id == ADMIN_CHAT_ID
        and "message_verification_id" in context.user_data
        and update.message.text
    ):

        verification_id = context.user_data.pop("message_verification_id")

        from services.verify_admin_service import get_verification_by_id

        verify = get_verification_by_id(verification_id)

        if verify:

            await context.bot.send_message(
                chat_id=verify["telegram_id"],
                text=(
                "🦋 התקבלה הודעה מצוות הבוט\n"
                    "────────────────────\n"
                    f"{update.message.text}"
                  )
                )

            await update.message.reply_text(
                "✅ ההודעה נשלחה למשתמש."
            )

        else:
            await update.message.reply_text(
                "❌ האימות לא נמצא."
            )
        context.user_data.pop(user_id, None)
        return

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
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except:
                pass
            err = await context.bot.send_message(chat_id, "❌ עליך לשלוח *תמונה בלבד*.", parse_mode="Markdown")
            await asyncio.sleep(2)
            try:
                await context.bot.delete_message(chat_id, err.message_id)
            except:
                pass
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
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except:
                pass
            err = await context.bot.send_message(chat_id, "❌ עליך לשלוח *תמונה בלבד*.", parse_mode="Markdown")
            await asyncio.sleep(2)
            try:
                await context.bot.delete_message(chat_id, err.message_id)
            except:
                pass
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
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except:
                pass
            err = await context.bot.send_message(chat_id, "❌ עליך לשלוח *תמונה בלבד*.", parse_mode="Markdown")
            await asyncio.sleep(2)
            try:
                await context.bot.delete_message(chat_id, err.message_id)
            except:
                pass
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
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except:
                pass
            err = await context.bot.send_message(chat_id, "❌ עליך לשלוח *סרטון עגול* בלבד.", parse_mode="Markdown")
            await asyncio.sleep(2)
            try:
                await context.bot.delete_message(chat_id, err.message_id)
            except:
                pass
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
    
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    print(now)
    print(now.tzinfo)
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
