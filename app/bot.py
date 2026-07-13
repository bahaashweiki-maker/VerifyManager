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

from admin.admin import admin_panel
from admin.verify_admin import verify_admin_menu
from admin.verify_media import verify_media_menu


# -----------------------------
# פקודת /start
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await query.answer()

    data = query.data

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