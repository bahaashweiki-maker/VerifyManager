"""
admin/admin_manager.py
─────────────────────────────────────────────────────────────────────────────
ממשק ניהול מנהלים — VerifyManager Admin Manager

נגיש רק לסופר-אדמין. הגנה מתבצעת ב-bot.py לפני הניתוב לכאן.

Callbacks:
    ADMIN_MANAGERS              — תפריט ראשי
    ADMIN_MGR_ADD               — פרומפט להוספת מנהל
    ADMIN_MGR_LIST              — רשימת מנהלים
    ADMIN_MGR_VIEW_{id}         — צפייה במנהל ספציפי
    ADMIN_MGR_PERMS_{id}        — מסך הרשאות גרפי (✅/❌ לכל הרשאה)
    ADMIN_MGR_TOGGLE_{id}_{key} — הפעלה/ביטול הרשאה מיידי
    ADMIN_MGR_DEMOTE_{id}       — מסך אישור הורדת מנהל
    ADMIN_MGR_CONFIRM_{id}      — ביצוע הורדת מנהל
    ADMIN_MGR_CANCEL            — ביטול קלט וחזרה לתפריט

state ב-context.user_data:
    admin_mgr_state    — "WAITING_ADMIN_ID"
    admin_mgr_chat_id  — chat_id של הודעת הפרומפט
    admin_mgr_msg_id   — message_id של הודעת הפרומפט
    mgr_viewed_perms   — רשימת הרשאות של מנהל שנצפה (פנימי)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

from telegram import Bot, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config.permissions import PERMISSIONS
from services.admin_service import (
    promote_to_admin,
    demote_admin,
    get_all_admins,
    grant_admin_permission,
    revoke_admin_permission,
    get_admin_permissions,
    is_super_admin,
)

logger = logging.getLogger(__name__)

_STATE        = "admin_mgr_state"
_CHAT_ID      = "admin_mgr_chat_id"
_MSG_ID       = "admin_mgr_msg_id"
_VIEWED_PERMS = "mgr_viewed_perms"

_WAIT_ID = "WAITING_ADMIN_ID"


async def admin_manager_route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data  = query.data

    if data == "ADMIN_MANAGERS":
        return await _show_main_menu(update, context)
    if data == "ADMIN_MGR_ADD":
        return await _prompt_add_admin(update, context)
    if data == "ADMIN_MGR_LIST":
        return await _show_admin_list(update, context)
    if data.startswith("ADMIN_MGR_VIEW_"):
        return await _show_admin_view(update, context)
    if data.startswith("ADMIN_MGR_PERMS_"):
        return await _show_permissions_screen(update, context)
    if data.startswith("ADMIN_MGR_TOGGLE_"):
        return await _toggle_permission(update, context)
    if data.startswith("ADMIN_MGR_DEMOTE_") and not data.startswith("ADMIN_MGR_CONFIRM_"):
        return await _confirm_demote(update, context)
    if data.startswith("ADMIN_MGR_CONFIRM_"):
        return await _execute_demote(update, context)
    if data == "ADMIN_MGR_CANCEL":
        return await _cancel_input(update, context)


async def handle_admin_mgr_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get(_STATE, "")
    text  = (update.message.text or "").strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if state == _WAIT_ID:
        await _process_add_admin(update, context, text)


async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ הוסף מנהל",    callback_data="ADMIN_MGR_ADD")],
        [InlineKeyboardButton("📋 רשימת מנהלים", callback_data="ADMIN_MGR_LIST")],
        [InlineKeyboardButton("🔙 חזרה",         callback_data="ADMIN_PANEL")],
    ])
    await update.callback_query.edit_message_text(
        text="👑 <b>ניהול מנהלים</b>\n\nבחר פעולה:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _prompt_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    context.user_data[_STATE]   = _WAIT_ID
    context.user_data[_CHAT_ID] = query.message.chat_id
    context.user_data[_MSG_ID]  = query.message.message_id

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ביטול", callback_data="ADMIN_MGR_CANCEL")],
    ])
    await query.edit_message_text(
        text=(
            "➕ <b>הוספת מנהל חדש</b>\n\n"
            "שלח את ה-Telegram ID של המנהל:\n"
            "<i>(מספר בלבד, למשל: 123456789)</i>"
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _process_add_admin(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    chat_id = context.user_data.pop(_CHAT_ID, None)
    msg_id  = context.user_data.pop(_MSG_ID, None)
    context.user_data.pop(_STATE, None)

    caller_id = update.message.from_user.id

    if not text.lstrip("-").isdigit():
        await _edit_stored(context, chat_id, msg_id,
            text="❌ <b>קלט לא תקין</b>\n\nנדרש מספר בלבד.\nנסה שוב מהתפריט.",
            keyboard=_back_to_managers_kb(),
        )
        return

    target_id = int(text)

    if is_super_admin(target_id):
        await _edit_stored(context, chat_id, msg_id,
            text="⚠️ לא ניתן לשנות הרשאות הסופר-אדמין.",
            keyboard=_back_to_managers_kb(),
        )
        return

    success = promote_to_admin(target_id, granted_by=caller_id)

    if success:
        msg = (
            f"✅ <b>מנהל נוסף בהצלחה</b>\n\n"
            f"Telegram ID: <code>{target_id}</code>\n"
            f"הרשאת בסיס <code>admin</code> הוקצתה.\n\n"
            f"<i>לניהול הרשאות נוספות — כנס לפרטי המנהל.</i>"
        )
    else:
        msg = "❌ שגיאה בהוספת המנהל. נסה שנית."

    await _edit_stored(context, chat_id, msg_id, text=msg, keyboard=_back_to_managers_kb())


async def _show_admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    admins = get_all_admins()

    if not admins:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 חזרה", callback_data="ADMIN_MANAGERS")],
        ])
        await update.callback_query.edit_message_text(
            text="📋 <b>רשימת מנהלים</b>\n\nאין מנהלים פעילים כרגע.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(
            f"👤 {admin_id}",
            callback_data=f"ADMIN_MGR_VIEW_{admin_id}",
        )]
        for admin_id in admins
    ]
    buttons.append([InlineKeyboardButton("🔙 חזרה", callback_data="ADMIN_MANAGERS")])

    await update.callback_query.edit_message_text(
        text=f"📋 <b>מנהלים פעילים</b> ({len(admins)})\n\nבחר מנהל לצפייה:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _show_admin_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    data      = update.callback_query.data
    target_id = int(data[len("ADMIN_MGR_VIEW_"):])
    perms     = get_admin_permissions(target_id)

    context.user_data[_VIEWED_PERMS] = perms

    perms_lines = []
    for p in perms:
        label = next((x["label"] for x in PERMISSIONS if x["key"] == p), None)
        if label:
            perms_lines.append(f"  ✅ {label}")
        else:
            perms_lines.append(f"  ✅ <code>{p}</code>")

    perms_text = "\n".join(perms_lines) if perms_lines else "  <i>אין הרשאות</i>"

    text = (
        f"👤 <b>מנהל</b>: <code>{target_id}</code>\n\n"
        f"<b>הרשאות ({len(perms)}):</b>\n{perms_text}"
    )

    buttons = [
        [InlineKeyboardButton("🔐 ניהול הרשאות", callback_data=f"ADMIN_MGR_PERMS_{target_id}")],
        [InlineKeyboardButton("🚫 הורד ממנהל",   callback_data=f"ADMIN_MGR_DEMOTE_{target_id}")],
        [InlineKeyboardButton("🔙 חזרה",         callback_data="ADMIN_MGR_LIST")],
    ]

    await update.callback_query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _show_permissions_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data      = update.callback_query.data
    target_id = int(data[len("ADMIN_MGR_PERMS_"):])
    await _render_permissions_screen(update.callback_query, target_id, context.bot)


async def _toggle_permission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data   = update.callback_query.data
    suffix = data[len("ADMIN_MGR_TOGGLE_"):]

    sep_idx   = suffix.index("_")
    target_id = int(suffix[:sep_idx])
    perm_key  = suffix[sep_idx + 1:]

    caller_id     = update.callback_query.from_user.id
    current_perms = set(get_admin_permissions(target_id))

    if perm_key in current_perms:
        revoke_admin_permission(target_id, perm_key)
        await update.callback_query.answer(f"❌ הוסרה: {perm_key}")
    else:
        grant_admin_permission(target_id, perm_key, granted_by=caller_id)
        await update.callback_query.answer(f"✅ הופעלה: {perm_key}")

    await _render_permissions_screen(update.callback_query, target_id, context.bot)


async def _render_permissions_screen(
    query: CallbackQuery,
    target_id: int,
    bot: Bot | None = None,
) -> None:
    # שליפת פרטי המשתמש מטלגרם (שם + username)
    header   = f"🆔 <code>{target_id}</code>"
    username = None

    if bot:
        try:
            chat = await bot.get_chat(target_id)
            header = f"👤 {chat.first_name}"
            if chat.username:
                username = chat.username
                header += f"\n📛 @{chat.username}"
            header += f"\n🆔 <code>{target_id}</code>"
        except Exception:
            pass  # אם הבקשה נכשלת — מוצג ID בלבד

    current_perms = set(get_admin_permissions(target_id))

    buttons = []
    for perm in PERMISSIONS:
        key   = perm["key"]
        label = perm["label"]
        icon  = "✅" if key in current_perms else "❌"
        buttons.append([InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=f"ADMIN_MGR_TOGGLE_{target_id}_{key}",
        )])

    # כפתור יצירת קשר — מוצג רק אם קיים username
    if username:
        buttons.append([
            InlineKeyboardButton("💬 צור קשר עם המנהל", url=f"https://t.me/{username}"),
        ])

    buttons.append([
        InlineKeyboardButton("💾 שמור הרשאות", callback_data=f"ADMIN_MGR_VIEW_{target_id}"),
    ])

    await query.edit_message_text(
        text=(
            f"🔐 <b>ניהול הרשאות</b>\n"
            f"{header}\n\n"
            f"✅ = הרשאה פעילה  |  ❌ = הרשאה כבויה\n"
            f"לחץ על הרשאה כדי להפעיל / לבטל.\n"
            f"<i>השינויים נשמרים מיד.</i>"
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _confirm_demote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data      = update.callback_query.data
    target_id = int(data[len("ADMIN_MGR_DEMOTE_"):])

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ כן, הורד מנהל", callback_data=f"ADMIN_MGR_CONFIRM_{target_id}")],
        [InlineKeyboardButton("❌ ביטול",          callback_data=f"ADMIN_MGR_VIEW_{target_id}")],
    ])
    await update.callback_query.edit_message_text(
        text=(
            f"⚠️ <b>אישור הורדת מנהל</b>\n\n"
            f"Telegram ID: <code>{target_id}</code>\n\n"
            f"פעולה זו תסיר את <b>כל ההרשאות</b> של המנהל.\n"
            f"האם להמשיך?"
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _execute_demote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data      = update.callback_query.data
    target_id = int(data[len("ADMIN_MGR_CONFIRM_"):])

    count   = demote_admin(target_id)
    success = count is True or count

    if success:
        msg = (
            f"✅ <b>מנהל הורד בהצלחה</b>\n\n"
            f"Telegram ID: <code>{target_id}</code>\n"
            f"כל ההרשאות הוסרו."
        )
    else:
        msg = "❌ שגיאה בהורדת המנהל. נסה שנית."

    context.user_data.pop(_VIEWED_PERMS, None)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 רשימת מנהלים", callback_data="ADMIN_MGR_LIST")],
        [InlineKeyboardButton("🔙 תפריט ראשי",   callback_data="ADMIN_MANAGERS")],
    ])
    await update.callback_query.edit_message_text(
        text=msg, reply_markup=keyboard, parse_mode="HTML"
    )


async def _cancel_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    await _show_main_menu(update, context)


def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (_STATE, _CHAT_ID, _MSG_ID, _VIEWED_PERMS):
        context.user_data.pop(key, None)


async def _edit_stored(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int | None,
    msg_id: int | None,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    if not chat_id or not msg_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("_edit_stored failed: %s", exc)


def _back_to_managers_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 חזרה לניהול מנהלים", callback_data="ADMIN_MANAGERS")],
    ])