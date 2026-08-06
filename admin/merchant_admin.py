"""
admin/merchant_admin.py
----------------------
Admin UI for merchant publication management.

Current scope:
- Global merchant channels list/add/remove
- Merchant list (users whose type is 'merchant')
- Per-merchant channel assignment
- Per-merchant hourly publication toggle
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from admin.admin import admin_panel
from repositories.merchant_channels_repository import (
    create_channel,
    deactivate_channel,
    get_channel_by_id,
    list_channels,
)
from repositories.merchant_publication_repository import (
    grant_merchant_channel_access,
    grant_merchant_required_channel,
    list_merchant_allowed_channels,
    list_merchant_required_channels,
    merchant_has_hourly_publish,
    revoke_merchant_channel_access,
    revoke_merchant_required_channel,
    set_merchant_hourly_publish,
)
from services.merchant_service import list_merchant_profiles

logger = logging.getLogger(__name__)

_STATE = "merchant_admin_state"
_CHAT_ID = "merchant_admin_chat_id"
_MSG_ID = "merchant_admin_msg_id"
_WAIT_CHANNEL = "WAITING_MERCHANT_CHANNEL"


async def merchant_admin_route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    if data == "ADMIN_MERCHANTS":
        return await _show_main_menu(update, context)
    if data == "MERCHANT_ADM_CHANNELS":
        return await _show_channels(update, context)
    if data == "MERCHANT_ADM_CHANNEL_ADD":
        return await _prompt_add_channel(update, context)
    if data.startswith("MERCHANT_ADM_CHANNEL_VIEW_"):
        return await _show_channel_details(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_CHANNEL_DEL_"):
        return await _delete_channel(update, context, int(data.rsplit("_", 1)[1]))
    if data == "MERCHANT_ADM_LIST":
        return await _show_merchants(update, context)
    if data.startswith("MERCHANT_ADM_VIEW_"):
        return await _show_merchant(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_HOURLY_"):
        return await _toggle_hourly(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_ASSIGN_"):
        return await _show_channel_assignment(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_REQUIRED_"):
        return await _show_required_assignment(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_CH_TOGGLE_"):
        raw = data.removeprefix("MERCHANT_ADM_CH_TOGGLE_")
        telegram_id_raw, channel_id_raw = raw.split("_", 1)
        return await _toggle_merchant_channel(update, context, int(telegram_id_raw), int(channel_id_raw))
    if data.startswith("MERCHANT_ADM_REQ_TOGGLE_"):
        raw = data.removeprefix("MERCHANT_ADM_REQ_TOGGLE_")
        telegram_id_raw, channel_id_raw = raw.split("_", 1)
        return await _toggle_required_channel(update, context, int(telegram_id_raw), int(channel_id_raw))
    if data == "MERCHANT_ADM_BACK":
        return await _show_main_menu(update, context)


async def handle_merchant_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get(_STATE)
    if state != _WAIT_CHANNEL or not update.message:
        return

    text = (update.message.text or "").strip()
    chat_id = context.user_data.pop(_CHAT_ID, None)
    msg_id = context.user_data.pop(_MSG_ID, None)
    context.user_data.pop(_STATE, None)

    created_id = create_channel(text)
    if created_id > 0:
        await _edit_stored_message(
            context,
            chat_id,
            msg_id,
            "✅ הערוץ נשמר בהצלחה.",
            _back_to_channels_kb(),
        )
    else:
        await _edit_stored_message(
            context,
            chat_id,
            msg_id,
            "❌ לא ניתן לשמור ערוץ. שלח @channel או קישור t.me תקין.",
            _back_to_channels_kb(),
        )

    try:
        await update.message.delete()
    except Exception:
        pass


async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    await update.callback_query.edit_message_text(
        "🏪 <b>ניהול סוחרים ופרסום</b>\n\nבחר פעולה:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 ניהול סוחרים", callback_data="MERCHANT_ADM_LIST")],
            [InlineKeyboardButton("📡 ערוצים מורשים", callback_data="MERCHANT_ADM_CHANNELS")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="ADMIN_PANEL")],
        ]),
        parse_mode="HTML",
    )


async def _show_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    channels = list_channels(active_only=True)
    rows = []
    for channel in channels:
        rows.append([
            InlineKeyboardButton(
                f"📡 {channel['display_name']}",
                callback_data=f"MERCHANT_ADM_CHANNEL_VIEW_{channel['id']}",
            ),
            InlineKeyboardButton("🗑", callback_data=f"MERCHANT_ADM_CHANNEL_DEL_{channel['id']}")
        ])
    rows.append([InlineKeyboardButton("➕ הוסף ערוץ", callback_data="MERCHANT_ADM_CHANNEL_ADD")])
    rows.append([InlineKeyboardButton("🔙 חזרה", callback_data="MERCHANT_ADM_BACK")])

    text = f"📡 <b>ערוצים מורשים</b> ({len(channels)})\n\n"
    if channels:
        text += "כאן אתה מנהל את רשימת הערוצים שאפשר לשייך לסוחרים."
    else:
        text += "אין עדיין ערוצים. הוסף ערוץ ראשון."

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_channel_details(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int) -> None:
    _clear_state(context)
    channel = get_channel_by_id(channel_id)
    if channel is None:
        await update.callback_query.answer("⚠️ ערוץ לא נמצא", show_alert=True)
        return await _show_channels(update, context)

    await update.callback_query.edit_message_text(
        (
            "📡 <b>פרטי ערוץ</b>\n\n"
            f"שם: <b>{channel['display_name']}</b>\n"
            f"מפתח: <code>{channel['channel_key']}</code>\n"
            f"מזהה/קישור: <code>{channel['channel_ref']}</code>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 הסר ערוץ", callback_data=f"MERCHANT_ADM_CHANNEL_DEL_{channel['id']}")],
            [InlineKeyboardButton("⬅️ חזרה לערוצים", callback_data="MERCHANT_ADM_CHANNELS")],
        ]),
        parse_mode="HTML",
    )


async def _prompt_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    context.user_data[_STATE] = _WAIT_CHANNEL
    context.user_data[_CHAT_ID] = query.message.chat_id
    context.user_data[_MSG_ID] = query.message.message_id
    await query.edit_message_text(
        (
            "📡 <b>הוספת ערוץ</b>\n\n"
            "פורמטים נתמכים:\n"
            "• @channel\n"
            "• https://t.me/channel\n"
            "• שם | @channel\n"
            "• שם | קישור הזמנה פרטי | -1001234567890"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="MERCHANT_ADM_CHANNELS")],
        ]),
        parse_mode="HTML",
    )


async def _delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int) -> None:
    ok = deactivate_channel(channel_id)
    await update.callback_query.answer("✅ הערוץ הוסר" if ok else "⚠️ לא ניתן להסיר", show_alert=not ok)
    await _show_channels(update, context)


async def _show_merchants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    merchants = list_merchant_profiles()
    rows = []
    for merchant in merchants:
        rows.append([
            InlineKeyboardButton(
                f"🏪 {merchant['display_name']}",
                callback_data=f"MERCHANT_ADM_VIEW_{merchant['telegram_id']}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 חזרה", callback_data="MERCHANT_ADM_BACK")])

    await update.callback_query.edit_message_text(
        f"👤 <b>רשימת סוחרים</b> ({len(merchants)})\n\nבחר סוחר לניהול:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_merchant(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    channels, required_channels = _sanitize_merchant_channel_permissions(telegram_id)
    all_channels = list_channels(active_only=True)
    by_key = {c["channel_key"]: c["display_name"] for c in all_channels}

    def _format_channel_list(keys: list[str]) -> str:
        if not keys:
            return "אין"
        names = [by_key.get(k, k) for k in keys]
        if len(names) > 4:
            return ", ".join(names[:4]) + f" ... (+{len(names) - 4})"
        return ", ".join(names)

    hourly = merchant_has_hourly_publish(telegram_id)
    hourly_label = "פעיל" if hourly else "כבוי"

    await update.callback_query.edit_message_text(
        (
            f"🏪 <b>{merchant['display_name']}</b>\n"
            f"🆔 <code>{telegram_id}</code>\n\n"
            f"⏱️ פרסום כל שעה: <b>{hourly_label}</b>\n"
            f"📡 ערוצי פרסום: <b>{len(channels)}</b>\n"
            f"🔐 ערוצי חובה: <b>{len(required_channels)}</b>\n\n"
            f"📡 משויך לפרסום: <b>{_format_channel_list(channels)}</b>\n"
            f"🔐 חובת הצטרפות: <b>{_format_channel_list(required_channels)}</b>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 שיוך ערוצים", callback_data=f"MERCHANT_ADM_ASSIGN_{telegram_id}")],
            [InlineKeyboardButton("🔐 חובת הצטרפות", callback_data=f"MERCHANT_ADM_REQUIRED_{telegram_id}")],
            [InlineKeyboardButton("⏱️ הפעל/כבה כל שעה", callback_data=f"MERCHANT_ADM_HOURLY_{telegram_id}")],
            [InlineKeyboardButton("🔙 חזרה לסוחרים", callback_data="MERCHANT_ADM_LIST")],
        ]),
        parse_mode="HTML",
    )


async def _toggle_hourly(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> None:
    enabled = not merchant_has_hourly_publish(telegram_id)
    ok = set_merchant_hourly_publish(
        telegram_id=telegram_id,
        enabled=enabled,
        granted_by=update.callback_query.from_user.id,
    )
    if ok:
        await update.callback_query.answer("✅ נשמר")
    else:
        await update.callback_query.answer("❌ שגיאה בשמירה", show_alert=True)
    await _show_merchant(update, context, telegram_id)


async def _show_channel_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    assigned = set(_sanitize_merchant_channel_permissions(telegram_id)[0])
    channels = list_channels(active_only=True)
    rows = []
    for channel in channels:
        mark = "✅" if channel["channel_key"] in assigned else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {channel['display_name']}",
                callback_data=f"MERCHANT_ADM_CH_TOGGLE_{telegram_id}_{channel['id']}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 חזרה לסוחר", callback_data=f"MERCHANT_ADM_VIEW_{telegram_id}")])

    await update.callback_query.edit_message_text(
        f"📡 <b>ערוצי פרסום</b>\n\nסוחר: <b>{merchant['display_name']}</b>",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _toggle_merchant_channel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    channel_id: int,
) -> None:
    channel = get_channel_by_id(channel_id)
    if channel is None:
        await update.callback_query.answer("⚠️ ערוץ לא נמצא", show_alert=True)
        return await _show_channel_assignment(update, context, telegram_id)

    assigned = set(list_merchant_allowed_channels(telegram_id))
    if channel["channel_key"] in assigned:
        ok = revoke_merchant_channel_access(telegram_id, channel["channel_key"])
    else:
        ok = grant_merchant_channel_access(
            telegram_id,
            channel["channel_key"],
            granted_by=update.callback_query.from_user.id,
        )

    await update.callback_query.answer("✅ נשמר" if ok else "❌ שגיאה", show_alert=not ok)
    await _show_channel_assignment(update, context, telegram_id)


async def _show_required_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    assigned = set(_sanitize_merchant_channel_permissions(telegram_id)[1])
    channels = list_channels(active_only=True)
    rows = []
    for channel in channels:
        mark = "✅" if channel["channel_key"] in assigned else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {channel['display_name']}",
                callback_data=f"MERCHANT_ADM_REQ_TOGGLE_{telegram_id}_{channel['id']}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 חזרה לסוחר", callback_data=f"MERCHANT_ADM_VIEW_{telegram_id}")])

    await update.callback_query.edit_message_text(
        (
            f"🔐 <b>ערוצי חובה להצטרפות</b>\n\n"
            f"סוחר: <b>{merchant['display_name']}</b>\n"
            f"הסוחר חייב להיות חבר בכל הערוצים המסומנים לפני פתיחת פרסום."
        ),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _toggle_required_channel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    channel_id: int,
) -> None:
    channel = get_channel_by_id(channel_id)
    if channel is None:
        await update.callback_query.answer("⚠️ ערוץ לא נמצא", show_alert=True)
        return await _show_required_assignment(update, context, telegram_id)

    assigned = set(list_merchant_required_channels(telegram_id))
    if channel["channel_key"] in assigned:
        ok = revoke_merchant_required_channel(telegram_id, channel["channel_key"])
    else:
        ok = grant_merchant_required_channel(
            telegram_id,
            channel["channel_key"],
            granted_by=update.callback_query.from_user.id,
        )

    await update.callback_query.answer("✅ נשמר" if ok else "❌ שגיאה", show_alert=not ok)
    await _show_required_assignment(update, context, telegram_id)


def _get_merchant_or_none(telegram_id: int):
    merchants = list_merchant_profiles()
    return next((m for m in merchants if int(m["telegram_id"]) == int(telegram_id)), None)


def _sanitize_merchant_channel_permissions(telegram_id: int) -> tuple[list[str], list[str]]:
    """Remove stale channel permissions that no longer match active channel keys."""
    active_channel_keys = {c["channel_key"] for c in list_channels(active_only=True)}

    allowed = list_merchant_allowed_channels(telegram_id)
    required = list_merchant_required_channels(telegram_id)

    stale_allowed = [key for key in allowed if key not in active_channel_keys]
    stale_required = [key for key in required if key not in active_channel_keys]

    for key in stale_allowed:
        revoke_merchant_channel_access(telegram_id, key)
    for key in stale_required:
        revoke_merchant_required_channel(telegram_id, key)

    if stale_allowed or stale_required:
        allowed = list_merchant_allowed_channels(telegram_id)
        required = list_merchant_required_channels(telegram_id)

    return allowed, required


def _back_to_channels_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזרה לערוצים", callback_data="MERCHANT_ADM_CHANNELS")],
    ])


async def _edit_stored_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int | None,
    msg_id: int | None,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    if chat_id and msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return
        except Exception:
            pass
    if chat_id:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")


def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(_STATE, None)
    context.user_data.pop(_CHAT_ID, None)
    context.user_data.pop(_MSG_ID, None)
