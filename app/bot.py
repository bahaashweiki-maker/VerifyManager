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
)

from app.engine.page_engine import PageEngine
from app.engine.publishing_renderer import render_home, handle_user_nav
from datetime import datetime
from services.verified_users_service import is_suspended, get_active_suspension

from admin.admin import admin_panel
from admin.verify_admin import verify_admin_menu
from admin.verify_media import verify_media_menu
from admin.publishing_admin import build_publishing_handler
from admin.admin_manager import admin_manager_route, handle_admin_mgr_input
from admin.verified_users_admin import verified_users_route, handle_verified_users_input

from database.publishing_models import init_publishing_db
from database.permission_models import init_permissions_db
from database.verified_users_models import init_verified_users_db
from services.admin_service import is_super_admin
from services.permission_service import has_permission


# ─────────────────────────────────────────
# /start — תמיד דרך Publishing Module
# ─────────────────────────────────────────

async def _reject_if_suspended(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True and notify the user if they are suspended.

    This helper detects the user id from the Update (message or callback)
    and, if an active suspension exists, notifies the user and returns True
    to indicate processing should stop.
    """
    user = None
    if update.effective_user:
        user = update.effective_user
    elif getattr(update, 'message', None) and getattr(update.message, 'from_user', None):
        user = update.message.from_user
    elif getattr(update, 'callback_query', None) and getattr(update.callback_query, 'from_user', None):
        user = update.callback_query.from_user

    if not user:
        return False

    uid = user.id
    try:
        if is_suspended(uid):
            susp = get_active_suspension(uid)
            until = susp.get("suspended_until") if susp else None
            if until:
                try:
                    until_dt = datetime.fromisoformat(until)
                    until_str = until_dt.strftime('%Y-%m-%d %H:%M UTC')
                except Exception:
                    until_str = until
                text = f"🚫 החשבון שלך מושעה עד: {until_str}."
            else:
                text = "🚫 החשבון שלך מושעה (קבוע)."

            # Prefer showing as alert for callback queries
            if getattr(update, 'callback_query', None):
                try:
                    await update.callback_query.answer(text, show_alert=True)
                except Exception:
                    pass
                try:
                    await update.callback_query.message.delete()
                except Exception:
                    pass
            else:
                chat_id = None
                if getattr(update, 'effective_chat', None):
                    chat_id = update.effective_chat.id
                elif getattr(update, 'message', None):
                    chat_id = update.message.chat_id
                if chat_id:
                    try:
                        await context.bot.send_message(chat_id, text)
                    except Exception:
                        pass
            return True
    except Exception:
        # Fail-open on errors in suspension check to avoid accidental blocks
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _reject_if_suspended(update, context):
        return
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
    # Block suspended users early
    if await _reject_if_suspended(update, context):
        return
    query = update.callback_query
    data  = query.data
    # No debug prints during normal operation

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

    # 6. חזרה לפאנל הניהול הראשי
    if data == "ADMIN_PANEL":
        uid = query.from_user.id
        if not is_super_admin(uid) and not has_permission(uid, "admin"):
            await query.answer("⛔ אין לך הרשאה.", show_alert=True)
            return
        return await admin_panel(update, context)

    # 6א. ניהול מנהלים — רק סופר-אדמין
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

    # 6ב. ניהול מאומתים — סופר-אדמין או בעל הרשאת users.view
    if data == "VUSERS_LIST" or data.startswith("VUSERS_"):
        uid = query.from_user.id
        if not is_super_admin(uid) and not has_permission(uid, "users.view"):
            await query.answer("⛔ אין לך הרשאה לנהל משתמשים.", show_alert=True)
            return
        return await verified_users_route(update, context)

    # 7. HOME — דרך Publishing Module בלבד
    if data == "HOME":
        try:
            await query.message.delete()
        except Exception:
            pass
        await render_home(context.bot, query.message.chat_id)
        return

    # 8. pub:* שלא נתפס ע"י ConversationHandler — בלע בשקט
    if data.startswith("pub:"):
        return

    # 9. IGNORE
    if data == "IGNORE":
        return

    # 10. מודולים בפיתוח — BROADCAST / STATISTICS / SETTINGS
    if data in ("ADMIN_BROADCAST", "ADMIN_STATISTICS", "ADMIN_SETTINGS", "ADMIN_USERS"):
        await query.answer("🔧 מודול זה בפיתוח — יהיה זמין בקרוב.", show_alert=True)
        return

    # 11. דפים רגילים (PageEngine) — כל שאר ה-callbacks
    try:
        await query.message.delete()
    except Exception:
        pass
    await PageEngine.show_page(update, context, data)


# ─────────────────────────────────────────
# מדיה / טקסט נכנסים
# ─────────────────────────────────────────
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Block suspended users early
    if await _reject_if_suspended(update, context):
        return
    # קלט ממנהל המנהלים
    if context.user_data.get("admin_mgr_state") and update.message and update.message.text:
        return await handle_admin_mgr_input(update, context)
    # קלט ממודול ניהול מאומתים
    if context.user_data.get("vusers_state") and update.message and update.message.text:
        return await handle_verified_users_input(update, context)
    # ברירת מחדל — תהליך אימות
    await process_verify(update, context)


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    init_publishing_db()
    init_permissions_db()
    init_verified_users_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Publishing ConversationHandler — group=-1 מבטיח קליטה לפני button_click
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