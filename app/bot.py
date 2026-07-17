from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.settings import BOT_TOKEN

from services.verify_service import (
    start_verify,
    process_verify,
    cancel_verify,
)

from app.engine.page_engine import PageEngine
from app.engine.publishing_renderer import render_home, handle_user_nav

from admin.admin import admin_panel, ADMIN_ID
from admin.verify_admin import verify_admin_menu
from admin.verify_media import verify_media_menu
from admin.publishing_admin import build_publishing_handler

from database.publishing_models import init_publishing_db
from database.permission_models import init_permissions_db
from services.admin_service import is_super_admin
from services.permission_service import has_permission


# ─────────────────────────────────────────
# /start — תמיד דרך Publishing Module
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_home(context.bot, update.effective_chat.id)


# ─────────────────────────────────────────
# /admin
# ─────────────────────────────────────────
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)


# ─────────────────────────────────────────
# כל הכפתורים
# ─────────────────────────────────────────
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    # 1. pub:user:* — handle_user_nav קורא ל-answer() בעצמו, חייב להיות לפני query.answer()
    if data.startswith("pub:user:"):
        return await handle_user_nav(update, context)

    await query.answer()

    # 2. מדיה של אימותים
    if data.startswith("VIEW_"):
        return await verify_media_menu(update, context)

    if data.startswith("MEDIA_BACK_"):
        if not is_super_admin(query.from_user.id) and not has_permission(query.from_user.id, "verify.review"):
            await query.answer("⛔ אין לך הרשאה לנהל אימותים.", show_alert=True)
            return
        return await verify_admin_menu(update, context)

    # 3. התחלת אימות
    if data == "START_VERIFY":
        return await start_verify(update, context)

    # 4. ביטול אימות
    if data == "CANCEL_VERIFY":
        # cancel_verify פנימית קוראת PageEngine.show_page("HOME") שמציג את הבית הישן.
        # במקום זאת: מנקים state, מוחקים הודעה נוכחית, ומציגים את בית הפרסומים החדש.
        context.user_data.clear()
        try:
            await query.message.delete()
        except Exception:
            pass
        await render_home(context.bot, query.message.chat_id)
        return

    # 5. מערכת האימותים — מנהל
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
        if not is_super_admin(query.from_user.id) and not has_permission(query.from_user.id, "verify.review"):
            await query.answer("⛔ אין לך הרשאה לנהל אימותים.", show_alert=True)
            return
        return await verify_admin_menu(update, context)

    # 6. HOME — דרך Publishing Module בלבד
    #    (תואם כפתורים ישנים שעדיין שולחים callback_data="HOME")
    if data == "HOME":
        try:
            await query.message.delete()
        except Exception:
            pass
        await render_home(context.bot, query.message.chat_id)
        return

    # 7. pub:* שלא נתפס ע"י ConversationHandler (group=-1) — בלע בשקט
    if data.startswith("pub:"):
        return

    # 8. IGNORE
    if data == "IGNORE":
        return

    # 9. דפים רגילים (PageEngine) — כל שאר ה-callbacks
    try:
        await query.message.delete()
    except Exception:
        pass
    await PageEngine.show_page(update, context, data)


# ─────────────────────────────────────────
# מדיה / טקסט נכנסים
# ─────────────────────────────────────────
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_verify(update, context)


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    init_publishing_db()
    init_permissions_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Publishing ConversationHandler — group=-1 מבטיח קליטה לפני button_click
    app.add_handler(
        build_publishing_handler(
            is_admin_fn=lambda u: u.effective_user.id == ADMIN_ID
        ),
        group=-1,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin",  admin))
    app.add_handler(CallbackQueryHandler(button_click))
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
