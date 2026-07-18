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

from admin.admin import admin_panel
from admin.verify_admin import verify_admin_menu
from admin.verify_media import verify_media_menu
from admin.publishing_admin import build_publishing_handler
from admin.admin_manager import admin_manager_route, handle_admin_mgr_input

from database.publishing_models import init_publishing_db
from database.permission_models import init_permissions_db
from services.admin_service import is_super_admin
from services.permission_service import has_permission


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_home(context.bot, update.effective_chat.id)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    if data.startswith("pub:user:"):
        return await handle_user_nav(update, context)

    await query.answer()

    if data.startswith("VIEW_"):
        return await verify_media_menu(update, context)

    if data.startswith("MEDIA_BACK_"):
        if not is_super_admin(query.from_user.id) and not has_permission(query.from_user.id, "verify.review"):
            await query.answer("⛔ אין לך הרשאה לנהל אימותים.", show_alert=True)
            return
        return await verify_admin_menu(update, context)

    if data == "START_VERIFY":
        return await start_verify(update, context)

    if data == "CANCEL_VERIFY":
        context.user_data.clear()
        try:
            await query.message.delete()
        except Exception:
            pass
        await render_home(context.bot, query.message.chat_id)
        return

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

    if data == "ADMIN_PANEL":
        if not is_super_admin(query.from_user.id) and not has_permission(query.from_user.id, "admin"):
            await query.answer("⛔ אין לך הרשאה.", show_alert=True)
            return
        return await admin_panel(update, context)

    if (
        data == "ADMIN_MANAGERS"
        or data == "ADMIN_MGR_ADD"
        or data == "ADMIN_MGR_LIST"
        or data == "ADMIN_MGR_CANCEL"
        or data.startswith("ADMIN_MGR_VIEW_")
        or data.startswith("ADMIN_MGR_PERMS_")
        or data.startswith("ADMIN_MGR_TOGGLE_")
        or data.startswith("ADMIN_MGR_DEMOTE_")
        or data.startswith("ADMIN_MGR_CONFIRM_")
    ):
        if not is_super_admin(query.from_user.id):
            await query.answer("⛔ רק הסופר-אדמין יכול לנהל מנהלים.", show_alert=True)
            return
        return await admin_manager_route(update, context)

    if data == "HOME":
        try:
            await query.message.delete()
        except Exception:
            pass
        await render_home(context.bot, query.message.chat_id)
        return

    if data.startswith("pub:"):
        return

    if data == "IGNORE":
        return

    try:
        await query.message.delete()
    except Exception:
        pass
    await PageEngine.show_page(update, context, data)


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("admin_mgr_state") and update.message and update.message.text:
        return await handle_admin_mgr_input(update, context)
    await process_verify(update, context)


def main():
    init_publishing_db()
    init_permissions_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(
        build_publishing_handler(
            is_admin_fn=lambda u: (
                is_super_admin(u.effective_user.id)
                or has_permission(u.effective_user.id, "admin")
            )
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