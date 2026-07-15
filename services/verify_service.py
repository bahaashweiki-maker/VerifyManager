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

ADMIN_CHAT_ID = 1751674910


async def _temp_error(
    bot,
    chat_id: int,
    text: str,
    user_msg_id: int | None = None,
    delay: float = 2.0,
) -> None:
    try:
        err_msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        await asyncio.sleep(delay)
        to_delete = [bot.delete_message(chat_id=chat_id, message_id=err_msg.message_id)]
        if user_msg_id:
            to_delete.append(bot.delete_message(chat_id=chat_id, message_id=user_msg_id))
        await asyncio.gather(*to_delete, return_exceptions=True)
    except Exception:
        pass


async def show_home_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 התחלת אימות", callback_data="START_VERIFY")],
        [InlineKeyboardButton("ℹ️ מידע", callback_data="INFO")]
    ])

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


def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ביטול אימות", callback_data="CANCEL_VERIFY")]
    ])


async def cancel_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.callback_query.from_user
    user_id = user.id
    chat_id = update.callback_query.message.chat_id

    context.user_data.pop(user_id, None)

    try:
        await update.callback_query.message.delete()
    except Exception:
        pass

    msg_id = await render_home(context.bot, chat_id)
    if msg_id is not None:
        context.user_data["home_msg_id"] = msg_id
    else:
        await PageEngine.show_page(update, context, "HOME")


async def start_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    chat_id = query.message.chat_id

    if not user.username:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 חזרה לדף הראשי", callback_data="pub:user:home")]
        ])

        try:
            await query.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ לא ניתן להתחיל את תהליך האימות\n\n"
                "כדי להגיש בקשת אימות, יש להגדיר שם משתמש (Username) בחשבון הטלגרם שלך.\n\n"
                "שם המשתמש הוא השם שמתחיל בסימן @.\n\n"
                "לאחר שתגדיר שם משתמש, חזור לבוט ולחץ שוב על 🪪 שלח אימות."
            ),
            reply_markup=keyboard
        )
        return

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

    try:
        await query.message.delete()
    except Exception:
        pass

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    context.user_data[user_id]["last_bot_msg"] = msg.message_id


async def process_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    chat_id = update.message.chat_id

    state = context.user_data.get(user_id)

    if not state:
        try:
            await context.bot.delete_message(chat_id, update.message.message_id)
        except Exception:
            pass

        warning = await update.message.reply_text(
            "⚠️ הבוט פועל באמצעות הכפתורים בלבד."
        )
        await asyncio.sleep(2)
        try:
            await context.bot.delete_message(chat_id, warning.message_id)
        except Exception:
            pass

        return

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
            await update.message.reply_text("✅ ההודעה נשלחה למשתמש.")
        else:
            await update.message.reply_text("❌ האימות לא נמצא.")

        context.user_data.pop(user_id, None)
        return

    state = context.user_data.get(user_id)
    if not state:
        await update.message.reply_text("❗ לא התחלת תהליך אימות.")
        return

    step = state["step"]
    last_bot_msg = state["last_bot_msg"]
    user_msg_id = update.message.message_id

    async def cleanup():
        await asyncio.gather(
            context.bot.delete_message(chat_id, user_msg_id),
            context.bot.delete_message(chat_id, last_bot_msg),
            return_exceptions=True
        )

    if step == 1:
        if not update.message.photo:
            await _temp_error(context.bot, chat_id, "❌ עליך לשלוח *תמונה בלבד*.", user_msg_id)
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

    if step == 2:
        if not update.message.photo:
            await _temp_error(context.bot, chat_id, "❌ עליך לשלוח *תמונה בלבד*.", user_msg_id)
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

    if step == 3:
        if not update.message.photo:
            await _temp_error(context.bot, chat_id, "❌ עליך לשלוח *תמונה בלבד*.", user_msg_id)
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

    if step == 4:
        if not (update.message.video_note or update.message.video):
            await _temp_error(context.bot, chat_id, "❌ עליך לשלוח *סרטון עגול* בלבד.", user_msg_id)
            return

        state["media"]["video"] = (
            update.message.video_note.file_id if update.message.video_note else update.message.video.file_id
        )

        await cleanup()

        await context.bot.send_message(
            chat_id,
            "✨ *לקוח יקר,*\n\n"
            "האימות שלך התקבל בהצלחה על ידי צוות הבדיקה שלנו.\n"
            "אנחנו מטפלים בבקשה שלך בעדיפות גבוהה.\n\n"
            "📢 תקבל עדכון ברגע שהאימות יאושר.\n"
            "תודה על שיתוף הפעולה 🙏",
            parse_mode="Markdown"
        )

        await send_to_admin(update, context, state)

        state["step"] = "DONE"
        return


async def send_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, state: dict):
    user = update.message.from_user
    user_id = user.id

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