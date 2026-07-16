from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from config.settings import BOT_TOKEN
from services.verify_service import (
    start_verify,
    process_verify,
    cancel_verify,
)

from app.engine.page_engine import PageEngine

from admin.admin import admin_panel, ADMIN_ID
from admin.verify_admin import verify_admin_menu
from admin.verify_media import verify_media_menu

from database.publishing_models     import init_publishing_db
from admin.publishing_admin         import build_publishing_handler
from app.engine.publishing_renderer import handle_user_nav, render_home


# -----------------------------
# פקודת /start
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    bot     = context.bot

    # מחיקת הודעת הבית הקודמת של הבוט (אם קיימת) — ולא של הודעת /start של המשתמש
    prev_msg_id = context.user_data.get("home_msg_id")
    if prev_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
        except Exception:
            pass  # ההודעה כבר נמחקה או פגה — ממשיכים
        context.user_data.pop("home_msg_id", None)

    # שליחת הודעת הבית החדשה ושמירת ה-message_id
    msg_id = await render_home(bot, chat_id)
    if msg_id is not None:
        context.user_data["home_msg_id"] = msg_id
    else:
        await PageEngine.show_page(update, context, "HOME")


# -----------------------------
# פקודת /admin
# -----------------------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)


# -----------------------------
# כל הכפתורים
# -----------------------------
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # מודול הפרסום — ניווט משתמש (מטפל ב-answer() בעצמו)
    if data.startswith("pub:user:"):
        return await handle_user_nav(update, context)

    await query.answer()

    # 1. מדיה של אימותים
    if data.startswith("VIEW_"):
        return await verify_media_menu(update, context)

    if data.startswith("MEDIA_BACK_"):
        return await verify_admin_menu(update, context)

    # 2. התחלת אימות
    if data == "START_VERIFY":
        return await start_verify(update, context)

    # 3. ביטול אימות
    if data == "CANCEL_VERIFY":
        return await cancel_verify(update, context)

    # 4. מערכת האימותים - מנהל
    if (
        data in (
            "ADMIN_VERIFY",
            "ADMIN_HOME",
            "VERIFY_PENDING",
            "VERIFY_APPROVED",
            "VERIFY_REJECTED",
            "VERIFY_BLOCKED",
            "VERIFY_STATS",
        )
        or data.startswith("OPEN_VERIFY_")
        or data.startswith("VERIFY_APPROVE_")
        or data.startswith("VERIFY_REJECT_")
        or data.startswith("VERIFY_BLOCK_")
        or data.startswith("VERIFY_DELETE_")
        or data.startswith("VERIFY_MESSAGE_")
    ):
        return await verify_admin_menu(update, context)

    # 5. מעבר בין דפים רגילים
    if data == "IGNORE":
        return

    # pub: שנשאר כאן (מצב שגוי) — לא מעבירים ל-PageEngine
    if data.startswith("pub:"):
        return

    try:
        await update.callback_query.message.delete()
    except Exception:
        pass
    await PageEngine.show_page(update, context, data)


# -----------------------------
# כל המדיה
# -----------------------------
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_verify(update, context)


# -----------------------------
# MAIN
# -----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # אתחול DB של מודול הפרסום
    init_publishing_db()

    # ConversationHandler של ניהול פרסומים (לפני ה-handler הכללי)
    app.add_handler(
        build_publishing_handler(
            is_admin_fn=lambda u: u.effective_user.id == ADMIN_ID
        ),
        group=-1,
    )

    # /start
    app.add_handler(CommandHandler("start", start))

    # /admin
    app.add_handler(CommandHandler("admin", admin))

    # כל הכפתורים
    app.add_handler(CallbackQueryHandler(button_click))

    # תמונות / סרטונים / טקסט
    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.VIDEO_NOTE
            | filters.TEXT,
            media_handler,
        )
    )

    print("🤖 Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()