"""
admin/subscriptions_admin.py
----------------------------
מטפל ממשק הניהול של מודול המנויים.
כל פעולה שעדיין לא יושמה מחזירה "בקרוב" כל עוד המסכים והקולבקים קיימים.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from database.database import IL_TZ, get_connection, now_il

from services.subscribers_service import (
    list_subscribers_page,
    count_subscribers,
    find_subscribers_page,
    count_subscribers_by_search,
    get_subscriber_card,
    suspend_subscriber,
    unsuspend_subscriber,
    block_subscriber,
    unblock_subscriber,
    clear_subscriber_admin_notes,
    track_subscriber_activity,
)
from services.subscriber_stats_service import (
    get_subscription_system_stats_live,
    get_subscriber_stats_activity,
    get_subscriber_personal_statistics,
    reset_global_stats_actions,
    reset_personal_stats,
)
from services.subscriber_chat_service import (
    open_subscriber_chat,
    get_open_subscriber_chat,
    list_subscriber_chats,
    get_subscriber_chat,
    get_subscriber_chat_history,
    add_subscriber_chat_message,
    clear_subscriber_chat_history,
)
from services.subscriber_publication_service import (
    compute_next_run,
    count_publication_recipients,
    create_publication_delivery_record,
    create_publication_record,
    decode_publication_note,
    dispatch_publication,
    encode_publication_note,
    get_delivery_record,
    get_publication,
    list_available_publication_permissions,
    list_pending_delivery_records,
    list_pending_deletion_records,
    list_publication_buttons,
    list_publications_paged,
    mark_delivery_status,
    publication_stats,
    reset_publication_stats,
    replace_publication_buttons_record,
    remove_publication,
    update_publication_record,
)
from services.verified_users_service import get_all_catalogs


logger = logging.getLogger(__name__)


_STATE = "subs_state"
_AWAIT_SEARCH = "SUBS_AWAIT_SEARCH"
_AWAIT_CHAT_MSG = "SUBS_AWAIT_CHAT_MSG"
_AWAIT_SUB_WARNING = "SUBS_AWAIT_SUB_WARNING"
_AWAIT_SUB_NOTE = "SUBS_AWAIT_SUB_NOTE"
_AWAIT_PUB_CONTENT = "SUBS_AWAIT_PUB_CONTENT"
_AWAIT_PUB_TARGET_VALUE = "SUBS_AWAIT_PUB_TARGET_VALUE"
_AWAIT_PUB_BUTTONS = "SUBS_AWAIT_PUB_BUTTONS"
_AWAIT_PUB_BTN_LABEL = "SUBS_AWAIT_PUB_BTN_LABEL"
_AWAIT_PUB_BTN_VALUE = "SUBS_AWAIT_PUB_BTN_VALUE"
_AWAIT_PUB_BTN_ROW = "SUBS_AWAIT_PUB_BTN_ROW"
_AWAIT_PUB_SEARCH = "SUBS_AWAIT_PUB_SEARCH"
_AWAIT_PUB_SCHEDULE = "SUBS_AWAIT_PUB_SCHEDULE"
_AWAIT_PUB_AUTO_DELETE = "SUBS_AWAIT_PUB_AUTO_DELETE"
_SEARCH_TERM = "subs_search_term"
_CHAT_ID = "subs_chat_id"
_MSG_ID = "subs_msg_id"
_SUB_ID = "subs_subscriber_id"
_SUB_ORIGIN = "subs_origin"
_SUB_PAGE = "subs_page"
_SUB_CHAT_ID = "subs_active_chat_id"
_SUB_WARN_ORIGIN = "subs_warn_origin"
_SUB_WARN_PAGE = "subs_warn_page"
_SUB_WARN_ID = "subs_warn_subscriber_id"
_SUBS_MEDIA_PREVIEW_MSG_ID = "subs_media_preview_msg_id"
_SUBS_MEDIA_PREVIEW_CHAT_ID = "subs_media_preview_chat_id"
_SUBS_MEDIA_META_PREFIX = "__SUBS_MEDIA__:"
_SUBS_MEDIA_META_PREFIX_LEGACY = "SUBS_MEDIA__:"
_PUB_DRAFT = "subs_pub_draft"
_PUB_LIST_PAGE = "subs_pub_list_page"
_PUB_SEARCH_TERM = "subs_pub_search_term"
_PUB_TARGET_OPTIONS = "subs_pub_target_options"
_PUB_PREVIEW_MSG_ID = "subs_pub_preview_msg_id"
_PUB_PREVIEW_CHAT_ID = "subs_pub_preview_chat_id"
_PUB_PREVIEW_CONFIRMED = "subs_pub_preview_confirmed"
_PUB_EDIT_ID = "subs_pub_edit_id"
_PUB_BTN_MODE = "subs_pub_btn_mode"
_PUB_BTN_EDIT_INDEX = "subs_pub_btn_edit_index"
_PUB_BTN_LABEL_TMP = "subs_pub_btn_label_tmp"
_PUB_BTN_VALUE_TMP = "subs_pub_btn_value_tmp"
_PUB_SCHEDULE_JOBS: dict[int, str] = {}
_PUB_RECURRING_JOBS: dict[int, str] = {}
_PUB_DELETE_JOBS: dict[int, str] = {}


async def subscriptions_admin_route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    if data is None:
        return

    if not data.startswith("SUBS_MEDIA_BACK_"):
        await _clear_open_media_preview(context, query.message.chat_id)

    if data == "ADMIN_SUBSCRIPTIONS" or data == "SUBS_MAIN":
        return await _show_main(update)

    if data == "SUBS_LIST":
        _clear_search_state(context)
        return await _show_subscribers_list(update, page=1)

    if data.startswith("SUBS_LIST_PAGE_"):
        _clear_search_state(context)
        page = _parse_positive_int(data[len("SUBS_LIST_PAGE_"):])
        if page is None:
            return await _invalid_callback(update)
        return await _show_subscribers_list(update, page=page)

    if data == "SUBS_SEARCH":
        return await _prompt_search(update, context)

    if data.startswith("SUBS_SEARCH_PAGE_"):
        page = _parse_positive_int(data[len("SUBS_SEARCH_PAGE_"):])
        if page is None:
            return await _invalid_callback(update)
        return await _show_search_results(update, context, page)

    if data.startswith("SUBS_CARD_"):
        payload = _parse_card_payload(data, "SUBS_CARD_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _show_subscriber_card(update, context, subscriber_id, page, origin)

    if data.startswith("SUBS_OPEN_TG_PRIVATE_"):
        payload = _parse_card_payload(data, "SUBS_OPEN_TG_PRIVATE_")
        if payload is None:
            return await _invalid_callback(update)
        _origin, _page, subscriber_id = payload
        s = get_subscriber_card(subscriber_id)
        if not s or not s.get("username"):
            await update.callback_query.answer(
                "למשתמש זה אין Username ציבורי בטלגרם.",
                show_alert=True,
            )
            return
        await update.callback_query.answer()
        return

    if data.startswith("SUBS_REFRESH_"):
        payload = _parse_card_payload(data, "SUBS_REFRESH_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        await update.callback_query.answer("🔄 רוענן")
        return await _show_subscriber_card(update, context, subscriber_id, page, origin)

    if data.startswith("SUBS_CHAT_HISTORY_PAGE_"):
        payload = _parse_history_payload(data, "SUBS_CHAT_HISTORY_PAGE_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id, history_page = payload
        return await _show_chat_history_screen(update, origin, page, subscriber_id, history_page)

    if data.startswith("SUBS_CHAT_HISTORY_"):
        payload = _parse_card_payload(data, "SUBS_CHAT_HISTORY_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _show_chat_history_screen(update, origin, page, subscriber_id, 1)

    if data.startswith("SUBS_CHAT_RESET_CONFIRM_"):
        payload = _parse_card_payload(data, "SUBS_CHAT_RESET_CONFIRM_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _confirm_reset_chat_history(update, origin, page, subscriber_id)

    if data.startswith("SUBS_CHAT_RESET_DO_"):
        payload = _parse_card_payload(data, "SUBS_CHAT_RESET_DO_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _do_reset_chat_history(update, origin, page, subscriber_id)

    if data.startswith("SUBS_CHAT_SEND_"):
        return await _prompt_chat_message(update, context, data)

    if data.startswith("SUBS_CHAT_OPEN_"):
        return await _open_chat_from_notification(update, data)

    if data.startswith("SUBS_CHAT_VIEW_"):
        return await _show_chat_screen(update, data)

    if data.startswith("SUBS_CHAT_CLOSE_"):
        return await _close_chat_screen(update, data)

    if data.startswith("SUBS_CHAT_"):
        return await _open_chat_screen(update, data)

    if data.startswith("SUBS_MEDIA_VIEW_CHAT_"):
        return await _show_subscriber_media_from_chat(update, context, data)

    if data.startswith("SUBS_MEDIA_VIEW_H_"):
        return await _show_subscriber_media_from_history(update, context, data)

    if data.startswith("SUBS_MEDIA_BACK_CHAT_"):
        return await _back_from_subscriber_media(update, context)

    if data.startswith("SUBS_MEDIA_BACK_H_"):
        return await _back_from_subscriber_media(update, context)

    if data.startswith("SUBS_STATS_RESET_CONFIRM_"):
        payload = _parse_card_payload(data, "SUBS_STATS_RESET_CONFIRM_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _confirm_reset_personal_stats(update, origin, page, subscriber_id)

    if data.startswith("SUBS_STATS_RESET_DO_"):
        payload = _parse_card_payload(data, "SUBS_STATS_RESET_DO_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _do_reset_personal_stats(update, origin, page, subscriber_id)

    if data.startswith("SUBS_STATS_"):
        return await _show_personal_stats(update, data)

    if data.startswith("SUBS_NOTES_RESET_CONFIRM_"):
        payload = _parse_card_payload(data, "SUBS_NOTES_RESET_CONFIRM_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _confirm_reset_subscriber_admin_notes(update, origin, page, subscriber_id)

    if data.startswith("SUBS_NOTES_RESET_DO_"):
        payload = _parse_card_payload(data, "SUBS_NOTES_RESET_DO_")
        if payload is None:
            return await _invalid_callback(update)
        origin, page, subscriber_id = payload
        return await _do_reset_subscriber_admin_notes(update, origin, page, subscriber_id)

    if data.startswith("SUBS_NOTES_"):
        return await _show_subscriber_admin_notes(update, data)

    if data.startswith("SUBS_SUSPEND_DO_"):
        return await _do_suspend(update, context, data)

    if data.startswith("SUBS_UNSUSPEND_DO_"):
        return await _do_unsuspend(update, context, data)

    if data.startswith("SUBS_BLOCK_DO_"):
        return await _do_block(update, context, data)

    if data.startswith("SUBS_UNBLOCK_DO_"):
        return await _do_unblock(update, context, data)

    if data.startswith("SUBS_WARN_"):
        return await _prompt_subscriber_warning(update, context, data)

    if data.startswith("SUBS_NOTE_"):
        return await _prompt_subscriber_note(update, context, data)

    if data.startswith("SUBS_SUSPEND_"):
        return await _show_suspend_menu(update, data)

    if data == "SUBS_PUB_MENU":
        await _bootstrap_publication_jobs(context)
        await _clear_publication_preview_message(context)
        return await _show_publications_menu(update)

    if data == "SUBS_PUB_CREATE":
        return await _start_publication_create(update, context)

    if data == "SUBS_PUB_PREVIEW":
        return await _show_publication_preview(update, context)

    if data.startswith("SUBS_PUB_TARGET_"):
        return await _set_publication_target(update, context, data)

    if data == "SUBS_PUB_EDIT_CONTENT":
        return await _prompt_publication_content(update, context)

    if data == "SUBS_PUB_EDIT_BUTTONS":
        return await _show_publication_buttons_menu(update, context)

    if data == "SUBS_PUB_NOTE_DRAFT_BACK":
        return await _show_publication_preview(update, context)

    if data.startswith("SUBS_PUB_NOTE_DRAFT_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_NOTE_DRAFT_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _show_publication_note_from_draft(update, context, idx)

    if data == "SUBS_PUB_BTN_ADD_URL":
        return await _start_publication_button_add(update, context, mode="add_url")

    if data == "SUBS_PUB_BTN_ADD_NOTE":
        return await _start_publication_button_add(update, context, mode="add_note")

    if data == "SUBS_PUB_BTN_BACK":
        return await _show_publication_preview(update, context)

    if data.startswith("SUBS_PUB_BTN_EDIT_NOTE_NAME_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_EDIT_NOTE_NAME_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _start_publication_button_edit_note_name(update, context, idx)

    if data.startswith("SUBS_PUB_BTN_EDIT_NOTE_VALUE_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_EDIT_NOTE_VALUE_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _start_publication_button_edit_note_value(update, context, idx)

    if data.startswith("SUBS_PUB_BTN_EDIT_URL_NAME_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_EDIT_URL_NAME_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _start_publication_button_edit_url_name(update, context, idx)

    if data.startswith("SUBS_PUB_BTN_EDIT_URL_VALUE_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_EDIT_URL_VALUE_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _start_publication_button_edit_url_value(update, context, idx)

    if data == "SUBS_PUB_BTN_ROW_SAME":
        return await _finalize_publication_button_add(update, context, same_row=True)

    if data == "SUBS_PUB_BTN_ROW_NEW":
        return await _finalize_publication_button_add(update, context, same_row=False)

    if data.startswith("SUBS_PUB_BTN_EDIT_NOTE_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_EDIT_NOTE_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _show_publication_button_edit_choice(update, context, idx, kind="note")

    if data.startswith("SUBS_PUB_BTN_URL_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_URL_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _show_publication_button_edit_choice(update, context, idx, kind="url")

    if data.startswith("SUBS_PUB_BTN_EDIT_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_EDIT_"):])
        if idx is None:
            return await _invalid_callback(update)
        draft = context.user_data.get(_PUB_DRAFT) or {}
        buttons = draft.get("buttons") or []
        if 1 <= idx <= len(buttons):
            value = str((buttons[idx - 1] or {}).get("url") or "")
            if decode_publication_note(value) is not None:
                return await _show_publication_button_edit_choice(update, context, idx, kind="note")
            return await _show_publication_button_edit_choice(update, context, idx, kind="url")
        await update.callback_query.answer("כפתור לעריכה לא נמצא", show_alert=True)
        return

    if data.startswith("SUBS_PUB_BTN_DELETE_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_BTN_DELETE_"):])
        if idx is None:
            return await _invalid_callback(update)
        return await _delete_publication_button(update, context, idx)

    if data == "SUBS_PUB_SEND_NOW":
        return await _send_publication_now(update, context)

    if data == "SUBS_PUB_SCHEDULE":
        return await _prompt_publication_schedule(update, context)

    if data == "SUBS_PUB_RECUR_MONTH":
        return await _set_publication_monthly(update, context)

    if data.startswith("SUBS_PUB_DELAY_"):
        return await _set_publication_delay(update, context, data)

    if data.startswith("SUBS_PUB_RECUR_"):
        return await _set_publication_recurring(update, context, data)

    if data == "SUBS_PUB_CANCEL_DRAFT":
        await _clear_publication_preview_message(context)
        _clear_publication_draft(context)
        return await _show_publications_menu(update)

    if data == "SUBS_PUB_LIST":
        return await _show_publications_list(update, context, page=1)

    if data.startswith("SUBS_PUB_LIST_PAGE_"):
        page = _parse_positive_int(data[len("SUBS_PUB_LIST_PAGE_"):])
        if page is None:
            return await _invalid_callback(update)
        return await _show_publications_list(update, context, page=page)

    if data.startswith("SUBS_PUB_VIEW_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_VIEW_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _show_publication_details(update, context, pub_id)

    if data.startswith("SUBS_PUB_EDIT_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_EDIT_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _start_publication_edit(update, context, pub_id)

    if data == "SUBS_PUB_SAVE_EDIT":
        return await _save_publication_edit(update, context)

    if data.startswith("SUBS_PUB_AUTODEL_"):
        return await _handle_publication_auto_delete(update, context, data)

    if data.startswith("SUBS_PUB_DELETE_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_DELETE_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _delete_publication(update, context, pub_id)

    if data.startswith("SUBS_PUB_PURGE_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_PURGE_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _purge_sent_publication_messages(update, context, pub_id)

    if data.startswith("SUBS_PUB_RUN_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_RUN_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _run_publication_now(update, context, pub_id)

    if data.startswith("SUBS_PUB_CANCEL_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_CANCEL_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _cancel_publication(update, context, pub_id)

    if data.startswith("SUBS_PUB_RESUME_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_RESUME_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _resume_publication(update, context, pub_id)

    if data == "SUBS_PUB_SEARCH":
        return await _prompt_publication_search(update, context)

    if data == "SUBS_PUB_AUTO_DELETE":
        return await _handle_publication_auto_delete(update, context, data)

    if data == "SUBS_PUB_STATS":
        return await _show_publication_stats_menu(update, context)

    if data.startswith("SUBS_PUB_STATS_VIEW_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_STATS_VIEW_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _show_publication_stats_for_one(update, context, pub_id)

    if data.startswith("SUBS_PUB_STATS_RESET_CONFIRM_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_STATS_RESET_CONFIRM_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _confirm_reset_publication_stats(update, pub_id)

    if data.startswith("SUBS_PUB_STATS_RESET_DO_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_STATS_RESET_DO_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _do_reset_publication_stats(update, context, pub_id)

    if data == "SUBS_GLOBAL_STATS":
        return await _show_stats(update)

    if data == "SUBS_GLOBAL_STATS_RESET_CONFIRM":
        return await _confirm_reset_global_stats(update)

    if data == "SUBS_GLOBAL_STATS_RESET_DO":
        return await _do_reset_global_stats(update)


async def _invalid_callback(update: Update) -> None:
    try:
        await update.callback_query.answer("⚠️ פעולה לא תקינה. נסה לרענן את רשימת המנויים.", show_alert=True)
    except Exception:
        pass


def _parse_positive_int(raw: str):
    try:
        value = int(raw)
        if value <= 0:
            return None
        return value
    except (TypeError, ValueError):
        return None


async def _show_main(update: Update) -> None:
    await _safe_query_edit(
        update,
        text="👥 <b>מערכת מנויים</b>\n\nבחר פעולה:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 רשימת מנויים", callback_data="SUBS_LIST")],
            [InlineKeyboardButton("📣 פרסום", callback_data="SUBS_PUB_MENU")],
            [InlineKeyboardButton("📊 סטטיסטיקה", callback_data="SUBS_GLOBAL_STATS")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="ADMIN_PANEL")],
        ]),
        parse_mode="HTML",
    )


async def _show_subscribers_list(update: Update, page: int = 1) -> None:
    per_page = 10
    total = count_subscribers()

    if total == 0:
        await _safe_query_edit(
            update,
            text="👥 <b>רשימת מנויים</b>\n\nלא קיימים מנויים.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_MAIN")],
            ]),
            parse_mode="HTML",
        )
        return

    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    subscribers = list_subscribers_page(page=page, per_page=per_page)

    rows = []
    for s in subscribers:
        display_name = s.get("full_name") or (f"@{s['username']}" if s.get("username") else str(s["telegram_id"]))
        rows.append([
            InlineKeyboardButton(
                f"👤 {display_name}",
                callback_data=f"SUBS_CARD_L_{page}_{s['id']}",
            )
        ])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"SUBS_LIST_PAGE_{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("הבא ➡️", callback_data=f"SUBS_LIST_PAGE_{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton("🔍 חיפוש", callback_data="SUBS_SEARCH")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_MAIN")])

    await _safe_query_edit(
        update,
        text=f"👥 <b>רשימת מנויים</b>\nעמוד {page}/{total_pages} • סה״כ {total}",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_subscriber_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    subscriber_id: int,
    page: int,
    origin: str = "L",
) -> None:
    s = get_subscriber_card(subscriber_id)
    if not s:
        await update.callback_query.answer("⚠️ מנוי לא נמצא.", show_alert=True)
        if origin == "S":
            return await _show_search_results(update, context=context, page=page)
        return await _show_subscribers_list(update, page=page)

    display_name = s.get("full_name") or (f"@{s['username']}" if s.get("username") else str(s["telegram_id"]))
    stats = get_subscriber_personal_statistics(subscriber_id)

    text = (
        f"👤 <b>כרטיס מנוי</b>\n\n"
        f"שם: <b>{display_name}</b>\n"
        f"מזהה: <code>{s['telegram_id']}</code>\n"
        f"סטטוס: <b>{_subscriber_status_label(s.get('status'))}</b>\n\n"
        f"📅 תאריך הצטרפות: {_fmt_dt(stats.get('joined_at'))}\n"
        f"🚪 כניסה ראשונה: {_fmt_dt(stats.get('first_seen_at'))}\n"
        f"⏱️ כניסה אחרונה: {_fmt_dt(stats.get('last_seen_at'))}\n"
        f"🔢 מספר כניסות: {stats.get('login_count', 0)}\n"
        f"📌 פעילות בסיסית: {stats.get('basic_activity', 0)}"
    )

    back_cb = f"SUBS_LIST_PAGE_{page}" if origin == "L" else f"SUBS_SEARCH_PAGE_{page}"

    username = (s.get("username") or "").strip().lstrip("@")
    if username:
        private_chat_button = [
            InlineKeyboardButton("✉️ פתח שיחה פרטית", url=f"https://t.me/{username}")
        ]
    else:
        private_chat_button = [
            InlineKeyboardButton(
                "✉️ פתח שיחה פרטית",
                callback_data=f"SUBS_OPEN_TG_PRIVATE_{origin}_{page}_{subscriber_id}",
            )
        ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 רענן", callback_data=f"SUBS_REFRESH_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("💬 שיחה פרטית", callback_data=f"SUBS_CHAT_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("📜 היסטוריית שיחות", callback_data=f"SUBS_CHAT_HISTORY_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("📊 סטטיסטיקה אישית", callback_data=f"SUBS_STATS_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("⛔ ניהול סטטוס", callback_data=f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("⚠️ הוסף אזהרה", callback_data=f"SUBS_WARN_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("📝 הוסף הערת מנהל", callback_data=f"SUBS_NOTE_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("📒 הערות מנהל", callback_data=f"SUBS_NOTES_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("⬅️ חזרה", callback_data=back_cb)],
        private_chat_button,
    ])

    await _safe_query_edit(update, text=text, reply_markup=kb, parse_mode="HTML")


async def _show_publications_menu(update: Update) -> None:
    await _safe_query_edit(
        update,
        text="📣 <b>פרסום למנויים</b>\n\nבחר פעולה:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 יצירת פרסום", callback_data="SUBS_PUB_CREATE")],
            [InlineKeyboardButton("⏱️ תזמון", callback_data="SUBS_PUB_SCHEDULE")],
            [InlineKeyboardButton("🧹 מחיקה אוטומטית", callback_data="SUBS_PUB_AUTO_DELETE")],
            [InlineKeyboardButton("📚 רשימת פרסומים", callback_data="SUBS_PUB_LIST")],
            [InlineKeyboardButton("📈 סטטיסטיקת פרסום", callback_data="SUBS_PUB_STATS")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_MAIN")],
        ]),
        parse_mode="HTML",
    )


def _clear_publication_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(_PUB_DRAFT, None)
    context.user_data.pop(_PUB_TARGET_OPTIONS, None)
    context.user_data.pop(_PUB_PREVIEW_CONFIRMED, None)
    context.user_data.pop(_PUB_EDIT_ID, None)
    context.user_data.pop(_PUB_BTN_MODE, None)
    context.user_data.pop(_PUB_BTN_EDIT_INDEX, None)
    context.user_data.pop(_PUB_BTN_LABEL_TMP, None)
    context.user_data.pop(_PUB_BTN_VALUE_TMP, None)


async def _clear_publication_preview_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    msg_id = context.user_data.pop(_PUB_PREVIEW_MSG_ID, None)
    chat_id = context.user_data.pop(_PUB_PREVIEW_CHAT_ID, None)
    if not msg_id or not chat_id:
        return
    try:
        await context.bot.delete_message(chat_id=int(chat_id), message_id=int(msg_id))
    except Exception:
        pass


def _catalog_name_by_slug(slug: str | None) -> str | None:
    if not slug:
        return None
    try:
        for cat in get_all_catalogs():
            if str(cat.get("slug") or "") == str(slug):
                return str(cat.get("name") or slug)
    except Exception:
        return None
    return None


def _publication_target_label(target_type: str, target_value: str | None) -> str:
    if target_type == "catalog":
        display = _catalog_name_by_slug(target_value) or (target_value or "-")
        return f"קטלוג: {display}"
    labels = {
        "all": "לכל המשתמשים",
        "active": "משתמשים פעילים",
        "suspended": "משתמשים מושעים",
        "verified": "משתמשים מאומתים",
        "permission": f"הרשאה: {target_value or '-'}",
    }
    return labels.get(target_type, target_type)


def _publication_status_label(status: str) -> str:
    return {
        "draft": "טיוטה",
        "scheduled": "מתוזמן",
        "active": "פעיל",
        "sent": "הסתיים",
        "sending": "שולח",
        "canceled": "בוטל",
    }.get(status, status)


def _fmt_iso(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(ts)


def _recurrence_label(pub: dict) -> str:
    if int(pub.get("is_recurring") or 0) != 1:
        return "לא"
    r_type = str(pub.get("recurrence_type") or "interval").lower()
    minutes = int(pub.get("repeat_every_minutes") or 0)
    if r_type == "daily":
        return f"יומי {pub.get('recurrence_time') or ''}".strip()
    if r_type == "weekly":
        days = str(pub.get("recurrence_weekdays") or "")
        return f"שבועי ({days or '-'}) {pub.get('recurrence_time') or ''}".strip()
    if r_type == "monthly":
        dom = pub.get("recurrence_day_of_month") or "-"
        return f"חודשי יום {dom} {pub.get('recurrence_time') or ''}".strip()
    if minutes == 60:
        return "כל שעה"
    if minutes == 120:
        return "כל שעתיים"
    if minutes == 1440:
        return "כל יום"
    if minutes == 10080:
        return "כל שבוע"
    if minutes > 0:
        return f"כל {minutes} דקות"
    return "מחזורי"


def _draft_preview_text(draft: dict) -> str:
    content = (draft.get("content_text") or "").strip()
    media_type = draft.get("media_type") or "אין"
    target_type = draft.get("target_type") or "all"
    target_value = draft.get("target_value")
    buttons = draft.get("buttons") or []
    schedule = draft.get("schedule_at") or "מיידי"
    recurring = draft.get("recurring_every")
    auto_delete_minutes = int(draft.get("auto_delete_minutes") or 0)
    recurring_text = f"כל {recurring} דקות" if recurring else "לא"
    auto_delete_text = f"אחרי {auto_delete_minutes} דקות" if auto_delete_minutes > 0 else "כבוי"
    recipients = count_publication_recipients(target_type, target_value)
    content_preview = content[:300] if content else "(ללא טקסט)"
    return (
        "🧾 <b>תצוגה מקדימה לפרסום</b>\n\n"
        f"🎯 יעד: <b>{_publication_target_label(target_type, target_value)}</b>\n"
        f"👥 נמענים: <b>{recipients}</b>\n"
        f"🎞️ מדיה: <b>{media_type}</b>\n"
        f"⏱️ תזמון: <b>{schedule}</b>\n"
        f"🔁 מחזורי: <b>{recurring_text}</b>\n"
        f"🧹 מחיקה אוטומטית: <b>{auto_delete_text}</b>\n"
        f"🔘 כפתורים: <b>{len(buttons)}</b>\n\n"
        f"💬 תוכן:\n{content_preview}"
    )


def _publication_targets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 לכל המשתמשים", callback_data="SUBS_PUB_TARGET_all")],
        [InlineKeyboardButton("✅ משתמשים פעילים", callback_data="SUBS_PUB_TARGET_active")],
        [InlineKeyboardButton("⛔ משתמשים מושעים", callback_data="SUBS_PUB_TARGET_suspended")],
        [InlineKeyboardButton("🪪 משתמשים מאומתים", callback_data="SUBS_PUB_TARGET_verified")],
        [InlineKeyboardButton("📂 לפי קטלוג", callback_data="SUBS_PUB_TARGET_catalog")],
        [InlineKeyboardButton("🔐 לפי הרשאה", callback_data="SUBS_PUB_TARGET_permission")],
        [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_PREVIEW")],
    ])


def _publication_preview_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 יעד פרסום", callback_data="SUBS_PUB_TARGET_all")],
        [InlineKeyboardButton("✏️ עריכת תוכן", callback_data="SUBS_PUB_EDIT_CONTENT")],
        [InlineKeyboardButton("🔘 עריכת כפתורים", callback_data="SUBS_PUB_EDIT_BUTTONS")],
        [InlineKeyboardButton("🚀 שליחה מיידית", callback_data="SUBS_PUB_SEND_NOW")],
        [InlineKeyboardButton("⏱️ תזמון / טיימר", callback_data="SUBS_PUB_SCHEDULE")],
        [InlineKeyboardButton("🔁 פרסום מחזורי", callback_data="SUBS_PUB_RECUR_60")],
        [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_PUB_CANCEL_DRAFT")],
    ])


def _draft_publication_keyboard(draft: dict) -> InlineKeyboardMarkup | None:
    buttons = draft.get("buttons") or []
    rows_by_row_index: dict[int, list[InlineKeyboardButton]] = {}
    row_order: list[int] = []
    for idx, b in enumerate(buttons, start=1):
        title = str(b.get("title") or "").strip()
        url = str(b.get("url") or "").strip()
        if not title or not url:
            continue
        row_idx_raw = b.get("row_index")
        try:
            row_idx = int(row_idx_raw) if row_idx_raw is not None else idx
        except Exception:
            row_idx = idx
        if row_idx not in rows_by_row_index:
            rows_by_row_index[row_idx] = []
            row_order.append(row_idx)
        if decode_publication_note(url) is not None:
            rows_by_row_index[row_idx].append(InlineKeyboardButton(title, callback_data=f"SUBS_PUB_NOTE_DRAFT_{idx}"))
            continue
        if url:
            rows_by_row_index[row_idx].append(InlineKeyboardButton(title, url=url))
    rows = [rows_by_row_index[r] for r in row_order if rows_by_row_index.get(r)]
    return InlineKeyboardMarkup(rows) if rows else None


async def _show_publication_note_from_draft(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("הערה לא נמצאה", show_alert=True)
        return

    btn = buttons[idx - 1] or {}
    title = str(btn.get("title") or f"כפתור {idx}")
    note_text = decode_publication_note(str(btn.get("url") or ""))
    if note_text is None:
        await update.callback_query.answer("זהו כפתור קישור", show_alert=True)
        return

    await _safe_query_edit(
        update,
        text=(
            f"📝 <b>{title}</b>\n\n"
            f"{note_text or '(ללא תוכן)'}"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזור", callback_data="SUBS_PUB_NOTE_DRAFT_BACK")],
        ]),
        parse_mode="HTML",
    )


async def _send_real_publication_preview(context: ContextTypes.DEFAULT_TYPE, chat_id: int, draft: dict) -> None:
    await _clear_publication_preview_message(context)

    keyboard = _draft_publication_keyboard(draft)
    content = (draft.get("content_text") or "").strip()
    media_type = str(draft.get("media_type") or "").strip()
    file_id = str(draft.get("file_id") or "").strip()

    preview_msg = None
    try:
        if media_type and file_id:
            if media_type == "photo":
                preview_msg = await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=content or None, reply_markup=keyboard)
            elif media_type == "video":
                preview_msg = await context.bot.send_video(chat_id=chat_id, video=file_id, caption=content or None, reply_markup=keyboard)
            elif media_type == "animation":
                preview_msg = await context.bot.send_animation(chat_id=chat_id, animation=file_id, caption=content or None, reply_markup=keyboard)
            elif media_type == "document":
                preview_msg = await context.bot.send_document(chat_id=chat_id, document=file_id, caption=content or None, reply_markup=keyboard)
            elif media_type == "audio":
                preview_msg = await context.bot.send_audio(chat_id=chat_id, audio=file_id, caption=content or None, reply_markup=keyboard)
            elif media_type == "voice":
                preview_msg = await context.bot.send_voice(chat_id=chat_id, voice=file_id, caption=content or None, reply_markup=keyboard)
            elif media_type == "video_note":
                preview_msg = await context.bot.send_video_note(chat_id=chat_id, video_note=file_id)
                if content or keyboard:
                    preview_msg = await context.bot.send_message(chat_id=chat_id, text=content or "", reply_markup=keyboard)
            elif media_type == "sticker":
                preview_msg = await context.bot.send_sticker(chat_id=chat_id, sticker=file_id)
                if content or keyboard:
                    preview_msg = await context.bot.send_message(chat_id=chat_id, text=content or "", reply_markup=keyboard)
            else:
                preview_msg = await context.bot.send_message(chat_id=chat_id, text=content or "", reply_markup=keyboard)
        else:
            preview_msg = await context.bot.send_message(chat_id=chat_id, text=content or "(ללא טקסט)", reply_markup=keyboard)
    except Exception:
        preview_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ לא ניתן להציג מקדימה את המדיה כרגע. בדוק שהקובץ עדיין זמין.",
        )

    if preview_msg:
        context.user_data[_PUB_PREVIEW_MSG_ID] = preview_msg.message_id
        context.user_data[_PUB_PREVIEW_CHAT_ID] = preview_msg.chat_id


async def _start_publication_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _clear_publication_preview_message(context)
    context.user_data[_PUB_PREVIEW_CONFIRMED] = False
    context.user_data[_PUB_DRAFT] = {
        "title": "פרסום",
        "content_text": "",
        "media_type": None,
        "file_id": None,
        "target_type": "all",
        "target_value": None,
        "buttons": [],
        "schedule_at": None,
        "recurring_every": None,
        "auto_delete_minutes": 0,
    }
    context.user_data[_STATE] = _AWAIT_PUB_CONTENT
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _safe_query_edit(
        update,
        text=(
            "📝 <b>יצירת פרסום</b>\n\n"
            "שלח עכשיו הודעה אחת עם טקסט ו/או מדיה.\n"
            "נתמך: תמונה, וידאו, GIF, מסמך, אודיו, וייס, וידאו עגול.\n\n"
            "לאחר השליחה תיפתח תצוגה מקדימה מלאה."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_PUB_CANCEL_DRAFT")],
        ]),
        parse_mode="HTML",
    )


async def _prompt_publication_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[_STATE] = _AWAIT_PUB_CONTENT
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id
    await _safe_query_edit(
        update,
        text="✏️ שלח מחדש את תוכן הפרסום (טקסט ו/או מדיה).",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
        ]),
        parse_mode="HTML",
    )


async def _prompt_publication_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_publication_buttons_menu(update, context)


async def _show_publication_buttons_screen(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str = "HTML",
) -> None:
    try:
        await _safe_query_edit(
            update,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return
    except Exception:
        pass

    try:
        await update.callback_query.answer()
    except Exception:
        pass

    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception:
        pass


def _publication_buttons_manage_keyboard(buttons: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, btn in enumerate(buttons, start=1):
        title = str(btn.get("title") or f"כפתור {idx}")
        value = str(btn.get("url") or "")
        note_text = decode_publication_note(value)
        if note_text is not None:
            short = (title[:22] + "…") if len(title) > 22 else title
            rows.append([
                InlineKeyboardButton(f"✏️ 📝 {short}", callback_data=f"SUBS_PUB_BTN_EDIT_NOTE_{idx}"),
                InlineKeyboardButton(f"🗑️ 📝 {short}", callback_data=f"SUBS_PUB_BTN_DELETE_{idx}"),
            ])
        else:
            short = (title[:22] + "…") if len(title) > 22 else title
            rows.append([
                InlineKeyboardButton(f"✏️ 🔗 {short}", callback_data=f"SUBS_PUB_BTN_URL_{idx}"),
                InlineKeyboardButton("🗑️", callback_data=f"SUBS_PUB_BTN_DELETE_{idx}"),
            ])

    rows.append([InlineKeyboardButton("➕ הוסף כפתור קישור", callback_data="SUBS_PUB_BTN_ADD_URL")])
    rows.append([InlineKeyboardButton("➕ הוסף כפתור הערה", callback_data="SUBS_PUB_BTN_ADD_NOTE")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_BTN_BACK")])
    return InlineKeyboardMarkup(rows)


async def _show_publication_buttons_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []

    lines = ["🔘 <b>ניהול כפתורי פרסום</b>", ""]
    if not buttons:
        lines.append("אין כפתורים כרגע.")
    else:
        for idx, btn in enumerate(buttons, start=1):
            title = str(btn.get("title") or f"כפתור {idx}")
            value = str(btn.get("url") or "")
            if decode_publication_note(value) is not None:
                lines.append(f"{idx}. 📝 {title}")
            else:
                lines.append(f"{idx}. 🔗 {title}")

    await _show_publication_buttons_screen(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_publication_buttons_manage_keyboard(buttons),
        parse_mode="HTML",
    )


async def _start_publication_button_add(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    context.user_data[_STATE] = _AWAIT_PUB_BTN_LABEL
    context.user_data[_PUB_BTN_MODE] = mode
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id
    context.user_data.pop(_PUB_BTN_LABEL_TMP, None)
    context.user_data.pop(_PUB_BTN_VALUE_TMP, None)
    context.user_data.pop(_PUB_BTN_EDIT_INDEX, None)

    await _safe_query_edit(
        update,
        text="כתוב את שם הכפתור.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
        ]),
        parse_mode="HTML",
    )


async def _show_publication_button_edit_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    idx: int,
    *,
    kind: str,
) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("כפתור לא נמצא", show_alert=True)
        return

    title = str((buttons[idx - 1] or {}).get("title") or f"כפתור {idx}")
    if kind == "note":
        choices = [
            [InlineKeyboardButton("✏️ שינוי שם", callback_data=f"SUBS_PUB_BTN_EDIT_NOTE_NAME_{idx}")],
            [InlineKeyboardButton("📝 שינוי תוכן", callback_data=f"SUBS_PUB_BTN_EDIT_NOTE_VALUE_{idx}")],
        ]
        text = f"✏️ <b>עריכת כפתור הערה</b>\n\nכפתור: <b>{title}</b>\n\nבחר מה לשנות:"
    else:
        choices = [
            [InlineKeyboardButton("✏️ שינוי שם", callback_data=f"SUBS_PUB_BTN_EDIT_URL_NAME_{idx}")],
            [InlineKeyboardButton("🔗 שינוי קישור", callback_data=f"SUBS_PUB_BTN_EDIT_URL_VALUE_{idx}")],
        ]
        text = f"✏️ <b>עריכת כפתור קישור</b>\n\nכפתור: <b>{title}</b>\n\nבחר מה לשנות:"

    choices.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")])
    await _show_publication_buttons_screen(
        update,
        context,
        text=text,
        reply_markup=InlineKeyboardMarkup(choices),
        parse_mode="HTML",
    )


async def _start_publication_button_edit_note_name(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("כפתור לא נמצא", show_alert=True)
        return

    context.user_data[_STATE] = _AWAIT_PUB_BTN_LABEL
    context.user_data[_PUB_BTN_MODE] = "edit_note_name"
    context.user_data[_PUB_BTN_EDIT_INDEX] = idx
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _show_publication_buttons_screen(
        update,
        context,
        text="✏️ <b>עריכת כפתור הערה</b>\n\nשלח שם חדש לכפתור.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
        ]),
        parse_mode="HTML",
    )


async def _start_publication_button_edit_note_value(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("כפתור לא נמצא", show_alert=True)
        return

    context.user_data[_STATE] = _AWAIT_PUB_BTN_VALUE
    context.user_data[_PUB_BTN_MODE] = "edit_note_value"
    context.user_data[_PUB_BTN_EDIT_INDEX] = idx
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _show_publication_buttons_screen(
        update,
        context,
        text="✏️ <b>עריכת כפתור הערה</b>\n\nשלח טקסט הערה חדש.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
        ]),
        parse_mode="HTML",
    )


async def _start_publication_button_edit_url_name(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("כפתור לא נמצא", show_alert=True)
        return

    current = buttons[idx - 1] or {}
    context.user_data[_STATE] = _AWAIT_PUB_BTN_LABEL
    context.user_data[_PUB_BTN_MODE] = "edit_url_name"
    context.user_data[_PUB_BTN_EDIT_INDEX] = idx
    context.user_data[_PUB_BTN_LABEL_TMP] = str(current.get("title") or f"כפתור {idx}")[:50]
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _show_publication_buttons_screen(
        update,
        context,
        text="✏️ <b>עריכת כפתור קישור</b>\n\nשלח שם חדש לכפתור.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
        ]),
        parse_mode="HTML",
    )


async def _start_publication_button_edit_url_value(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("כפתור לא נמצא", show_alert=True)
        return

    current = buttons[idx - 1] or {}
    context.user_data[_STATE] = _AWAIT_PUB_BTN_VALUE
    context.user_data[_PUB_BTN_MODE] = "edit_url_value"
    context.user_data[_PUB_BTN_EDIT_INDEX] = idx
    context.user_data[_PUB_BTN_LABEL_TMP] = str(current.get("title") or f"כפתור {idx}")[:50]
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _show_publication_buttons_screen(
        update,
        context,
        text="✏️ <b>עריכת כפתור קישור</b>\n\nשלח קישור חדש.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
        ]),
        parse_mode="HTML",
    )


async def _start_publication_button_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    await _show_publication_button_edit_choice(update, context, idx, kind="note")


async def _start_publication_button_edit_url(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    await _show_publication_button_edit_choice(update, context, idx, kind="url")


async def _delete_publication_button(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = list(draft.get("buttons") or [])
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("כפתור לא נמצא", show_alert=True)
        return
    buttons.pop(idx - 1)
    draft["buttons"] = buttons
    context.user_data[_PUB_DRAFT] = draft
    context.user_data[_PUB_PREVIEW_CONFIRMED] = False
    await update.callback_query.answer("הכפתור נמחק")
    await _show_publication_buttons_menu(update, context)


async def _show_publication_url_button_hint(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = draft.get("buttons") or []
    if not (1 <= idx <= len(buttons)):
        await update.callback_query.answer("כפתור לא נמצא", show_alert=True)
        return
    value = str((buttons[idx - 1] or {}).get("url") or "")
    if decode_publication_note(value) is not None:
        await update.callback_query.answer("זה כפתור הערה", show_alert=True)
        return
    await update.callback_query.answer("לעריכה לחץ על שם הקישור. למחיקה לחץ על 🗑️")


def _next_row_index_for_new_button(buttons: list[dict], same_row: bool) -> int:
    if not buttons:
        return 1
    last = buttons[-1] or {}
    try:
        last_row = int(last.get("row_index") or len(buttons))
    except Exception:
        last_row = len(buttons)
    if same_row:
        return max(1, last_row)
    return max(1, last_row + 1)


async def _finalize_publication_button_add(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    same_row: bool,
) -> None:
    mode = context.user_data.get(_PUB_BTN_MODE)
    if mode not in {"add_url", "add_note"}:
        await update.callback_query.answer("מצב עריכה לא תקין", show_alert=True)
        return

    label = str(context.user_data.get(_PUB_BTN_LABEL_TMP) or "").strip()
    value = str(context.user_data.get(_PUB_BTN_VALUE_TMP) or "").strip()
    if not label or not value:
        await update.callback_query.answer("הוספת כפתור נכשלה", show_alert=True)
        return

    draft = context.user_data.get(_PUB_DRAFT) or {}
    buttons = list(draft.get("buttons") or [])
    row_index = _next_row_index_for_new_button(buttons, same_row=same_row)
    buttons.append({"title": label[:50], "url": value[:300], "row_index": row_index})
    draft["buttons"] = buttons
    context.user_data[_PUB_DRAFT] = draft
    context.user_data[_PUB_PREVIEW_CONFIRMED] = False

    context.user_data.pop(_STATE, None)
    context.user_data.pop(_PUB_BTN_MODE, None)
    context.user_data.pop(_PUB_BTN_EDIT_INDEX, None)
    context.user_data.pop(_PUB_BTN_LABEL_TMP, None)
    context.user_data.pop(_PUB_BTN_VALUE_TMP, None)

    await update.callback_query.answer("הכפתור נוסף")
    await _show_publication_buttons_menu(update, context)


async def _show_publication_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    await _send_real_publication_preview(context, update.callback_query.message.chat_id, draft)
    context.user_data[_PUB_PREVIEW_CONFIRMED] = True
    rows = [
        [InlineKeyboardButton("🎯 שינוי יעד", callback_data="SUBS_PUB_TARGET_PICK")],
        [InlineKeyboardButton("✏️ עריכת תוכן", callback_data="SUBS_PUB_EDIT_CONTENT")],
        [InlineKeyboardButton("🔘 עריכת כפתורים", callback_data="SUBS_PUB_EDIT_BUTTONS")],
        [InlineKeyboardButton("🧹 מחיקה אוטומטית", callback_data="SUBS_PUB_AUTO_DELETE")],
        [InlineKeyboardButton("🚀 שליחה מיידית", callback_data="SUBS_PUB_SEND_NOW")],
        [InlineKeyboardButton("⏱️ תזמון / טיימר", callback_data="SUBS_PUB_SCHEDULE")],
        [InlineKeyboardButton("🔁 כל שעה", callback_data="SUBS_PUB_RECUR_60")],
        [InlineKeyboardButton("🔁 כל חודש", callback_data="SUBS_PUB_RECUR_MONTH")],
    ]
    if int(context.user_data.get(_PUB_EDIT_ID) or 0) > 0:
        rows.append([InlineKeyboardButton("💾 שמירה", callback_data="SUBS_PUB_SAVE_EDIT")])
    rows.append([InlineKeyboardButton("❌ ביטול", callback_data="SUBS_PUB_CANCEL_DRAFT")])
    await _safe_query_edit(
        update,
        text=_draft_preview_text(draft),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _start_publication_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    pub = get_publication(publication_id)
    if not pub:
        await update.callback_query.answer("פרסום לא נמצא", show_alert=True)
        return

    buttons = list_publication_buttons(publication_id)
    context.user_data[_PUB_EDIT_ID] = publication_id
    context.user_data[_PUB_PREVIEW_CONFIRMED] = True
    context.user_data[_PUB_DRAFT] = {
        "title": pub.get("title") or "פרסום",
        "content_text": pub.get("content_text") or "",
        "media_type": pub.get("media_type"),
        "file_id": pub.get("file_id"),
        "target_type": pub.get("target_type") or "all",
        "target_value": pub.get("target_value"),
        "buttons": [
            {
                "title": b.get("title") or "",
                "url": b.get("url") or "",
                "row_index": b.get("row_index"),
            }
            for b in buttons
        ],
        "auto_delete_minutes": int(pub.get("auto_delete_minutes") or 0),
    }
    await _show_publication_preview(update, context)


async def _save_publication_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
    if pub_id <= 0:
        await update.callback_query.answer("אין פרסום לעריכה", show_alert=True)
        return
    draft = context.user_data.get(_PUB_DRAFT) or {}
    update_publication_record(
        pub_id,
        title=draft.get("title") or "פרסום",
        content_text=draft.get("content_text") or "",
        media_type=draft.get("media_type"),
        file_id=draft.get("file_id"),
        target_type=draft.get("target_type") or "all",
        target_value=draft.get("target_value"),
        auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
    )
    replace_publication_buttons_record(pub_id, draft.get("buttons") or [])
    await _clear_publication_preview_message(context)
    _clear_publication_draft(context)
    await _show_publication_details(update, context, pub_id)


async def _handle_publication_auto_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "SUBS_PUB_AUTO_DELETE":
        draft = context.user_data.get(_PUB_DRAFT) or {}
        if not draft and int(context.user_data.get(_PUB_EDIT_ID) or 0) <= 0:
            return await _show_publications_list(update, context, page=1)
        current = int(draft.get("auto_delete_minutes") or 0)
        await _safe_query_edit(
            update,
            text=(
                "🧹 <b>מחיקה אוטומטית</b>\n\n"
                f"מצב נוכחי: <b>{(str(current) + ' דקות') if current > 0 else 'כבוי'}</b>\n"
                "בחר ערך או שלח מספר דקות בצ׳אט."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("כבוי", callback_data="SUBS_PUB_AUTODEL_SET_0")],
                [InlineKeyboardButton("30 דק׳", callback_data="SUBS_PUB_AUTODEL_SET_30")],
                [InlineKeyboardButton("60 דק׳", callback_data="SUBS_PUB_AUTODEL_SET_60")],
                [InlineKeyboardButton("24 שעות", callback_data="SUBS_PUB_AUTODEL_SET_1440")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_PREVIEW")],
            ]),
            parse_mode="HTML",
        )
        context.user_data[_STATE] = _AWAIT_PUB_AUTO_DELETE
        context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
        context.user_data[_MSG_ID] = update.callback_query.message.message_id
        return

    if data.startswith("SUBS_PUB_AUTODEL_SET_"):
        value = _parse_positive_int(data[len("SUBS_PUB_AUTODEL_SET_"):])
        minutes = int(value or 0)
        draft = context.user_data.get(_PUB_DRAFT) or {}
        draft["auto_delete_minutes"] = minutes
        context.user_data[_PUB_DRAFT] = draft
        pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
        if pub_id > 0:
            update_publication_record(pub_id, auto_delete_minutes=minutes)
            await _apply_auto_delete_to_pending_deliveries(context, pub_id, minutes)
        context.user_data.pop(_STATE, None)
        return await _show_publication_preview(update, context)

    if data.startswith("SUBS_PUB_AUTODEL_APPLY_"):
        payload = data[len("SUBS_PUB_AUTODEL_APPLY_"):]
        parts = payload.split("_", 1)
        if len(parts) != 2:
            await update.callback_query.answer("ערך לא תקין", show_alert=True)
            return
        pub_id = _parse_positive_int(parts[0])
        minutes = int(_parse_positive_int(parts[1]) or 0)
        if pub_id is None:
            await update.callback_query.answer("פרסום לא תקין", show_alert=True)
            return
        update_publication_record(pub_id, auto_delete_minutes=minutes)
        await _apply_auto_delete_to_pending_deliveries(context, pub_id, minutes)
        await update.callback_query.answer("נשמר")
        return await _show_publication_details(update, context, pub_id)

    pub_id = _parse_positive_int(data[len("SUBS_PUB_AUTODEL_"):])
    if pub_id is None:
        await update.callback_query.answer("ערך לא תקין", show_alert=True)
        return
    pub = get_publication(pub_id)
    if not pub:
        await update.callback_query.answer("פרסום לא נמצא", show_alert=True)
        return
    current = int(pub.get("auto_delete_minutes") or 0)
    await _safe_query_edit(
        update,
        text=(
            f"🧹 <b>מחיקה אוטומטית לפרסום #{pub_id}</b>\n\n"
            f"מצב נוכחי: <b>{(str(current) + ' דקות') if current > 0 else 'כבוי'}</b>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("כבוי", callback_data=f"SUBS_PUB_AUTODEL_APPLY_{pub_id}_0")],
            [InlineKeyboardButton("30 דק׳", callback_data=f"SUBS_PUB_AUTODEL_APPLY_{pub_id}_30")],
            [InlineKeyboardButton("60 דק׳", callback_data=f"SUBS_PUB_AUTODEL_APPLY_{pub_id}_60")],
            [InlineKeyboardButton("24 שעות", callback_data=f"SUBS_PUB_AUTODEL_APPLY_{pub_id}_1440")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data=f"SUBS_PUB_VIEW_{pub_id}")],
        ]),
        parse_mode="HTML",
    )


async def _apply_auto_delete_to_pending_deliveries(
    context: ContextTypes.DEFAULT_TYPE,
    publication_id: int,
    minutes: int,
) -> None:
    if publication_id <= 0 or minutes <= 0:
        return

    pending = list_pending_delivery_records(publication_id)
    if not pending:
        return

    delete_at_dt = now_il().replace(tzinfo=None) + timedelta(minutes=minutes)
    delete_at = delete_at_dt.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE subscriber_publication_deliveries
                SET delete_at = ?
                WHERE publication_id = ?
                  AND status = 'pending'
                  AND (delete_at IS NULL OR TRIM(delete_at) = '')
                """,
                (delete_at, publication_id),
            )
            conn.commit()
    except Exception:
        return

    update_publication_record(publication_id, auto_delete_at=delete_at)

    for row in pending:
        delivery_id = int(row.get("id") or 0)
        if delivery_id <= 0:
            continue
        await _schedule_publication_delete_job(context, delivery_id, delete_at_dt)


async def _set_publication_target(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "SUBS_PUB_TARGET_PICK":
        await _safe_query_edit(
            update,
            text="🎯 בחר יעד פרסום:",
            reply_markup=_publication_targets_keyboard(),
            parse_mode="HTML",
        )
        return

    if data.startswith("SUBS_PUB_TARGET_catalog_pick_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_TARGET_catalog_pick_"):])
        options = context.user_data.get(_PUB_TARGET_OPTIONS) or {}
        catalog_slugs = options.get("catalog") or []
        if idx is None or idx > len(catalog_slugs):
            await update.callback_query.answer("בחירה לא תקינה", show_alert=True)
            return
        draft = context.user_data.get(_PUB_DRAFT) or {}
        draft["target_type"] = "catalog"
        draft["target_value"] = catalog_slugs[idx - 1]
        context.user_data[_PUB_DRAFT] = draft
        return await _show_publication_preview(update, context)

    if data.startswith("SUBS_PUB_TARGET_permission_pick_"):
        idx = _parse_positive_int(data[len("SUBS_PUB_TARGET_permission_pick_"):])
        options = context.user_data.get(_PUB_TARGET_OPTIONS) or {}
        permission_values = options.get("permission") or []
        if idx is None or idx > len(permission_values):
            await update.callback_query.answer("בחירה לא תקינה", show_alert=True)
            return
        draft = context.user_data.get(_PUB_DRAFT) or {}
        draft["target_type"] = "permission"
        draft["target_value"] = permission_values[idx - 1]
        context.user_data[_PUB_DRAFT] = draft
        return await _show_publication_preview(update, context)

    target = data[len("SUBS_PUB_TARGET_"):]
    draft = context.user_data.get(_PUB_DRAFT) or {}
    if target in {"all", "active", "suspended", "verified"}:
        draft["target_type"] = target
        draft["target_value"] = None
        context.user_data[_PUB_DRAFT] = draft
        return await _show_publication_preview(update, context)

    if target == "catalog":
        catalogs = get_all_catalogs()
        if not catalogs:
            await update.callback_query.answer("לא נמצאו קטלוגים פעילים", show_alert=True)
            return
        slugs = [str(c.get("slug") or "") for c in catalogs if c.get("slug")]
        context.user_data[_PUB_TARGET_OPTIONS] = {
            **(context.user_data.get(_PUB_TARGET_OPTIONS) or {}),
            "catalog": slugs,
        }
        rows = []
        for i, c in enumerate(catalogs, start=1):
            slug = str(c.get("slug") or "")
            if not slug:
                continue
            title = str(c.get("name") or slug)
            rows.append([InlineKeyboardButton(title[:48], callback_data=f"SUBS_PUB_TARGET_catalog_pick_{i}")])
        rows.append([InlineKeyboardButton("⬅️ חזרה ליעדים", callback_data="SUBS_PUB_TARGET_PICK")])
        await _safe_query_edit(
            update,
            text="📂 בחר קטלוג יעד מתוך הרשימה:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML",
        )
        return

    if target == "permission":
        permissions = list_available_publication_permissions()
        if not permissions:
            await update.callback_query.answer("לא נמצאו הרשאות עם משתמשים", show_alert=True)
            return
        context.user_data[_PUB_TARGET_OPTIONS] = {
            **(context.user_data.get(_PUB_TARGET_OPTIONS) or {}),
            "permission": permissions,
        }
        rows = [
            [InlineKeyboardButton(p[:48], callback_data=f"SUBS_PUB_TARGET_permission_pick_{i}")]
            for i, p in enumerate(permissions, start=1)
        ]
        rows.append([InlineKeyboardButton("⬅️ חזרה ליעדים", callback_data="SUBS_PUB_TARGET_PICK")])
        await _safe_query_edit(
            update,
            text="🔐 בחר הרשאה יעד מתוך הרשימה:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML",
        )
        return

    await update.callback_query.answer("יעד לא תקין", show_alert=True)


def _build_send_payload_from_draft(draft: dict) -> dict:
    return {
        "title": draft.get("title") or "פרסום",
        "content_text": draft.get("content_text") or "",
        "media_type": draft.get("media_type"),
        "file_id": draft.get("file_id"),
        "target_type": draft.get("target_type") or "all",
        "target_value": draft.get("target_value"),
        "buttons": draft.get("buttons") or [],
    }


async def _send_publication_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
        await update.callback_query.answer("יש לפתוח תצוגה מקדימה לפני שליחה.", show_alert=True)
        return
    if not (draft.get("content_text") or draft.get("file_id")):
        await update.callback_query.answer("אין תוכן לפרסום.", show_alert=True)
        return

    payload = _build_send_payload_from_draft(draft)
    pub_id = create_publication_record(
        title=payload["title"],
        content_text=payload["content_text"],
        media_type=payload["media_type"],
        file_id=payload["file_id"],
        target_type=payload["target_type"],
        target_value=payload["target_value"],
        status="sending",
        created_by=update.callback_query.from_user.id,
        auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
        buttons=payload["buttons"],
    )
    if pub_id <= 0:
        await update.callback_query.answer("שגיאה ביצירת פרסום.", show_alert=True)
        return

    started = datetime.utcnow()
    result = await dispatch_publication(context.bot, pub_id)
    await _process_publication_auto_delete(context, pub_id, result)
    elapsed = (datetime.utcnow() - started).total_seconds()
    await _clear_publication_preview_message(context)
    _clear_publication_draft(context)
    try:
        await update.callback_query.answer(
            f"נשלחו: {result.get('sent', 0)} | נכשלו: {result.get('failed', 0)} | {elapsed:.2f}s"
        )
    except Exception:
        pass
    await _show_publication_details(update, context, pub_id)


async def _prompt_publication_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    has_content = bool((draft.get("content_text") or "").strip() or draft.get("file_id"))
    if not has_content:
        await _safe_query_edit(
            update,
            text=(
                "⏱️ <b>תזמון פרסום</b>\n\n"
                "לפני תזמון צריך ליצור פרסום עם תוכן."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 יצירת פרסום", callback_data="SUBS_PUB_CREATE")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
            ]),
            parse_mode="HTML",
        )
        return

    if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
        await _safe_query_edit(
            update,
            text=(
                "⏱️ <b>תזמון פרסום</b>\n\n"
                "לפני תזמון יש לפתוח תצוגה מקדימה פעם אחת כדי לאשר את הטיוטה."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
            ]),
            parse_mode="HTML",
        )
        return

    context.user_data[_STATE] = _AWAIT_PUB_SCHEDULE
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id
    await _safe_query_edit(
        update,
        text=(
            "⏱️ <b>תזמון / טיימר</b>\n\n"
            "בחר מהיר:\n"
            "• בעוד 10 דקות\n"
            "• בעוד שעתיים\n"
            "• בעוד יום\n\n"
            "או שלח תזמון ידני:\n"
            "• כל 5 דקות / כל 10 דקות / כל 1 דקה\n"
            "• חד-פעמי: YYYY-MM-DD HH:MM או DD/MM/YYYY HH:MM\n"
            "• יומי: כל יום HH:MM\n"
            "• שבועי: כל יום שישי HH:MM\n"
            "• ימים מסוימים: ימים שני,רביעי HH:MM\n"
            "• חודשי: כל חודש 15 18:00"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("+10 דקות", callback_data="SUBS_PUB_DELAY_10m")],
            [InlineKeyboardButton("+2 שעות", callback_data="SUBS_PUB_DELAY_2h")],
            [InlineKeyboardButton("+1 יום", callback_data="SUBS_PUB_DELAY_1d")],
            [InlineKeyboardButton("🔁 כל 5 דקות", callback_data="SUBS_PUB_RECUR_5")],
            [InlineKeyboardButton("🔁 כל 10 דקות", callback_data="SUBS_PUB_RECUR_10")],
            [InlineKeyboardButton("🔁 כל שעה", callback_data="SUBS_PUB_RECUR_60")],
            [InlineKeyboardButton("🔁 כל שעתיים", callback_data="SUBS_PUB_RECUR_120")],
            [InlineKeyboardButton("🔁 כל 6 שעות", callback_data="SUBS_PUB_RECUR_360")],
            [InlineKeyboardButton("🔁 כל יום", callback_data="SUBS_PUB_RECUR_1440")],
            [InlineKeyboardButton("🔁 כל שבוע", callback_data="SUBS_PUB_RECUR_10080")],
            [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
        ]),
        parse_mode="HTML",
    )


async def _set_publication_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    suffix = data[len("SUBS_PUB_DELAY_"):]
    now = now_il().replace(tzinfo=None)
    try:
        amount = int(suffix[:-1])
    except (TypeError, ValueError):
        amount = 0

    if amount <= 0:
        await _safe_query_edit(
            update,
            text="⚠️ טיימר לא תקין. נסה שוב.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לתזמון", callback_data="SUBS_PUB_SCHEDULE")],
                [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
            ]),
            parse_mode="HTML",
        )
        return

    if suffix.endswith("m"):
        dt = now + timedelta(minutes=amount)
    elif suffix.endswith("h"):
        dt = now + timedelta(hours=amount)
    elif suffix.endswith("d"):
        dt = now + timedelta(days=amount)
    else:
        await _safe_query_edit(
            update,
            text="⚠️ טיימר לא תקין. נסה שוב.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לתזמון", callback_data="SUBS_PUB_SCHEDULE")],
                [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
            ]),
            parse_mode="HTML",
        )
        return

    await _save_scheduled_publication(update, context, dt)


async def _set_publication_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    minutes = _parse_positive_int(data[len("SUBS_PUB_RECUR_"):])
    if minutes is None:
        await _safe_query_edit(
            update,
            text="⚠️ מחזור לא תקין. נסה שוב.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לתזמון", callback_data="SUBS_PUB_SCHEDULE")],
                [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
            ]),
            parse_mode="HTML",
        )
        return
    if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
        await _safe_query_edit(
            update,
            text="⚠️ יש לפתוח תצוגה מקדימה לפני הפעלה מחזורית.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
            ]),
            parse_mode="HTML",
        )
        return
    draft = context.user_data.get(_PUB_DRAFT) or {}
    if not (draft.get("content_text") or draft.get("file_id")):
        await _safe_query_edit(
            update,
            text="⚠️ אין תוכן לפרסום.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 יצירת פרסום", callback_data="SUBS_PUB_CREATE")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
            ]),
            parse_mode="HTML",
        )
        return

    payload = _build_send_payload_from_draft(draft)
    next_dt = now_il().replace(tzinfo=None) + timedelta(minutes=minutes)
    next_run_at = next_dt.strftime("%Y-%m-%d %H:%M:%S")
    edit_pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
    if edit_pub_id > 0:
        ok = update_publication_record(
            edit_pub_id,
            title=payload["title"],
            content_text=payload["content_text"],
            media_type=payload["media_type"],
            file_id=payload["file_id"],
            target_type=payload["target_type"],
            target_value=payload["target_value"],
            status="active",
            is_recurring=1,
            repeat_every_minutes=minutes,
            recurrence_type="interval",
            recurrence_weekdays=None,
            recurrence_day_of_month=None,
            recurrence_time=None,
            next_run_at=next_run_at,
            scheduled_at=next_run_at,
            auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
        )
        if not ok:
            await _safe_query_edit(
                update,
                text="⚠️ שגיאה בעדכון פרסום מחזורי.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ חזרה לתזמון", callback_data="SUBS_PUB_SCHEDULE")],
                    [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                ]),
                parse_mode="HTML",
            )
            return
        replace_publication_buttons_record(edit_pub_id, payload["buttons"])
        pub_id = edit_pub_id
    else:
        pub_id = create_publication_record(
            title=payload["title"],
            content_text=payload["content_text"],
            media_type=payload["media_type"],
            file_id=payload["file_id"],
            target_type=payload["target_type"],
            target_value=payload["target_value"],
            status="active",
            created_by=update.callback_query.from_user.id,
            is_recurring=1,
            repeat_every_minutes=minutes,
            recurrence_type="interval",
            next_run_at=next_run_at,
            auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
            buttons=payload["buttons"],
        )
    if pub_id <= 0:
        await _safe_query_edit(
            update,
            text="⚠️ שגיאה ביצירת פרסום מחזורי.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לתזמון", callback_data="SUBS_PUB_SCHEDULE")],
                [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
            ]),
            parse_mode="HTML",
        )
        return
    await _schedule_recurring_job(context, pub_id, next_dt)
    context.user_data.pop(_STATE, None)
    await _clear_publication_preview_message(context)
    _clear_publication_draft(context)
    await _safe_query_edit(
        update,
        text=f"✅ פרסום מחזורי הופעל.\nתדירות: כל {minutes} דקות.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 פתח פרסום", callback_data=f"SUBS_PUB_VIEW_{pub_id}")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
        ]),
        parse_mode="HTML",
    )


async def _set_publication_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
        await update.callback_query.answer("יש לפתוח תצוגה מקדימה לפני הפעלה.", show_alert=True)
        return
    draft = context.user_data.get(_PUB_DRAFT) or {}
    if not (draft.get("content_text") or draft.get("file_id")):
        await update.callback_query.answer("אין תוכן לפרסום", show_alert=True)
        return

    now = now_il().replace(tzinfo=None)
    day_of_month = now.day
    hour = now.hour
    minute = now.minute
    recurrence_time = f"{hour:02d}:{minute:02d}"
    next_month = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
    next_month = (next_month + timedelta(days=32)).replace(day=min(day_of_month, 28))
    next_run_at = next_month.strftime("%Y-%m-%d %H:%M:%S")

    payload = _build_send_payload_from_draft(draft)
    edit_pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
    if edit_pub_id > 0:
        ok = update_publication_record(
            edit_pub_id,
            title=payload["title"],
            content_text=payload["content_text"],
            media_type=payload["media_type"],
            file_id=payload["file_id"],
            target_type=payload["target_type"],
            target_value=payload["target_value"],
            status="active",
            is_recurring=1,
            repeat_every_minutes=43200,
            recurrence_type="monthly",
            recurrence_day_of_month=day_of_month,
            recurrence_time=recurrence_time,
            next_run_at=next_run_at,
            scheduled_at=next_run_at,
            auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
        )
        if not ok:
            await update.callback_query.answer("שגיאה בעדכון", show_alert=True)
            return
        replace_publication_buttons_record(edit_pub_id, payload["buttons"])
        pub_id = edit_pub_id
    else:
        pub_id = create_publication_record(
            title=payload["title"],
            content_text=payload["content_text"],
            media_type=payload["media_type"],
            file_id=payload["file_id"],
            target_type=payload["target_type"],
            target_value=payload["target_value"],
            status="active",
            created_by=update.callback_query.from_user.id,
            is_recurring=1,
            repeat_every_minutes=43200,
            recurrence_type="monthly",
            recurrence_day_of_month=day_of_month,
            recurrence_time=recurrence_time,
            next_run_at=next_run_at,
            auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
            buttons=payload["buttons"],
        )
    if pub_id <= 0:
        await update.callback_query.answer("שגיאה ביצירת פרסום חודשי", show_alert=True)
        return

    await _schedule_recurring_job(context, pub_id, datetime.strptime(next_run_at, "%Y-%m-%d %H:%M:%S"))
    context.user_data.pop(_STATE, None)
    await _clear_publication_preview_message(context)
    _clear_publication_draft(context)
    await _safe_query_edit(
        update,
        text=f"✅ פרסום חודשי הופעל.\nהפעלה ראשונה: {next_run_at}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 פתח פרסום", callback_data=f"SUBS_PUB_VIEW_{pub_id}")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
        ]),
        parse_mode="HTML",
    )


async def _save_scheduled_publication(update: Update, context: ContextTypes.DEFAULT_TYPE, run_dt: datetime) -> None:
    if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
        await _safe_query_edit(
            update,
            text="⚠️ יש לפתוח תצוגה מקדימה לפני תזמון.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
            ]),
            parse_mode="HTML",
        )
        return
    draft = context.user_data.get(_PUB_DRAFT) or {}
    if not (draft.get("content_text") or draft.get("file_id")):
        await _safe_query_edit(
            update,
            text="⚠️ אין תוכן לפרסום.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 יצירת פרסום", callback_data="SUBS_PUB_CREATE")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
            ]),
            parse_mode="HTML",
        )
        return
    payload = _build_send_payload_from_draft(draft)
    run_at = run_dt.strftime("%Y-%m-%d %H:%M:%S")
    edit_pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
    if edit_pub_id > 0:
        ok = update_publication_record(
            edit_pub_id,
            title=payload["title"],
            content_text=payload["content_text"],
            media_type=payload["media_type"],
            file_id=payload["file_id"],
            target_type=payload["target_type"],
            target_value=payload["target_value"],
            status="scheduled",
            is_recurring=0,
            repeat_every_minutes=None,
            recurrence_type=None,
            recurrence_weekdays=None,
            recurrence_day_of_month=None,
            recurrence_time=None,
            scheduled_at=run_at,
            next_run_at=run_at,
            auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
        )
        if not ok:
            pub_id = 0
        else:
            replace_publication_buttons_record(edit_pub_id, payload["buttons"])
            pub_id = edit_pub_id
    else:
        pub_id = create_publication_record(
            title=payload["title"],
            content_text=payload["content_text"],
            media_type=payload["media_type"],
            file_id=payload["file_id"],
            target_type=payload["target_type"],
            target_value=payload["target_value"],
            status="scheduled",
            created_by=update.callback_query.from_user.id,
            scheduled_at=run_at,
            next_run_at=run_at,
            auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
            buttons=payload["buttons"],
        )
    if pub_id <= 0:
        await _safe_query_edit(
            update,
            text="⚠️ שגיאה בשמירת תזמון.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לתזמון", callback_data="SUBS_PUB_SCHEDULE")],
                [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
            ]),
            parse_mode="HTML",
        )
        return
    await _schedule_one_time_job(context, pub_id, run_dt)
    context.user_data.pop(_STATE, None)
    await _clear_publication_preview_message(context)
    _clear_publication_draft(context)
    await _show_publication_details(update, context, pub_id)


async def _show_publications_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    term = (context.user_data.get(_PUB_SEARCH_TERM) or "").strip()
    per_page = 8
    rows_data, total = list_publications_paged(page=page, per_page=per_page, search=term)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    if page != 1 and (not rows_data):
        rows_data, total = list_publications_paged(page=1, per_page=per_page, search=term)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = 1

    rows = []
    lines = [f"📚 <b>רשימת פרסומים</b>", f"עמוד {page}/{total_pages} • סה״כ {total}", ""]
    for idx, p in enumerate(rows_data, start=1):
        status = _publication_status_label(str(p.get("status") or ""))
        raw_title = str(p.get("title") or "").strip()
        title = raw_title or "פרסום ללא כותרת"
        content_text = (p.get("content_text") or "").strip()
        content_preview = " ".join(content_text.split())[:52]
        media_type = str(p.get("media_type") or "").strip()
        media_label = {
            "photo": "תמונה",
            "video": "וידאו",
            "animation": "אנימציה",
            "document": "מסמך",
            "audio": "אודיו",
            "voice": "הודעה קולית",
            "video_note": "סרטון עגול",
            "sticker": "סטיקר",
        }.get(media_type, "מדיה") if media_type else ""
        media_fallback = media_label if media_type else ""
        list_index = ((page - 1) * per_page) + idx
        normalized_title = "" if raw_title in {"פרסום", "פרסום ללא כותרת"} else raw_title
        target_type = str(p.get("target_type") or "all")
        target_value = p.get("target_value")
        target_short = {
            "all": "לכולם",
            "verified": "למאומתים",
            "active": "לפעילים",
            "trial": "בניסיון",
        }.get(target_type, "מותאם")
        if target_type == "permission" and target_value:
            target_short = f"הרשאה {target_value}"
        elif target_type == "subscriber" and target_value:
            target_short = f"משתמש {target_value}"
        target = _publication_target_label(str(p.get("target_type") or "all"), p.get("target_value"))
        next_run = _fmt_iso(str(p.get("next_run_at") or ""))
        last_sent = _fmt_iso(str(p.get("last_sent_at") or ""))
        display_name = normalized_title or content_preview or f"פרסום {list_index}"
        identity = f"{display_name} · {media_fallback}" if media_fallback else display_name
        lines.append(
            f"{list_index}. <b>{identity[:52]}</b> | {status}\n"
            f"יעד: {target} | שליחה הבאה: {next_run} | שליחה אחרונה: {last_sent}"
        )
        button_name = display_name[:14]
        if media_fallback:
            button_title = f"{button_name} · {media_fallback}"
        else:
            button_title = button_name
        button_prefix = "" if button_name == f"פרסום {list_index}" else f"פרסום {list_index} · "
        rows.append([InlineKeyboardButton(f"📄 {button_prefix}{button_title} · {target_short[:10]}", callback_data=f"SUBS_PUB_VIEW_{p['id']}")])

    if not rows_data:
        lines.append("אין פרסומים להצגה.")

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"SUBS_PUB_LIST_PAGE_{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("הבא ➡️", callback_data=f"SUBS_PUB_LIST_PAGE_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("🔍 חיפוש", callback_data="SUBS_PUB_SEARCH")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")])

    await _safe_query_edit(
        update,
        text="\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_publication_details(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    p = get_publication(publication_id)
    if not p:
        await update.callback_query.answer("פרסום לא נמצא", show_alert=True)
        return
    status = str(p.get("status") or "")
    title = str(p.get("title") or "").strip() or "פרסום ללא כותרת"
    if title.upper().startswith(("TIME_", "AUTO_DELETE_", "TEST_")):
        title = "פרסום"
    pending_targets = count_publication_recipients(str(p.get("target_type") or "all"), p.get("target_value")) if status in {"scheduled", "active"} else 0
    auto_delete_minutes = int(p.get("auto_delete_minutes") or 0)
    text = (
        f"📄 <b>פרסום #{publication_id}</b>\n\n"
        f"כותרת: <b>{title}</b>\n"
        f"מצב: <b>{_publication_status_label(status)}</b>\n"
        f"מחזוריות: <b>{_recurrence_label(p)}</b>\n"
        f"יעד: <b>{_publication_target_label(str(p.get('target_type') or 'all'), p.get('target_value'))}</b>\n"
        f"שליחה מתוכננת: <b>{_fmt_iso(p.get('scheduled_at'))}</b>\n"
        f"שליחה הבאה: <b>{_fmt_iso(p.get('next_run_at'))}</b>\n"
        f"שליחה אחרונה: <b>{_fmt_iso(p.get('last_sent_at'))}</b>\n"
        f"מחיקה אוטומטית: <b>{(str(auto_delete_minutes) + ' דקות') if auto_delete_minutes > 0 else 'כבוי'}</b>\n"
        f"מוצלח: <b>{p.get('sent_success_count') or 0}</b> | נכשל: <b>{p.get('sent_fail_count') or 0}</b>\n"
        f"ממתין: <b>{pending_targets}</b>\n"
        f"יעד כולל: <b>{p.get('total_targets') or 0}</b>"
    )
    rows = [[InlineKeyboardButton("✏️ עריכה מלאה", callback_data=f"SUBS_PUB_EDIT_{publication_id}")]]
    rows.append([InlineKeyboardButton("🚀 שלח עכשיו", callback_data=f"SUBS_PUB_RUN_{publication_id}")])
    if status in {"scheduled", "active"}:
        rows.append([InlineKeyboardButton("⛔ עצור", callback_data=f"SUBS_PUB_CANCEL_{publication_id}")])
    if status == "canceled" and int(p.get("is_recurring") or 0) == 1:
        rows.append([InlineKeyboardButton("▶️ הפעלה מחדש", callback_data=f"SUBS_PUB_RESUME_{publication_id}")])
    rows.append([InlineKeyboardButton("🧹 מחיקה אוטומטית", callback_data=f"SUBS_PUB_AUTODEL_{publication_id}")])
    if int(p.get("sent_success_count") or 0) > 0:
        rows.append([InlineKeyboardButton("🗑️ מחיקה מיידית של פרסום שנשלח", callback_data=f"SUBS_PUB_PURGE_{publication_id}")])
    rows.append([InlineKeyboardButton("📈 סטטיסטיקה", callback_data=f"SUBS_PUB_STATS_VIEW_{publication_id}")])
    rows.append([InlineKeyboardButton("🗑️ מחיקה", callback_data=f"SUBS_PUB_DELETE_{publication_id}")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_LIST")])
    await _safe_query_edit(update, text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")


async def _delete_publication(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    await _cancel_publication_jobs(context, publication_id)
    ok = remove_publication(publication_id)
    await update.callback_query.answer("נמחק" if ok else "מחיקה נכשלה", show_alert=not ok)
    await _show_publications_list(update, context, page=1)


async def _purge_sent_publication_messages(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    deliveries = list_pending_delivery_records(publication_id)
    if not deliveries:
        await update.callback_query.answer("אין הודעות פעילות למחיקה", show_alert=True)
        return await _show_publication_details(update, context, publication_id)

    deleted = 0
    failed = 0
    for d in deliveries:
        delivery_id = int(d.get("id") or 0)
        chat_id = int(d.get("telegram_id") or 0)
        message_id = int(d.get("message_id") or 0)
        if delivery_id <= 0 or chat_id <= 0 or message_id <= 0:
            if delivery_id > 0:
                mark_delivery_status(delivery_id, "failed")
                _PUB_DELETE_JOBS.pop(delivery_id, None)
            failed += 1
            continue

        if context.job_queue:
            job_name = f"pub_del_{delivery_id}"
            for job in context.job_queue.jobs():
                if job.name == job_name:
                    job.schedule_removal()
            _PUB_DELETE_JOBS.pop(delivery_id, None)

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            mark_delivery_status(delivery_id, "deleted")
            deleted += 1
        except Exception:
            mark_delivery_status(delivery_id, "failed")
            failed += 1

    await update.callback_query.answer(f"נמחקו: {deleted} | נכשלו: {failed}")
    await _show_publication_details(update, context, publication_id)


async def _run_publication_now(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    result = await dispatch_publication(context.bot, publication_id)
    await _process_publication_auto_delete(context, publication_id, result)
    await update.callback_query.answer("נשלח" if result.get("ok") else "שליחה נכשלה", show_alert=not result.get("ok"))
    await _show_publication_details(update, context, publication_id)


async def _cancel_publication(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    await _cancel_publication_jobs(context, publication_id)
    update_publication_record(publication_id, status="canceled", next_run_at=None)
    await update.callback_query.answer("הפרסום בוטל")
    await _show_publication_details(update, context, publication_id)


async def _resume_publication(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    p = get_publication(publication_id)
    if not p:
        await update.callback_query.answer("פרסום לא נמצא", show_alert=True)
        return
    if int(p.get("is_recurring") or 0) != 1:
        await update.callback_query.answer("רק למחזורי ניתן להפעיל מחדש", show_alert=True)
        return
    next_run = compute_next_run(p, from_time=now_il().replace(tzinfo=None))
    if not next_run:
        await update.callback_query.answer("תדירות לא תקינה", show_alert=True)
        return
    update_publication_record(publication_id, status="active", next_run_at=next_run)
    await _schedule_recurring_job(context, publication_id, datetime.strptime(next_run, "%Y-%m-%d %H:%M:%S"))
    await update.callback_query.answer("הופעל מחדש")
    await _show_publication_details(update, context, publication_id)


async def _prompt_publication_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[_STATE] = _AWAIT_PUB_SEARCH
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id
    await _safe_query_edit(
        update,
        text="🔍 שלח מילה לחיפוש בפרסומים (כותרת/תוכן). שלח '-' לאיפוס.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_LIST")],
        ]),
        parse_mode="HTML",
    )


async def _show_publication_stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows, total = list_publications_paged(page=1, per_page=8, search="")
    lines = ["📈 <b>סטטיסטיקות פרסום</b>", f"סה״כ פרסומים: <b>{total}</b>", "", "בחר פרסום:"]
    kb_rows = []
    for p in rows:
        status = _publication_status_label(str(p.get("status") or ""))
        raw_title = str(p.get("title") or "").strip()
        content_text = " ".join(str(p.get("content_text") or "").split())
        media_type = str(p.get("media_type") or "").strip()
        media_label = {
            "photo": "תמונה",
            "video": "וידאו",
            "animation": "אנימציה",
            "document": "מסמך",
            "audio": "אודיו",
            "voice": "הודעה קולית",
            "video_note": "סרטון עגול",
            "sticker": "סטיקר",
        }.get(media_type, "")

        if raw_title and raw_title not in {"פרסום", "פרסום ללא כותרת"}:
            identity = raw_title
        elif content_text:
            identity = content_text[:28]
        else:
            identity = media_label or "פרסום ללא כותרת"

        button_text = f"{identity[:36]} · {status}"
        kb_rows.append([
            InlineKeyboardButton(button_text, callback_data=f"SUBS_PUB_STATS_VIEW_{p['id']}")
        ])
    kb_rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")])
    await _safe_query_edit(update, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="HTML")


async def _show_publication_stats_for_one(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    stats = publication_stats(publication_id)
    pub = stats.get("publication") or {}
    events = stats.get("events") or {}
    sent_success_effective = int(stats.get("sent_success_effective") or 0)
    sent_fail_effective = int(stats.get("sent_fail_effective") or 0)
    pending_targets = count_publication_recipients(str(pub.get("target_type") or "all"), pub.get("target_value")) if str(pub.get("status") or "") in {"scheduled", "active"} else 0
    raw_title = str(pub.get("title") or "").strip()
    content_text = " ".join(str(pub.get("content_text") or "").split())
    display_name = raw_title if raw_title and raw_title not in {"פרסום", "פרסום ללא כותרת"} else (content_text[:36] if content_text else "פרסום")
    button_clicks = int(events.get("button_click", 0)) + int(events.get("click", 0))
    text = (
        f"📈 <b>סטטיסטיקה לפרסום</b>\n"
        f"שם: <b>{display_name}</b>\n\n"
        f"יעד: <b>{_publication_target_label(str(pub.get('target_type') or 'all'), pub.get('target_value'))}</b>\n"
        f"זמן שליחה אחרון: <b>{_fmt_iso(pub.get('last_sent_at'))}</b>\n"
        f"זמן שליחה הבא: <b>{_fmt_iso(pub.get('next_run_at'))}</b>\n"
        f"ממתין: <b>{pending_targets}</b>\n"
        f"נשלחו: <b>{events.get('sent', 0)}</b>\n"
        f"נכשלו: <b>{events.get('failed', 0)}</b>\n"
        f"לחיצות כפתורים: <b>{button_clicks}</b>\n"
        f"מונה הצלחות: <b>{sent_success_effective}</b>\n"
        f"מונה כישלונות: <b>{sent_fail_effective}</b>"
    )
    await _safe_query_edit(
        update,
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 איפוס סטטיסטיקה", callback_data=f"SUBS_PUB_STATS_RESET_CONFIRM_{publication_id}")],
            [InlineKeyboardButton("⬅️ חזרה לפרסום", callback_data=f"SUBS_PUB_VIEW_{publication_id}")],
        ]),
        parse_mode="HTML",
    )


async def _bootstrap_publication_jobs(context: ContextTypes.DEFAULT_TYPE) -> None:
    rows, _ = list_publications_paged(page=1, per_page=200)
    now = now_il().replace(tzinfo=None)
    for p in rows:
        pub_id = int(p.get("id") or 0)
        if pub_id <= 0:
            continue
        status = str(p.get("status") or "")
        if status == "scheduled" and p.get("scheduled_at"):
            try:
                run_at = datetime.strptime(str(p.get("scheduled_at")), "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if run_at <= now:
                await _run_publication_job(context, pub_id)
            else:
                await _schedule_one_time_job(context, pub_id, run_at)
        elif status == "active" and int(p.get("is_recurring") or 0) == 1:
            minutes = int(p.get("repeat_every_minutes") or 0)
            if minutes > 0:
                next_run_raw = str(p.get("next_run_at") or "").strip()
                next_run_dt = None
                if next_run_raw:
                    try:
                        next_run_dt = datetime.strptime(next_run_raw, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        next_run_dt = None
                if next_run_dt is None:
                    next_run_dt = now + timedelta(minutes=minutes)
                    update_publication_record(pub_id, next_run_at=next_run_dt.strftime("%Y-%m-%d %H:%M:%S"))
                await _schedule_recurring_job(context, pub_id, next_run_dt)
    await _bootstrap_publication_delete_jobs(context)


async def bootstrap_publication_jobs_on_startup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Initialize scheduled/recurring publication jobs after bot startup."""
    await _bootstrap_publication_jobs(context)


async def _run_publication_job(context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    result = await dispatch_publication(context.bot, publication_id)
    await _process_publication_auto_delete(context, publication_id, result)


async def _schedule_one_time_job(context: ContextTypes.DEFAULT_TYPE, publication_id: int, run_at: datetime) -> None:
    await _cancel_publication_jobs(context, publication_id)
    if not context.job_queue:
        return
    run_when = run_at.replace(tzinfo=IL_TZ) if run_at.tzinfo is None else run_at.astimezone(IL_TZ)
    job = context.job_queue.run_once(
        _publication_job_callback,
        when=run_when,
        data={"publication_id": publication_id, "mode": "once"},
        name=f"pub_once_{publication_id}",
    )
    _PUB_SCHEDULE_JOBS[publication_id] = job.name


async def _schedule_recurring_job(
    context: ContextTypes.DEFAULT_TYPE,
    publication_id: int,
    run_at: datetime,
    *,
    cancel_delete_jobs: bool = True,
) -> None:
    await _cancel_publication_jobs(context, publication_id, cancel_delete_jobs=cancel_delete_jobs)
    if not context.job_queue:
        return
    run_when = run_at.replace(tzinfo=IL_TZ) if run_at.tzinfo is None else run_at.astimezone(IL_TZ)
    job = context.job_queue.run_once(
        _publication_job_callback,
        when=run_when,
        data={"publication_id": publication_id, "mode": "repeat"},
        name=f"pub_repeat_{publication_id}",
    )
    _PUB_RECURRING_JOBS[publication_id] = job.name


async def _cancel_publication_jobs(
    context: ContextTypes.DEFAULT_TYPE,
    publication_id: int,
    *,
    cancel_delete_jobs: bool = True,
) -> None:
    if context.job_queue:
        for job in context.job_queue.jobs():
            if job.name in {f"pub_once_{publication_id}", f"pub_repeat_{publication_id}"}:
                job.schedule_removal()

        if cancel_delete_jobs:
            deliveries = list_pending_delivery_records(publication_id)
            for d in deliveries:
                delivery_id = int(d.get("id") or 0)
                if delivery_id <= 0:
                    continue
                job_name = f"pub_del_{delivery_id}"
                for job in context.job_queue.jobs():
                    if job.name == job_name:
                        job.schedule_removal()
                _PUB_DELETE_JOBS.pop(delivery_id, None)
    _PUB_SCHEDULE_JOBS.pop(publication_id, None)
    _PUB_RECURRING_JOBS.pop(publication_id, None)


async def _publication_job_callback(job_context) -> None:
    data = job_context.job.data or {}
    publication_id = int(data.get("publication_id") or 0)
    mode = str(data.get("mode") or "")
    if publication_id <= 0:
        return
    publication = get_publication(publication_id)
    if not publication:
        return

    status = str(publication.get("status") or "")
    is_recurring = int(publication.get("is_recurring") or 0) == 1

    if mode == "once" and status != "scheduled":
        return
    if mode == "repeat" and (status != "active" or not is_recurring):
        return

    result = await dispatch_publication(job_context.bot, publication_id)
    await _process_publication_auto_delete(job_context, publication_id, result)

    if mode == "repeat":
        publication = get_publication(publication_id)
        if not publication:
            return
        if str(publication.get("status") or "") != "active":
            return
        next_run_raw = str(publication.get("next_run_at") or "").strip()
        if not next_run_raw:
            return
        try:
            next_run_dt = datetime.strptime(next_run_raw, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return
        await _schedule_recurring_job(job_context, publication_id, next_run_dt, cancel_delete_jobs=False)


async def _bootstrap_publication_delete_jobs(context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = list_pending_deletion_records()
    for row in rows:
        delivery_id = int(row.get("id") or 0)
        if delivery_id <= 0:
            continue
        delete_at = str(row.get("delete_at") or "")
        try:
            run_at = datetime.strptime(delete_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            run_at = now_il().replace(tzinfo=None)
        await _schedule_publication_delete_job(context, delivery_id, run_at)


async def _schedule_publication_delete_job(context: ContextTypes.DEFAULT_TYPE, delivery_id: int, run_at: datetime) -> None:
    if not context.job_queue:
        return
    run_when = run_at.replace(tzinfo=IL_TZ) if run_at.tzinfo is None else run_at.astimezone(IL_TZ)
    job_name = f"pub_del_{delivery_id}"
    for job in context.job_queue.jobs():
        if job.name == job_name:
            job.schedule_removal()
    job = context.job_queue.run_once(
        _publication_delete_job_callback,
        when=run_when,
        data={"delivery_id": delivery_id},
        name=job_name,
    )
    _PUB_DELETE_JOBS[delivery_id] = job.name


async def _publication_delete_job_callback(job_context) -> None:
    delivery_id = int((job_context.job.data or {}).get("delivery_id") or 0)
    if delivery_id <= 0:
        return
    delivery = get_delivery_record(delivery_id)
    if not delivery:
        _PUB_DELETE_JOBS.pop(delivery_id, None)
        return
    if str(delivery.get("status") or "") != "pending":
        _PUB_DELETE_JOBS.pop(delivery_id, None)
        return
    chat_id = int(delivery.get("telegram_id") or 0)
    message_id = int(delivery.get("message_id") or 0)
    if chat_id <= 0 or message_id <= 0:
        mark_delivery_status(delivery_id, "failed")
        _PUB_DELETE_JOBS.pop(delivery_id, None)
        return
    try:
        await job_context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        mark_delivery_status(delivery_id, "deleted")
    except Exception:
        mark_delivery_status(delivery_id, "failed")
    _PUB_DELETE_JOBS.pop(delivery_id, None)


async def _process_publication_auto_delete(context: ContextTypes.DEFAULT_TYPE, publication_id: int, result: dict) -> None:
    deliveries = result.get("deliveries") or []
    if not deliveries:
        return
    pub = get_publication(publication_id)
    if not pub:
        return
    minutes = int(pub.get("auto_delete_minutes") or 0)
    delete_at_dt = None
    delete_at = None
    if minutes > 0:
        delete_at_dt = now_il().replace(tzinfo=None) + timedelta(minutes=minutes)
        delete_at = delete_at_dt.strftime("%Y-%m-%d %H:%M:%S")
        update_publication_record(publication_id, auto_delete_at=delete_at)
    for item in deliveries:
        delivery_id = create_publication_delivery_record(
            publication_id=publication_id,
            subscriber_id=int(item.get("subscriber_id") or 0) or None,
            telegram_id=int(item.get("telegram_id") or 0),
            message_id=int(item.get("message_id") or 0),
            delete_at=delete_at,
        )
        if delivery_id > 0 and delete_at_dt is not None:
            await _schedule_publication_delete_job(context, delivery_id, delete_at_dt)


def _parse_user_datetime(raw: str) -> datetime | None:
    normalized = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(normalized, fmt)
        except Exception:
            continue
    return None


def _next_time_today_or_tomorrow(now: datetime, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def _next_weekday_time(now: datetime, weekday: int, hour: int, minute: int) -> datetime:
    current = now.weekday()
    days_ahead = (weekday - current) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate


def _parse_manual_recurrence(raw: str, now: datetime) -> dict | None:
    text = " ".join(raw.strip().lower().split())

    m_interval_he = re.fullmatch(r"כל\s+(\d{1,5})\s*(?:דקה|דקות|דק|דק׳)", text)
    if m_interval_he:
        every_minutes = int(m_interval_he.group(1))
        if every_minutes > 0:
            return {
                "repeat_every_minutes": every_minutes,
                "recurrence_type": "interval",
                "recurrence_weekdays": None,
                "recurrence_day_of_month": None,
                "recurrence_time": None,
                "first_run_dt": now + timedelta(minutes=every_minutes),
            }
        return None

    m_interval_en = re.fullmatch(r"(?:every|each)\s+(\d{1,5})\s*(?:minute|minutes|min)", text)
    if m_interval_en:
        every_minutes = int(m_interval_en.group(1))
        if every_minutes > 0:
            return {
                "repeat_every_minutes": every_minutes,
                "recurrence_type": "interval",
                "recurrence_weekdays": None,
                "recurrence_day_of_month": None,
                "recurrence_time": None,
                "first_run_dt": now + timedelta(minutes=every_minutes),
            }
        return None

    m_daily = re.fullmatch(r"(?:כל יום|daily)\s+(\d{1,2}):(\d{2})", text)
    if m_daily:
        hour = int(m_daily.group(1))
        minute = int(m_daily.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return {
                "repeat_every_minutes": 1440,
                "recurrence_type": "daily",
                "recurrence_weekdays": None,
                "recurrence_day_of_month": None,
                "recurrence_time": f"{hour:02d}:{minute:02d}",
                "first_run_dt": _next_time_today_or_tomorrow(now, hour, minute),
            }
        return None

    weekday_map = {
        "ראשון": 6,
        "שני": 0,
        "שלישי": 1,
        "רביעי": 2,
        "חמישי": 3,
        "שישי": 4,
        "שבת": 5,
    }

    m_weekly_he = re.fullmatch(r"כל יום\s+(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)\s+(\d{1,2}):(\d{2})", text)
    if m_weekly_he:
        weekday_name = m_weekly_he.group(1)
        hour = int(m_weekly_he.group(2))
        minute = int(m_weekly_he.group(3))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            weekday = weekday_map[weekday_name]
            return {
                "repeat_every_minutes": 10080,
                "recurrence_type": "weekly",
                "recurrence_weekdays": str(weekday),
                "recurrence_day_of_month": None,
                "recurrence_time": f"{hour:02d}:{minute:02d}",
                "first_run_dt": _next_weekday_time(now, weekday, hour, minute),
            }
        return None

    m_multi_weekdays = re.fullmatch(r"ימים\s+([א-ת, ]+)\s+(\d{1,2}):(\d{2})", text)
    if m_multi_weekdays:
        names_raw = m_multi_weekdays.group(1)
        hour = int(m_multi_weekdays.group(2))
        minute = int(m_multi_weekdays.group(3))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        day_tokens = [x.strip() for x in names_raw.split(",") if x.strip()]
        weekdays: list[int] = []
        for token in day_tokens:
            if token in weekday_map:
                weekdays.append(weekday_map[token])
        weekdays = sorted(set(weekdays))
        if not weekdays:
            return None
        first_run = min(_next_weekday_time(now, wd, hour, minute) for wd in weekdays)
        return {
            "repeat_every_minutes": 10080,
            "recurrence_type": "weekly",
            "recurrence_weekdays": ",".join(str(x) for x in weekdays),
            "recurrence_day_of_month": None,
            "recurrence_time": f"{hour:02d}:{minute:02d}",
            "first_run_dt": first_run,
        }

    m_weekly_en = re.fullmatch(r"(?:weekly|every week)\s+(\d{1,2}):(\d{2})", text)
    if m_weekly_en:
        hour = int(m_weekly_en.group(1))
        minute = int(m_weekly_en.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return {
                "repeat_every_minutes": 10080,
                "recurrence_type": "weekly",
                "recurrence_weekdays": str(now.weekday()),
                "recurrence_day_of_month": None,
                "recurrence_time": f"{hour:02d}:{minute:02d}",
                "first_run_dt": _next_weekday_time(now, now.weekday(), hour, minute),
            }
        return None

    m_monthly = re.fullmatch(r"כל חודש\s+(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if m_monthly:
        day_of_month = int(m_monthly.group(1))
        hour = int(m_monthly.group(2))
        minute = int(m_monthly.group(3))
        if 1 <= day_of_month <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59:
            first = now.replace(day=min(day_of_month, 28), hour=hour, minute=minute, second=0, microsecond=0)
            if first <= now:
                first = (first.replace(day=1) + timedelta(days=32)).replace(day=min(day_of_month, 28))
            return {
                "repeat_every_minutes": 43200,
                "recurrence_type": "monthly",
                "recurrence_weekdays": None,
                "recurrence_day_of_month": day_of_month,
                "recurrence_time": f"{hour:02d}:{minute:02d}",
                "first_run_dt": first,
            }
        return None

    return None


async def _prompt_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[_STATE] = _AWAIT_SEARCH
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _safe_query_edit(
        update,
        text="🔍 <b>חיפוש מנויים</b>\n\nשלח שם, יוזרניים או מזהה טלגרם:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_LIST")],
        ]),
        parse_mode="HTML",
    )


async def _show_search_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 1,
) -> None:
    term = (context.user_data.get(_SEARCH_TERM) or "").strip()
    if not term:
        return await _prompt_search(update, context)

    per_page = 10
    total = count_subscribers_by_search(term)

    if total == 0:
        await _safe_query_edit(
            update,
            text=f"🔍 <b>תוצאות חיפוש</b>\n\nלא נמצאו תוצאות עבור: <b>{term}</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 חיפוש חדש", callback_data="SUBS_SEARCH")],
                [InlineKeyboardButton("⬅️ חזרה לרשימה", callback_data="SUBS_LIST")],
            ]),
            parse_mode="HTML",
        )
        return

    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    subscribers = find_subscribers_page(term=term, page=page, per_page=per_page)

    rows = []
    for s in subscribers:
        display_name = s.get("full_name") or (f"@{s['username']}" if s.get("username") else str(s["telegram_id"]))
        rows.append([
            InlineKeyboardButton(
                f"👤 {display_name}",
                callback_data=f"SUBS_CARD_S_{page}_{s['id']}",
            )
        ])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"SUBS_SEARCH_PAGE_{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("הבא ➡️", callback_data=f"SUBS_SEARCH_PAGE_{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton("🔍 חיפוש חדש", callback_data="SUBS_SEARCH")])
    rows.append([InlineKeyboardButton("⬅️ חזרה לרשימה", callback_data="SUBS_LIST")])

    await _safe_query_edit(
        update,
        text=f"🔍 <b>תוצאות חיפוש</b>\n<b>{term}</b>\nעמוד {page}/{total_pages} • סה״כ {total}",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


def _parse_card_payload(data: str, prefix: str):
    try:
        suffix = data[len(prefix):]
        parts = suffix.split("_", 2)
        if len(parts) == 3:
            origin = parts[0]
            page = int(parts[1])
            subscriber_id = int(parts[2])
        elif len(parts) == 2:
            # Backward compatibility: SUBS_CARD_{page}_{subscriber_id}
            origin = "L"
            page = int(parts[0])
            subscriber_id = int(parts[1])
        elif len(parts) == 1:
            # Backward compatibility: SUBS_CARD_{subscriber_id}
            origin = "L"
            page = 1
            subscriber_id = int(parts[0])
        else:
            return None
        if origin not in {"L", "S"} or page <= 0 or subscriber_id <= 0:
            return None
        return origin, page, subscriber_id
    except (TypeError, ValueError):
        return None


def _parse_chat_payload(data: str, prefix: str):
    try:
        suffix = data[len(prefix):]
        parts = suffix.split("_", 3)
        if len(parts) != 4:
            return None
        origin = parts[0]
        page = int(parts[1])
        subscriber_id = int(parts[2])
        chat_id = int(parts[3])
        if origin not in {"L", "S"} or page <= 0 or subscriber_id <= 0 or chat_id < 0:
            return None
        return origin, page, subscriber_id, chat_id
    except (TypeError, ValueError):
        return None


def _parse_history_payload(data: str, prefix: str):
    try:
        suffix = data[len(prefix):]
        parts = suffix.split("_", 3)
        if len(parts) != 4:
            return None
        origin = parts[0]
        page = int(parts[1])
        subscriber_id = int(parts[2])
        history_page = int(parts[3])
        if origin not in {"L", "S"} or page <= 0 or subscriber_id <= 0 or history_page <= 0:
            return None
        return origin, page, subscriber_id, history_page
    except (TypeError, ValueError):
        return None


def _parse_media_chat_payload(data: str, prefix: str):
    try:
        suffix = data[len(prefix):]
        parts = suffix.split("_", 4)
        if len(parts) != 5:
            return None
        origin = parts[0]
        page = int(parts[1])
        subscriber_id = int(parts[2])
        chat_id = int(parts[3])
        msg_id = int(parts[4])
        if origin not in {"L", "S"} or page <= 0 or subscriber_id <= 0 or chat_id <= 0 or msg_id <= 0:
            return None
        return origin, page, subscriber_id, chat_id, msg_id
    except (TypeError, ValueError):
        return None


def _parse_media_history_payload(data: str, prefix: str):
    try:
        suffix = data[len(prefix):]
        parts = suffix.split("_", 5)
        if len(parts) != 6:
            return None
        origin = parts[0]
        page = int(parts[1])
        subscriber_id = int(parts[2])
        history_page = int(parts[3])
        chat_id = int(parts[4])
        msg_id = int(parts[5])
        if (
            origin not in {"L", "S"}
            or page <= 0
            or subscriber_id <= 0
            or history_page <= 0
            or chat_id <= 0
            or msg_id <= 0
        ):
            return None
        return origin, page, subscriber_id, history_page, chat_id, msg_id
    except (TypeError, ValueError):
        return None


def _is_not_modified(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


async def _safe_query_edit(
    update: Update,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str = "HTML",
) -> None:
    try:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except BadRequest as exc:
        if _is_not_modified(exc):
            try:
                await update.callback_query.answer("ℹ️ אין שינוי להצגה.")
            except Exception:
                pass
            return
        raise


async def _safe_bot_edit(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str = "HTML",
) -> bool:
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except BadRequest as exc:
        if _is_not_modified(exc):
            return True
        return False
    except Exception:
        return False


def _card_back_callback(origin: str, page: int) -> str:
    return f"SUBS_LIST_PAGE_{page}" if origin == "L" else f"SUBS_SEARCH_PAGE_{page}"


def _fmt_dt(ts) -> str:
    if not ts:
        return "-"
    try:
        return f"{ts[8:10]}.{ts[5:7]}.{ts[:4]} {ts[11:16]}"
    except Exception:
        return str(ts)


def _subscriber_status_label(status: str | None) -> str:
    return {
        "active": "פעיל",
        "suspended": "מושעה",
        "blocked": "חסום",
    }.get((status or "").lower(), "לא ידוע")


def _pack_media_meta(media_type: str, caption: str | None) -> str:
    payload = {
        "media_type": media_type,
        "caption": caption or "",
    }
    return _SUBS_MEDIA_META_PREFIX + json.dumps(payload, ensure_ascii=False)


def _unpack_media_meta(message_text: str | None):
    if not message_text or not isinstance(message_text, str):
        return None
    prefix = None
    if message_text.startswith(_SUBS_MEDIA_META_PREFIX):
        prefix = _SUBS_MEDIA_META_PREFIX
    elif message_text.startswith(_SUBS_MEDIA_META_PREFIX_LEGACY):
        prefix = _SUBS_MEDIA_META_PREFIX_LEGACY
    if not prefix:
        return None
    raw = message_text[len(prefix):]
    try:
        data = json.loads(raw)
        media_type = str(data.get("media_type") or "")
        caption = str(data.get("caption") or "")
        if not media_type:
            return None
        return {
            "media_type": media_type,
            "caption": caption,
        }
    except Exception:
        return None


def _extract_message_media(message) -> dict | None:
    if not message:
        return None
    caption = getattr(message, "caption", None)

    if getattr(message, "photo", None):
        return {"media_type": "photo", "file_id": message.photo[-1].file_id, "caption": caption}
    if getattr(message, "video", None):
        return {"media_type": "video", "file_id": message.video.file_id, "caption": caption}
    if getattr(message, "document", None):
        return {"media_type": "document", "file_id": message.document.file_id, "caption": caption}
    if getattr(message, "voice", None):
        return {"media_type": "voice", "file_id": message.voice.file_id, "caption": caption}
    if getattr(message, "audio", None):
        return {"media_type": "audio", "file_id": message.audio.file_id, "caption": caption}
    if getattr(message, "animation", None):
        return {"media_type": "animation", "file_id": message.animation.file_id, "caption": caption}
    if getattr(message, "video_note", None):
        return {"media_type": "video_note", "file_id": message.video_note.file_id, "caption": caption}
    if getattr(message, "sticker", None):
        return {"media_type": "sticker", "file_id": message.sticker.file_id, "caption": caption}
    return None


def _media_label(media_type: str) -> str:
    labels = {
        "photo": "📷 תמונה",
        "video": "🎥 וידאו",
        "document": "📄 מסמך",
        "voice": "🎤 הודעה קולית",
        "audio": "🎵 אודיו",
        "animation": "🎞️ אנימציה",
        "video_note": "🔵 וידאו עגול",
        "sticker": "😊 סטיקר",
    }
    return labels.get(media_type, "🗂️ מדיה")


async def _clear_open_media_preview(context: ContextTypes.DEFAULT_TYPE, panel_chat_id: int | None) -> None:
    msg_id = context.user_data.get(_SUBS_MEDIA_PREVIEW_MSG_ID)
    chat_id = context.user_data.get(_SUBS_MEDIA_PREVIEW_CHAT_ID)
    if not msg_id or not chat_id:
        return
    if panel_chat_id and int(chat_id) != int(panel_chat_id):
        return
    try:
        await context.bot.delete_message(chat_id=int(chat_id), message_id=int(msg_id))
    except Exception:
        pass
    finally:
        context.user_data.pop(_SUBS_MEDIA_PREVIEW_MSG_ID, None)
        context.user_data.pop(_SUBS_MEDIA_PREVIEW_CHAT_ID, None)


async def _send_media_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    media_type: str,
    file_id: str,
    caption: str | None,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    kwargs = {
        "chat_id": chat_id,
        "reply_markup": reply_markup,
    }
    if media_type == "photo":
        return await context.bot.send_photo(photo=file_id, caption=caption or None, **kwargs)
    if media_type == "video":
        return await context.bot.send_video(video=file_id, caption=caption or None, **kwargs)
    if media_type == "document":
        return await context.bot.send_document(document=file_id, caption=caption or None, **kwargs)
    if media_type == "voice":
        return await context.bot.send_voice(voice=file_id, caption=caption or None, **kwargs)
    if media_type == "audio":
        return await context.bot.send_audio(audio=file_id, caption=caption or None, **kwargs)
    if media_type == "animation":
        return await context.bot.send_animation(animation=file_id, caption=caption or None, **kwargs)
    if media_type == "video_note":
        return await context.bot.send_video_note(video_note=file_id, **kwargs)
    if media_type == "sticker":
        return await context.bot.send_sticker(sticker=file_id, **kwargs)
    return None


async def _open_chat_screen(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_CHAT_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    subscriber = get_subscriber_card(subscriber_id)
    if not subscriber:
        await update.callback_query.answer("⚠️ מנוי לא נמצא.", show_alert=True)
        return

    open_chat = get_open_subscriber_chat(subscriber_id)
    if open_chat:
        chat_id = int(open_chat.get("id") or 0)
    else:
        chats = list_subscriber_chats(subscriber_id)
        chat_id = int(chats[0].get("id") or 0) if chats else 0
    await _render_chat_screen(update, origin, page, subscriber_id, chat_id)


async def _show_chat_screen(update: Update, data: str) -> None:
    payload = _parse_chat_payload(data, "SUBS_CHAT_VIEW_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id, chat_id = payload
    await _render_chat_screen(update, origin, page, subscriber_id, chat_id)


async def _close_chat_screen(update: Update, data: str) -> None:
    payload = _parse_chat_payload(data, "SUBS_CHAT_CLOSE_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id, chat_id = payload
    from services.subscriber_chat_service import close_chat

    if chat_id <= 0:
        await update.callback_query.answer("⚠️ אין שיחה פתוחה לסגירה.", show_alert=True)
        return await _render_chat_screen(update, origin, page, subscriber_id, chat_id)

    close_chat(chat_id)
    subscriber = get_subscriber_card(subscriber_id)
    if subscriber:
        try:
            await update.get_bot().send_message(
                chat_id=subscriber["telegram_id"],
                text=(
                    "✅ השיחה עם צוות הבוט נסגרה.\n"
                    "תודה על שיתוף הפעולה."
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 הפעל בוט מחדש", callback_data="RESTART_BOT_PENDING"),
                ]]),
            )
        except Exception:
            pass
    await _render_chat_screen(update, origin, page, subscriber_id, chat_id)


async def _render_chat_screen(
    update: Update,
    origin: str,
    page: int,
    subscriber_id: int,
    chat_id: int,
) -> None:
    text, kb = _compose_chat_screen(origin, page, subscriber_id, chat_id)
    if not text:
        await update.callback_query.answer("⚠️ שיחה לא נמצאה.", show_alert=True)
        return
    await _safe_query_edit(update, text=text, reply_markup=kb, parse_mode="HTML")


def _compose_chat_screen(origin: str, page: int, subscriber_id: int, chat_id: int):
    subscriber = get_subscriber_card(subscriber_id)
    if not subscriber:
        return None, None

    chat = get_subscriber_chat(chat_id) if chat_id > 0 else None

    messages = get_subscriber_chat_history(chat_id) if chat else []
    display_name = subscriber.get("full_name") or (f"@{subscriber['username']}" if subscriber.get("username") else str(subscriber["telegram_id"]))
    status = "🟢 פתוחה" if chat and chat.get("is_open") else "🔴 סגורה"

    lines = [
        f"💬 <b>שיחה עם {display_name}</b>",
        f"סטטוס: <b>{status}</b>",
        "",
    ]
    for m in messages[-20:]:
        role = "🛡️ מנהל" if m.get("sender_role") == "admin" else "👤 מנוי"
        media_meta = _unpack_media_meta(m.get("message_text"))
        if media_meta and m.get("file_id"):
            media_caption = media_meta.get("caption") or ""
            media_title = _media_label(media_meta.get("media_type") or "")
            caption_preview = f" | {media_caption[:80]}" if media_caption else ""
            lines.append(f"{role}: {media_title}{caption_preview} <i>({_fmt_dt(m.get('created_at'))})</i>")
        else:
            lines.append(f"{role}: {m.get('message_text') or ''} <i>({_fmt_dt(m.get('created_at'))})</i>")
    if not messages:
        lines.append("אין הודעות עדיין.")

    rows = []
    rows.append([InlineKeyboardButton("✉️ שלח הודעה", callback_data=f"SUBS_CHAT_SEND_{origin}_{page}_{subscriber_id}_{chat_id}")])
    if chat and chat.get("is_open"):
        rows.append([InlineKeyboardButton("🔒 סגור שיחה", callback_data=f"SUBS_CHAT_CLOSE_{origin}_{page}_{subscriber_id}_{chat_id}")])
    for m in messages[-20:]:
        media_meta = _unpack_media_meta(m.get("message_text"))
        if media_meta and m.get("file_id") and m.get("id"):
            rows.append([
                InlineKeyboardButton(
                    f"{_media_label(media_meta.get('media_type') or '')} · פתח",
                    callback_data=f"SUBS_MEDIA_VIEW_CHAT_{origin}_{page}_{subscriber_id}_{chat_id}_{m['id']}",
                )
            ])
    rows.append([InlineKeyboardButton("🔄 רענן", callback_data=f"SUBS_CHAT_VIEW_{origin}_{page}_{subscriber_id}_{chat_id}")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _prompt_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_chat_payload(data, "SUBS_CHAT_SEND_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id, chat_id = payload

    admin_id = update.callback_query.from_user.id
    effective_chat_id = chat_id

    existing_chat = get_subscriber_chat(chat_id) if chat_id > 0 else None
    if not existing_chat or not existing_chat.get("is_open"):
        effective_chat_id = open_subscriber_chat(subscriber_id=subscriber_id, admin_id=admin_id)
        subscriber = get_subscriber_card(subscriber_id)
        if subscriber:
            try:
                await context.bot.send_message(
                    chat_id=subscriber["telegram_id"],
                    text=(
                        "📩 נפתחה שיחה בינך לבין צוות הבוט.\n"
                        "כעת ניתן להשיב ישירות להודעות.\n"
                        "תודה."
                    ),
                )
            except Exception:
                pass

    context.user_data[_STATE] = _AWAIT_CHAT_MSG
    context.user_data[_SUB_ORIGIN] = origin
    context.user_data[_SUB_PAGE] = page
    context.user_data[_SUB_ID] = subscriber_id
    context.user_data[_SUB_CHAT_ID] = effective_chat_id
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _safe_query_edit(
        update,
        text="✉️ <b>שלח הודעה למנוי</b>\n\nכתוב הודעה:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_CHAT_VIEW_{origin}_{page}_{subscriber_id}_{effective_chat_id}")],
        ]),
        parse_mode="HTML",
    )


async def _show_chat_history_screen(
    update: Update,
    origin: str,
    page: int,
    subscriber_id: int,
    history_page: int = 1,
) -> None:
    subscriber = get_subscriber_card(subscriber_id)
    if not subscriber:
        await update.callback_query.answer("⚠️ מנוי לא נמצא.", show_alert=True)
        return

    chats = list_subscriber_chats(subscriber_id)
    all_messages = []
    for c in chats:
        msgs = get_subscriber_chat_history(c["id"])
        for m in msgs:
            all_messages.append({
                "chat_id": c["id"],
                "sender_role": m.get("sender_role"),
                "message_text": m.get("message_text") or "(ללא טקסט)",
                "file_id": m.get("file_id"),
                "created_at": m.get("created_at"),
                "id": m.get("id") or 0,
            })

    all_messages.sort(key=lambda x: (x.get("created_at") or "", x.get("id") or 0))

    per_page = 15
    total = len(all_messages)
    total_pages = max(1, (total + per_page - 1) // per_page)
    history_page = max(1, min(history_page, total_pages))

    start = (history_page - 1) * per_page
    end = start + per_page
    page_messages = all_messages[start:end]

    lines = [
        "📜 <b>היסטוריית שיחות מלאה</b>",
        f"הודעות: <b>{total}</b> | עמוד {history_page}/{total_pages}",
        "",
    ]

    if not page_messages:
        lines.append("ההיסטוריה ריקה.")
    else:
        media_rows = []
        for m in page_messages:
            role = "🛡️ מנהל" if m.get("sender_role") == "admin" else "👤 מנוי"
            media_meta = _unpack_media_meta(m.get("message_text"))
            if media_meta and m.get("file_id") and m.get("id"):
                media_caption = media_meta.get("caption") or ""
                media_title = _media_label(media_meta.get("media_type") or "")
                caption_preview = f" | {media_caption[:80]}" if media_caption else ""
                lines.append(
                    f"{role}: {media_title}{caption_preview} | <i>{_fmt_dt(m.get('created_at'))}</i>"
                )
                media_rows.append([
                    InlineKeyboardButton(
                        f"{media_title} · פתח",
                        callback_data=(
                            f"SUBS_MEDIA_VIEW_H_{origin}_{page}_{subscriber_id}_{history_page}_{m['chat_id']}_{m['id']}"
                        ),
                    )
                ])
            else:
                lines.append(
                    f"{role}: {m.get('message_text')} | <i>{_fmt_dt(m.get('created_at'))}</i>"
                )

    rows = []
    if total_pages > 1:
        nav = []
        if history_page > 1:
            nav.append(
                InlineKeyboardButton(
                    "⬅️ הקודם",
                    callback_data=f"SUBS_CHAT_HISTORY_PAGE_{origin}_{page}_{subscriber_id}_{history_page - 1}",
                )
            )
        if history_page < total_pages:
            nav.append(
                InlineKeyboardButton(
                    "הבא ➡️",
                    callback_data=f"SUBS_CHAT_HISTORY_PAGE_{origin}_{page}_{subscriber_id}_{history_page + 1}",
                )
            )
        if nav:
            rows.append(nav)

    rows.append([InlineKeyboardButton("🔄 רענן", callback_data=f"SUBS_CHAT_HISTORY_PAGE_{origin}_{page}_{subscriber_id}_{history_page}")])
    if 'media_rows' in locals() and media_rows:
        rows.extend(media_rows)
    rows.append([InlineKeyboardButton("🗑️ איפוס היסטוריה", callback_data=f"SUBS_CHAT_RESET_CONFIRM_{origin}_{page}_{subscriber_id}")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")])

    await _safe_query_edit(
        update,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _confirm_reset_chat_history(update: Update, origin: str, page: int, subscriber_id: int) -> None:
    await _safe_query_edit(
        update,
        text="האם לאפס את היסטוריית השיחות של המנוי?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן", callback_data=f"SUBS_CHAT_RESET_DO_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_CHAT_HISTORY_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


async def _do_reset_chat_history(update: Update, origin: str, page: int, subscriber_id: int) -> None:
    clear_subscriber_chat_history(subscriber_id)
    await update.callback_query.answer("✅ היסטוריית השיחות אופסה.")
    await _show_chat_history_screen(update, origin, page, subscriber_id, 1)


async def _show_personal_stats(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_STATS_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    stats = get_subscriber_personal_statistics(subscriber_id)

    text = (
        "📊 <b>סטטיסטיקה אישית</b>\n\n"
        f"📅 תאריך הצטרפות: <b>{_fmt_dt(stats.get('joined_at'))}</b>\n"
        f"🚪 כניסה ראשונה: <b>{_fmt_dt(stats.get('first_seen_at'))}</b>\n"
        f"⏱️ כניסה אחרונה: <b>{_fmt_dt(stats.get('last_seen_at'))}</b>\n"
        f"🔢 מספר כניסות: <b>{stats.get('login_count', 0)}</b>\n"
        f"📌 פעילות בסיסית: <b>{stats.get('basic_activity', 0)}</b>\n"
        f"🧾 אירועי פעילות: <b>{stats.get('activity_events', 0)}</b>\n"
        f"📤 הודעות שנשלחו למנוי: <b>{stats.get('messages_sent_to_subscriber', 0)}</b>\n"
        f"📥 הודעות שהתקבלו ממנו: <b>{stats.get('messages_received_from_subscriber', 0)}</b>\n"
        f"📣 פרסומים שנשלחו אליו: <b>{stats.get('publications_sent', 0)}</b>\n"
        f"🔘 לחיצות על כפתורי פרסום: <b>{stats.get('publication_button_clicks', 0)}</b>\n"
        f"⚠️ אזהרות: <b>{stats.get('warnings_count', 0)}</b>\n"
        f"📝 הערות מנהל: <b>{stats.get('admin_notes_count', 0)}</b>"
    )

    await _safe_query_edit(
        update,
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 רענן", callback_data=f"SUBS_STATS_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("📒 הערות מנהל", callback_data=f"SUBS_NOTES_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("🧹 איפוס סטטיסטיקה", callback_data=f"SUBS_STATS_RESET_CONFIRM_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


def _parse_admin_note_payload(raw_payload: str | None) -> tuple[str, str, str]:
    raw = str(raw_payload or "")
    if not raw:
        return "", "", ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            note = str(data.get("note") or "")
            admin_name = str(data.get("admin_name") or "")
            created_at = str(data.get("created_at") or "")
            return note, admin_name, created_at
    except Exception:
        pass
    return raw, "", ""


async def _show_subscriber_admin_notes(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_NOTES_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload

    s = get_subscriber_card(subscriber_id)
    if not s:
        await update.callback_query.answer("⚠️ מנוי לא נמצא.", show_alert=True)
        return

    entries = get_subscriber_stats_activity(subscriber_id=subscriber_id, limit=120)
    notes = [e for e in entries if str(e.get("event_key") or "") == "admin_note"]

    display_name = s.get("full_name") or (f"@{s['username']}" if s.get("username") else str(s["telegram_id"]))
    lines = [f"📒 <b>הערות מנהל</b>", f"מנוי: <b>{display_name}</b>", ""]
    if not notes:
        lines.append("אין הערות מנהל למנוי זה.")
    else:
        for idx, n in enumerate(notes[:20], start=1):
            note_text, admin_name, created_at = _parse_admin_note_payload(n.get("payload"))
            ts = _fmt_dt(created_at or n.get("created_at"))
            author = admin_name or "מנהל"
            snippet = (note_text or "").strip()
            if len(snippet) > 220:
                snippet = snippet[:220] + "..."
            lines.append(f"{idx}. <b>{author}</b> | <i>{ts}</i>")
            lines.append(snippet or "(ללא תוכן)")
            lines.append("")

    await _safe_query_edit(
        update,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 רענן", callback_data=f"SUBS_NOTES_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("📝 הוסף הערת מנהל", callback_data=f"SUBS_NOTE_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("🧹 איפוס הערות מנהל", callback_data=f"SUBS_NOTES_RESET_CONFIRM_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


async def _confirm_reset_subscriber_admin_notes(update: Update, origin: str, page: int, subscriber_id: int) -> None:
    await _safe_query_edit(
        update,
        text=(
            "🧹 <b>איפוס הערות מנהל</b>\n\n"
            "האם למחוק את כל הערות המנהל של מנוי זה?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, מחק", callback_data=f"SUBS_NOTES_RESET_DO_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_NOTES_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


async def _do_reset_subscriber_admin_notes(update: Update, origin: str, page: int, subscriber_id: int) -> None:
    deleted = clear_subscriber_admin_notes(subscriber_id)
    await update.callback_query.answer(f"נמחקו {deleted} הערות")
    await _show_subscriber_admin_notes(update, f"SUBS_NOTES_{origin}_{page}_{subscriber_id}")


async def _show_subscriber_media_from_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
) -> None:
    payload = _parse_media_chat_payload(data, "SUBS_MEDIA_VIEW_CHAT_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id, chat_id, msg_id = payload
    messages = get_subscriber_chat_history(chat_id)
    target = None
    for m in messages:
        if int(m.get("id") or 0) == msg_id:
            target = m
            break
    if not target:
        await update.callback_query.answer("⚠️ מדיה לא נמצאה.", show_alert=True)
        return
    media_meta = _unpack_media_meta(target.get("message_text"))
    file_id = target.get("file_id")
    if not media_meta or not file_id:
        await update.callback_query.answer("⚠️ הודעה זו אינה מדיה.", show_alert=True)
        return

    await _clear_open_media_preview(context, update.callback_query.message.chat_id)
    preview = await _send_media_message(
        context,
        chat_id=update.callback_query.message.chat_id,
        media_type=media_meta.get("media_type") or "",
        file_id=file_id,
        caption=media_meta.get("caption"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזור", callback_data=f"SUBS_MEDIA_BACK_CHAT_{origin}_{page}_{subscriber_id}_{chat_id}")]
        ]),
    )
    if preview:
        context.user_data[_SUBS_MEDIA_PREVIEW_MSG_ID] = preview.message_id
        context.user_data[_SUBS_MEDIA_PREVIEW_CHAT_ID] = preview.chat_id
    await update.callback_query.answer()


async def _show_subscriber_media_from_history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
) -> None:
    payload = _parse_media_history_payload(data, "SUBS_MEDIA_VIEW_H_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id, history_page, chat_id, msg_id = payload
    messages = get_subscriber_chat_history(chat_id)
    target = None
    for m in messages:
        if int(m.get("id") or 0) == msg_id:
            target = m
            break
    if not target:
        await update.callback_query.answer("⚠️ מדיה לא נמצאה.", show_alert=True)
        return
    media_meta = _unpack_media_meta(target.get("message_text"))
    file_id = target.get("file_id")
    if not media_meta or not file_id:
        await update.callback_query.answer("⚠️ הודעה זו אינה מדיה.", show_alert=True)
        return

    await _clear_open_media_preview(context, update.callback_query.message.chat_id)
    preview = await _send_media_message(
        context,
        chat_id=update.callback_query.message.chat_id,
        media_type=media_meta.get("media_type") or "",
        file_id=file_id,
        caption=media_meta.get("caption"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזור", callback_data=f"SUBS_MEDIA_BACK_H_{origin}_{page}_{subscriber_id}_{history_page}")]
        ]),
    )
    if preview:
        context.user_data[_SUBS_MEDIA_PREVIEW_MSG_ID] = preview.message_id
        context.user_data[_SUBS_MEDIA_PREVIEW_CHAT_ID] = preview.chat_id
    await update.callback_query.answer()


async def _back_from_subscriber_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    try:
        await update.callback_query.message.delete()
    except Exception:
        pass
    context.user_data.pop(_SUBS_MEDIA_PREVIEW_MSG_ID, None)
    context.user_data.pop(_SUBS_MEDIA_PREVIEW_CHAT_ID, None)
    await update.callback_query.answer()


async def _confirm_reset_personal_stats(update: Update, origin: str, page: int, subscriber_id: int) -> None:
    await _safe_query_edit(
        update,
        text=(
            "🧹 <b>איפוס סטטיסטיקה אישית</b>\n\n"
            "פעולה זו תאפס רק את שדות הסטטיסטיקה של המנוי.\n"
            "פרטי זהות, סטטוס, צ'אטים והיסטוריה לא יימחקו."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, אפס", callback_data=f"SUBS_STATS_RESET_DO_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_STATS_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


async def _do_reset_personal_stats(update: Update, origin: str, page: int, subscriber_id: int) -> None:
    ok = reset_personal_stats(subscriber_id)
    await update.callback_query.answer("✅ הסטטיסטיקה אופסה." if ok else "❌ איפוס נכשל.", show_alert=not ok)
    if ok:
        try:
            track_subscriber_activity(
                subscriber_id=subscriber_id,
                event_key="stats_reset",
                payload="admin_reset",
                increment_basic_activity=False,
            )
        except Exception:
            pass
    await _show_personal_stats(update, f"SUBS_STATS_{origin}_{page}_{subscriber_id}")


async def _confirm_reset_global_stats(update: Update) -> None:
    await _safe_query_edit(
        update,
        text=(
            "🧹 <b>איפוס סטטיסטיקה כללית (פעולות)</b>\n\n"
            "האיפוס יאפס רק מוני פעולות (הודעות, אירועים, לחיצות).\n"
            "הוא לא מוחק מנויים, ולא משנה סטטוס פעיל/מושעה/חסום."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, אפס", callback_data="SUBS_GLOBAL_STATS_RESET_DO")],
            [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_GLOBAL_STATS")],
        ]),
        parse_mode="HTML",
    )


async def _do_reset_global_stats(update: Update) -> None:
    ok = reset_global_stats_actions()
    await update.callback_query.answer("✅ סטטיסטיקת הפעולות אופסה." if ok else "❌ איפוס נכשל.", show_alert=not ok)
    await _show_stats(update)


async def _confirm_reset_publication_stats(update: Update, publication_id: int) -> None:
    await _safe_query_edit(
        update,
        text=(
            f"🧹 <b>איפוס סטטיסטיקה לפרסום #{publication_id}</b>\n\n"
            "האיפוס יאפס רק מוני ביצועים ולחיצות של הפרסום הזה.\n"
            "הוא לא מוחק פרסום ולא משנה את היעד או התוכן."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, אפס", callback_data=f"SUBS_PUB_STATS_RESET_DO_{publication_id}")],
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_PUB_STATS_VIEW_{publication_id}")],
        ]),
        parse_mode="HTML",
    )


async def _do_reset_publication_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    ok = reset_publication_stats(publication_id)
    await update.callback_query.answer("✅ סטטיסטיקת הפרסום אופסה." if ok else "❌ איפוס נכשל.", show_alert=not ok)
    await _show_publication_stats_for_one(update, context, publication_id)


async def _show_suspend_menu(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_SUSPEND_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    s = get_subscriber_card(subscriber_id)
    if not s:
        await update.callback_query.answer("⚠️ מנוי לא נמצא.", show_alert=True)
        return

    status = str(s.get("status") or "").lower()
    is_suspended = status == "suspended"
    is_blocked = status == "blocked"
    status_label = "חסום" if is_blocked else ("מושעה" if is_suspended else "פעיל")
    text = f"⛔ <b>סטטוס נוכחי:</b> {status_label}"
    rows = []
    if is_suspended:
        rows.append([InlineKeyboardButton("✅ ביטול השעיה", callback_data=f"SUBS_UNSUSPEND_DO_{origin}_{page}_{subscriber_id}")])
    elif is_blocked:
        rows.append([InlineKeyboardButton("✅ ביטול חסימה", callback_data=f"SUBS_UNBLOCK_DO_{origin}_{page}_{subscriber_id}")])
    else:
        rows.append([InlineKeyboardButton("⛔ השעה מנוי", callback_data=f"SUBS_SUSPEND_DO_{origin}_{page}_{subscriber_id}")])
        rows.append([InlineKeyboardButton("🚫 חסום מנוי", callback_data=f"SUBS_BLOCK_DO_{origin}_{page}_{subscriber_id}")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")])

    await _safe_query_edit(update, text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")


async def _do_suspend(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_SUSPEND_DO_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    ok = suspend_subscriber(subscriber_id, performed_by=update.callback_query.from_user.id)
    await update.callback_query.answer("✅ המנוי הושעה." if ok else "❌ לא ניתן להשעות.", show_alert=not ok)
    if ok:
        subscriber = get_subscriber_card(subscriber_id)
        if subscriber:
            try:
                await context.bot.send_message(
                    chat_id=subscriber["telegram_id"],
                    text=(
                        "🚫 החשבון שלך הושעה זמנית על ידי הנהלת הבוט.\n\n"
                        "🔒 החשבון נמצא בבדיקה ולכן הגישה לשירותי הבוט הושהתה באופן זמני.\n\n"
                        "🙏 אם יש לך שאלה או אם לדעתך מדובר בטעות, ניתן ליצור קשר עם הנהלת הבוט.\n\n"
                        "תודה על הסבלנות ושיתוף הפעולה. 💙"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📞 צור קשר", callback_data="pub:user:contact")],
                    ]),
                )
            except Exception:
                pass
    await _show_suspend_menu(update, f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")


async def _do_unsuspend(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_UNSUSPEND_DO_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    ok = unsuspend_subscriber(subscriber_id, performed_by=update.callback_query.from_user.id)
    await update.callback_query.answer("✅ ההשעיה בוטלה." if ok else "❌ לא ניתן לבטל השעיה.", show_alert=not ok)
    if ok:
        subscriber = get_subscriber_card(subscriber_id)
        if subscriber:
            try:
                await context.bot.send_message(
                    chat_id=subscriber["telegram_id"],
                    text=(
                        "🎉 החשבון שלך שוחרר מההשעיה!\n\n"
                        "🙌 ניתן להשתמש שוב בכל שירותי הבוט.\n\n"
                        "ברוכים השבים ואנו מאחלים לך המשך שימוש נעים! 💙"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚀 לחץ כאן להפעלת הבוט מחדש", callback_data="BOT_RESTART_START")],
                    ]),
                )
            except Exception:
                pass
    await _show_suspend_menu(update, f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")


async def _do_block(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_BLOCK_DO_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    ok = block_subscriber(subscriber_id, performed_by=update.callback_query.from_user.id)
    await update.callback_query.answer("✅ המנוי נחסם." if ok else "❌ לא ניתן לחסום.", show_alert=not ok)
    if ok:
        subscriber = get_subscriber_card(subscriber_id)
        if subscriber:
            try:
                await context.bot.send_message(
                    chat_id=subscriber["telegram_id"],
                    text=(
                        "🚫 החשבון שלך נחסם על ידי הנהלת הבוט.\n\n"
                        "אם לדעתך מדובר בטעות, ניתן לפנות להנהלה."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📞 צור קשר", callback_data="pub:user:contact")],
                    ]),
                )
            except Exception:
                pass
    await _show_suspend_menu(update, f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")


async def _do_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_UNBLOCK_DO_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    ok = unblock_subscriber(subscriber_id, performed_by=update.callback_query.from_user.id)
    await update.callback_query.answer("✅ החסימה בוטלה." if ok else "❌ לא ניתן לבטל חסימה.", show_alert=not ok)
    if ok:
        subscriber = get_subscriber_card(subscriber_id)
        if subscriber:
            try:
                await context.bot.send_message(
                    chat_id=subscriber["telegram_id"],
                    text=(
                        "🎉 החסימה הוסרה מהחשבון שלך.\n"
                        "אפשר לחזור להשתמש בבוט."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚀 הפעל בוט מחדש", callback_data="BOT_RESTART_START")],
                    ]),
                )
            except Exception:
                pass
    await _show_suspend_menu(update, f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")


async def _prompt_subscriber_warning(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_WARN_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    context.user_data[_STATE] = _AWAIT_SUB_WARNING
    context.user_data[_SUB_WARN_ORIGIN] = origin
    context.user_data[_SUB_WARN_PAGE] = page
    context.user_data[_SUB_WARN_ID] = subscriber_id
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id
    await _safe_query_edit(
        update,
        text="⚠️ <b>הוספת אזהרה</b>\n\nשלח את טקסט האזהרה למנוי.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


async def _prompt_subscriber_note(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_NOTE_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    context.user_data[_STATE] = _AWAIT_SUB_NOTE
    context.user_data[_SUB_WARN_ORIGIN] = origin
    context.user_data[_SUB_WARN_PAGE] = page
    context.user_data[_SUB_WARN_ID] = subscriber_id
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id
    await _safe_query_edit(
        update,
        text="📝 <b>הוספת הערת מנהל</b>\n\nשלח את ההערה הפנימית.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


async def _show_stats(update: Update) -> None:
    live = get_subscription_system_stats_live() or {}

    total_subscribers = int(live.get("total_subscribers") or 0)
    active_subscribers = int(live.get("active_subscribers") or 0)
    suspended_subscribers = int(live.get("suspended_subscribers") or 0)
    blocked_subscribers = int(live.get("blocked_subscribers") or 0)
    total_publications = int(live.get("total_publications") or 0)
    scheduled_publications = int(live.get("scheduled_publications") or 0)
    active_publications = int(live.get("active_publications") or 0)
    total_private_msgs = int(live.get("total_private_msgs") or 0)
    private_msgs_from_admin = int(live.get("private_msgs_from_admin") or 0)
    private_msgs_from_subscribers = int(live.get("private_msgs_from_subscribers") or 0)
    total_private_chats = int(live.get("total_private_chats") or 0)
    open_private_chats = int(live.get("open_private_chats") or 0)
    total_activity_events = int(live.get("total_activity_events") or 0)
    publication_button_clicks = int(live.get("publication_button_clicks") or 0)

    text = (
        "📊 <b>סטטיסטיקה</b>\n\n"
        f"👥 מנויים: <b>{total_subscribers}</b>\n"
        f"✅ פעילים: <b>{active_subscribers}</b>\n"
        f"⛔ מושעים: <b>{suspended_subscribers}</b>\n"
        f"🚫 חסומים: <b>{blocked_subscribers}</b>\n"
        f"📣 פרסומים: <b>{total_publications}</b> (פעילים: {active_publications} | מתוזמנים: {scheduled_publications})\n"
        f"💬 הודעות פרטיות: <b>{total_private_msgs}</b> (מנהל: {private_msgs_from_admin} | מנויים: {private_msgs_from_subscribers})\n"
        f"🧵 שיחות פרטיות: <b>{total_private_chats}</b> (פתוחות: {open_private_chats})\n"
        f"🧾 אירועי פעילות: <b>{total_activity_events}</b>\n"
        f"🔘 לחיצות כפתורי פרסום: <b>{publication_button_clicks}</b>"
    )

    await _safe_query_edit(
        update,
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 רענון", callback_data="SUBS_GLOBAL_STATS")],
            [InlineKeyboardButton("🧹 איפוס פעולות", callback_data="SUBS_GLOBAL_STATS_RESET_CONFIRM")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_MAIN")],
        ]),
        parse_mode="HTML",
    )


async def _open_chat_from_notification(update: Update, data: str) -> None:
    suffix = data[len("SUBS_CHAT_OPEN_"):]
    parts = suffix.split("_", 1)
    if len(parts) != 2:
        return await _invalid_callback(update)
    subscriber_id = _parse_positive_int(parts[0])
    chat_id = _parse_positive_int(parts[1])
    if subscriber_id is None or chat_id is None:
        return await _invalid_callback(update)
    await _render_chat_screen(update, "L", 1, subscriber_id, chat_id)


async def _show_coming_soon(update: Update, title: str, back_cb: str) -> None:
    await _safe_query_edit(
        update,
        text=(
            f"{title}\n\n"
            "⚠️ אפשרות זו עדיין לא ממומשת במודול הפרסום."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data=back_cb)],
        ]),
        parse_mode="HTML",
    )

def _clear_search_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(_STATE, None)
    context.user_data.pop(_SEARCH_TERM, None)
    context.user_data.pop(_CHAT_ID, None)
    context.user_data.pop(_MSG_ID, None)


async def handle_subscriptions_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    state = context.user_data.get(_STATE)

    if state in {_AWAIT_SUB_WARNING, _AWAIT_SUB_NOTE}:
        text = (update.message.text or "").strip() if update.message else ""
        if not text:
            await update.message.reply_text("שלח טקסט תקין.")
            return

        origin = context.user_data.get(_SUB_WARN_ORIGIN) or "L"
        page = int(context.user_data.get(_SUB_WARN_PAGE) or 1)
        subscriber_id = int(context.user_data.get(_SUB_WARN_ID) or 0)
        if subscriber_id <= 0:
            context.user_data.pop(_STATE, None)
            return

        event_key = "warning" if state == _AWAIT_SUB_WARNING else "admin_note"
        payload_value = text[:1000]
        if state == _AWAIT_SUB_NOTE:
            admin_user = update.effective_user
            payload_value = json.dumps(
                {
                    "note": text[:1000],
                    "admin_id": int(admin_user.id) if admin_user else None,
                    "admin_name": (admin_user.full_name if admin_user else "") or "",
                    "created_at": now_il().strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
            )
        ok = track_subscriber_activity(
            subscriber_id=subscriber_id,
            event_key=event_key,
            payload=payload_value,
            increment_basic_activity=False,
        )

        if ok and state == _AWAIT_SUB_WARNING:
            subscriber = get_subscriber_card(subscriber_id)
            if subscriber:
                try:
                    await context.bot.send_message(
                        chat_id=subscriber["telegram_id"],
                        text=f"⚠️ אזהרה מצוות הבוט:\n\n{text[:1000]}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 הפעל בוט מחדש", callback_data="RESTART_BOT_PENDING")],
                        ]),
                    )
                except Exception:
                    pass

        context.user_data.pop(_STATE, None)
        context.user_data.pop(_SUB_WARN_ORIGIN, None)
        context.user_data.pop(_SUB_WARN_PAGE, None)
        context.user_data.pop(_SUB_WARN_ID, None)

        try:
            await update.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ נשמר בהצלחה." if ok else "❌ שמירה נכשלה.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לכרטיס מנוי", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")],
            ]),
            parse_mode="HTML",
        )
        return

    if state == _AWAIT_PUB_BTN_LABEL:
        label = (update.message.text or "").strip() if update.message else ""
        if not label:
            await update.message.reply_text("כתוב שם כפתור.")
            return
        mode = context.user_data.get(_PUB_BTN_MODE)
        context.user_data[_PUB_BTN_LABEL_TMP] = label[:50]

        if mode in {"edit_note_name", "edit_url_name"}:
            draft = context.user_data.get(_PUB_DRAFT) or {}
            buttons = list(draft.get("buttons") or [])
            idx = int(context.user_data.get(_PUB_BTN_EDIT_INDEX) or 0)
            if not (1 <= idx <= len(buttons)):
                await update.message.reply_text("כפתור לעריכה לא נמצא.")
                return

            current = buttons[idx - 1] or {}
            buttons[idx - 1] = {
                "title": label[:50],
                "url": str(current.get("url") or ""),
                "row_index": int(current.get("row_index") or idx),
            }
            draft["buttons"] = buttons
            context.user_data[_PUB_DRAFT] = draft
            context.user_data[_PUB_PREVIEW_CONFIRMED] = False
            context.user_data.pop(_STATE, None)
            context.user_data.pop(_PUB_BTN_MODE, None)
            context.user_data.pop(_PUB_BTN_EDIT_INDEX, None)
            context.user_data.pop(_PUB_BTN_LABEL_TMP, None)
            context.user_data.pop(_PUB_BTN_VALUE_TMP, None)

            chat_id = context.user_data.get(_CHAT_ID)
            msg_id = context.user_data.get(_MSG_ID)
            if chat_id and msg_id:
                sent = await _safe_bot_edit(
                    context,
                    chat_id=chat_id,
                    message_id=msg_id,
                    text="🔘 <b>ניהול כפתורי פרסום</b>",
                    reply_markup=_publication_buttons_manage_keyboard(buttons),
                    parse_mode="HTML",
                )
                if not sent:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="🔘 <b>ניהול כפתורי פרסום</b>",
                        reply_markup=_publication_buttons_manage_keyboard(buttons),
                        parse_mode="HTML",
                    )
            try:
                await update.message.delete()
            except Exception:
                pass
            return

        context.user_data[_STATE] = _AWAIT_PUB_BTN_VALUE
        prompt = "שלח קישור מלא (https://...)." if mode == "edit_url_name" or mode == "add_url" else "שלח טקסט הערה."
        chat_id = context.user_data.get(_CHAT_ID)
        msg_id = context.user_data.get(_MSG_ID)
        if chat_id and msg_id:
            await _safe_bot_edit(
                context,
                chat_id=chat_id,
                message_id=msg_id,
                text=prompt,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
                ]),
                parse_mode="HTML",
            )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if state == _AWAIT_PUB_BTN_VALUE:
        value = (update.message.text or "").strip() if update.message else ""
        if not value:
            await update.message.reply_text("שלח ערך תקין.")
            return

        mode = context.user_data.get(_PUB_BTN_MODE)
        draft = context.user_data.get(_PUB_DRAFT) or {}
        buttons = list(draft.get("buttons") or [])

        if mode == "add_url":
            if not value.startswith(("http://", "https://", "tg://")):
                await update.message.reply_text("קישור לא תקין. שלח קישור שמתחיל ב-http:// או https:// או tg://")
                return
            label = str(context.user_data.get(_PUB_BTN_LABEL_TMP) or "קישור")
            context.user_data[_PUB_BTN_LABEL_TMP] = label[:50]
            context.user_data[_PUB_BTN_VALUE_TMP] = value[:300]
            context.user_data[_STATE] = _AWAIT_PUB_BTN_ROW

            chat_id = context.user_data.get(_CHAT_ID)
            msg_id = context.user_data.get(_MSG_ID)
            if chat_id and msg_id:
                await _safe_bot_edit(
                    context,
                    chat_id=chat_id,
                    message_id=msg_id,
                    text="בחר היכן למקם את הכפתור החדש:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("באותה שורה", callback_data="SUBS_PUB_BTN_ROW_SAME")],
                        [InlineKeyboardButton("בשורה חדשה", callback_data="SUBS_PUB_BTN_ROW_NEW")],
                        [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
                    ]),
                    parse_mode="HTML",
                )
            try:
                await update.message.delete()
            except Exception:
                pass
            return
        elif mode == "edit_url_value":
            if not value.startswith(("http://", "https://", "tg://")):
                await update.message.reply_text("קישור לא תקין. שלח קישור שמתחיל ב-http:// או https:// או tg://")
                return
            idx = int(context.user_data.get(_PUB_BTN_EDIT_INDEX) or 0)
            if not (1 <= idx <= len(buttons)):
                await update.message.reply_text("כפתור לעריכה לא נמצא.")
                return
            label = str(context.user_data.get(_PUB_BTN_LABEL_TMP) or f"כפתור {idx}")
            current = buttons[idx - 1] or {}
            buttons[idx - 1] = {
                "title": label[:50],
                "url": value[:300],
                "row_index": int(current.get("row_index") or idx),
            }
        elif mode == "add_note":
            label = str(context.user_data.get(_PUB_BTN_LABEL_TMP) or "הערה")
            context.user_data[_PUB_BTN_LABEL_TMP] = label[:50]
            context.user_data[_PUB_BTN_VALUE_TMP] = encode_publication_note(value)
            context.user_data[_STATE] = _AWAIT_PUB_BTN_ROW

            chat_id = context.user_data.get(_CHAT_ID)
            msg_id = context.user_data.get(_MSG_ID)
            if chat_id and msg_id:
                await _safe_bot_edit(
                    context,
                    chat_id=chat_id,
                    message_id=msg_id,
                    text="בחר היכן למקם את הכפתור החדש:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("באותה שורה", callback_data="SUBS_PUB_BTN_ROW_SAME")],
                        [InlineKeyboardButton("בשורה חדשה", callback_data="SUBS_PUB_BTN_ROW_NEW")],
                        [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_EDIT_BUTTONS")],
                    ]),
                    parse_mode="HTML",
                )
            try:
                await update.message.delete()
            except Exception:
                pass
            return
        elif mode == "edit_note_value":
            idx = int(context.user_data.get(_PUB_BTN_EDIT_INDEX) or 0)
            if not (1 <= idx <= len(buttons)):
                await update.message.reply_text("כפתור לעריכה לא נמצא.")
                return
            current = buttons[idx - 1] or {}
            buttons[idx - 1] = {
                "title": str(current.get("title") or f"כפתור {idx}"),
                "url": encode_publication_note(value),
                "row_index": int(current.get("row_index") or idx),
            }
        elif mode in {"edit_url_name", "edit_note_name"}:
            # These modes finalize during the label step.
            return
        else:
            context.user_data.pop(_STATE, None)
            return

        draft["buttons"] = buttons
        context.user_data[_PUB_DRAFT] = draft
        context.user_data[_PUB_PREVIEW_CONFIRMED] = False
        context.user_data.pop(_STATE, None)
        context.user_data.pop(_PUB_BTN_MODE, None)
        context.user_data.pop(_PUB_BTN_LABEL_TMP, None)
        context.user_data.pop(_PUB_BTN_EDIT_INDEX, None)

        chat_id = context.user_data.get(_CHAT_ID)
        msg_id = context.user_data.get(_MSG_ID)
        if chat_id and msg_id:
            sent = await _safe_bot_edit(
                context,
                chat_id=chat_id,
                message_id=msg_id,
                text="🔘 <b>ניהול כפתורי פרסום</b>",
                reply_markup=_publication_buttons_manage_keyboard(buttons),
                parse_mode="HTML",
            )
            if not sent:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🔘 <b>ניהול כפתורי פרסום</b>",
                    reply_markup=_publication_buttons_manage_keyboard(buttons),
                    parse_mode="HTML",
                )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if state == _AWAIT_PUB_CONTENT:
        draft = context.user_data.get(_PUB_DRAFT) or {}
        text = (update.message.text or "").strip() if update.message else ""
        media = _extract_message_media(update.message)
        caption = str((media or {}).get("caption") or "").strip()
        content_text = text or caption
        if not content_text and not media:
            await update.message.reply_text("שלח טקסט ו/או מדיה לפרסום.")
            return

        draft["content_text"] = content_text
        if media:
            draft["media_type"] = media.get("media_type")
            draft["file_id"] = media.get("file_id")
        else:
            draft["media_type"] = None
            draft["file_id"] = None
        context.user_data[_PUB_DRAFT] = draft
        context.user_data[_PUB_PREVIEW_CONFIRMED] = False
        context.user_data.pop(_STATE, None)

        chat_id = context.user_data.get(_CHAT_ID)
        msg_id = context.user_data.get(_MSG_ID)
        if chat_id and msg_id:
            edited = await _safe_bot_edit(
                context,
                chat_id=chat_id,
                message_id=msg_id,
                text=_draft_preview_text(draft),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                    [InlineKeyboardButton("🎯 שינוי יעד", callback_data="SUBS_PUB_TARGET_PICK")],
                    [InlineKeyboardButton("✏️ עריכת תוכן", callback_data="SUBS_PUB_EDIT_CONTENT")],
                    [InlineKeyboardButton("🔘 עריכת כפתורים", callback_data="SUBS_PUB_EDIT_BUTTONS")],
                    [InlineKeyboardButton("🚀 שליחה מיידית", callback_data="SUBS_PUB_SEND_NOW")],
                    [InlineKeyboardButton("⏱️ תזמון / טיימר", callback_data="SUBS_PUB_SCHEDULE")],
                    [InlineKeyboardButton("🔁 כל שעה", callback_data="SUBS_PUB_RECUR_60")],
                    [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_PUB_CANCEL_DRAFT")],
                ]),
                parse_mode="HTML",
            )
            if edited:
                try:
                    await update.message.delete()
                except Exception:
                    pass
                return
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_draft_preview_text(draft),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                [InlineKeyboardButton("🎯 שינוי יעד", callback_data="SUBS_PUB_TARGET_PICK")],
                [InlineKeyboardButton("✏️ עריכת תוכן", callback_data="SUBS_PUB_EDIT_CONTENT")],
                [InlineKeyboardButton("🔘 עריכת כפתורים", callback_data="SUBS_PUB_EDIT_BUTTONS")],
                [InlineKeyboardButton("🚀 שליחה מיידית", callback_data="SUBS_PUB_SEND_NOW")],
                [InlineKeyboardButton("⏱️ תזמון / טיימר", callback_data="SUBS_PUB_SCHEDULE")],
                [InlineKeyboardButton("🔁 כל שעה", callback_data="SUBS_PUB_RECUR_60")],
                [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_PUB_CANCEL_DRAFT")],
            ]),
            parse_mode="HTML",
        )
        return

    if state == _AWAIT_PUB_TARGET_VALUE:
        value = (update.message.text or "").strip()
        if not value:
            return
        kind = context.user_data.get("subs_pub_target_kind")
        if kind not in {"catalog", "permission"}:
            context.user_data.pop(_STATE, None)
            return
        draft = context.user_data.get(_PUB_DRAFT) or {}
        draft["target_type"] = kind
        draft["target_value"] = value
        context.user_data[_PUB_DRAFT] = draft
        context.user_data[_PUB_PREVIEW_CONFIRMED] = False
        context.user_data.pop(_STATE, None)
        context.user_data.pop("subs_pub_target_kind", None)

        chat_id = context.user_data.get(_CHAT_ID)
        msg_id = context.user_data.get(_MSG_ID)
        if chat_id and msg_id:
            await _safe_bot_edit(
                context,
                chat_id=chat_id,
                message_id=msg_id,
                text=_draft_preview_text(draft),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                    [InlineKeyboardButton("🎯 שינוי יעד", callback_data="SUBS_PUB_TARGET_PICK")],
                    [InlineKeyboardButton("✏️ עריכת תוכן", callback_data="SUBS_PUB_EDIT_CONTENT")],
                    [InlineKeyboardButton("🔘 עריכת כפתורים", callback_data="SUBS_PUB_EDIT_BUTTONS")],
                    [InlineKeyboardButton("🚀 שליחה מיידית", callback_data="SUBS_PUB_SEND_NOW")],
                    [InlineKeyboardButton("⏱️ תזמון / טיימר", callback_data="SUBS_PUB_SCHEDULE")],
                    [InlineKeyboardButton("🔁 כל שעה", callback_data="SUBS_PUB_RECUR_60")],
                    [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_PUB_CANCEL_DRAFT")],
                ]),
                parse_mode="HTML",
            )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if state == _AWAIT_PUB_BUTTONS:
        raw = (update.message.text or "").strip()
        draft = context.user_data.get(_PUB_DRAFT) or {}
        if raw == "-":
            draft["buttons"] = []
        else:
            parsed: list[dict] = []
            for line in raw.splitlines():
                line = line.strip()
                if not line or "|" not in line:
                    continue
                title, url = [x.strip() for x in line.split("|", 1)]
                if not title or not url.startswith(("http://", "https://", "tg://")):
                    continue
                parsed.append({"title": title[:50], "url": url[:300]})
            draft["buttons"] = parsed
        context.user_data[_PUB_DRAFT] = draft
        context.user_data[_PUB_PREVIEW_CONFIRMED] = False
        context.user_data.pop(_STATE, None)

        chat_id = context.user_data.get(_CHAT_ID)
        msg_id = context.user_data.get(_MSG_ID)
        if chat_id and msg_id:
            await _safe_bot_edit(
                context,
                chat_id=chat_id,
                message_id=msg_id,
                text=_draft_preview_text(draft),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
                    [InlineKeyboardButton("🎯 שינוי יעד", callback_data="SUBS_PUB_TARGET_PICK")],
                    [InlineKeyboardButton("✏️ עריכת תוכן", callback_data="SUBS_PUB_EDIT_CONTENT")],
                    [InlineKeyboardButton("🔘 עריכת כפתורים", callback_data="SUBS_PUB_EDIT_BUTTONS")],
                    [InlineKeyboardButton("🚀 שליחה מיידית", callback_data="SUBS_PUB_SEND_NOW")],
                    [InlineKeyboardButton("⏱️ תזמון / טיימר", callback_data="SUBS_PUB_SCHEDULE")],
                    [InlineKeyboardButton("🔁 כל שעה", callback_data="SUBS_PUB_RECUR_60")],
                    [InlineKeyboardButton("❌ ביטול", callback_data="SUBS_PUB_CANCEL_DRAFT")],
                ]),
                parse_mode="HTML",
            )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if state == _AWAIT_PUB_AUTO_DELETE:
        raw = (update.message.text or "").strip()
        if not raw:
            return
        if raw == "0":
            minutes = 0
        else:
            parsed = _parse_positive_int(raw)
            if parsed is None:
                await update.message.reply_text("שלח מספר דקות חוקי. לדוגמה: 30, 60, 1440 או 0 לכיבוי.")
                return
            minutes = int(parsed)

        draft = context.user_data.get(_PUB_DRAFT) or {}
        draft["auto_delete_minutes"] = minutes
        context.user_data[_PUB_DRAFT] = draft
        pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
        if pub_id > 0:
            update_publication_record(pub_id, auto_delete_minutes=minutes)
        context.user_data.pop(_STATE, None)
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if state == _AWAIT_PUB_SCHEDULE:
        if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
            await update.message.reply_text("יש לפתוח תצוגה מקדימה לפני תזמון.")
            return
        raw = (update.message.text or "").strip()

        now = now_il().replace(tzinfo=None)
        recurring_plan = _parse_manual_recurrence(raw, now)
        if recurring_plan is not None:
            every_minutes = int(recurring_plan.get("repeat_every_minutes") or 0)
            recurrence_type = recurring_plan.get("recurrence_type")
            recurrence_weekdays = recurring_plan.get("recurrence_weekdays")
            recurrence_day_of_month = recurring_plan.get("recurrence_day_of_month")
            recurrence_time = recurring_plan.get("recurrence_time")
            first_run_dt = recurring_plan.get("first_run_dt")
            if every_minutes <= 0 or not isinstance(first_run_dt, datetime):
                await update.message.reply_text("⚠️ תזמון מחזורי לא תקין. נסה שוב.")
                return
            draft = context.user_data.get(_PUB_DRAFT) or {}
            payload = _build_send_payload_from_draft(draft)
            first_run_at = first_run_dt.strftime("%Y-%m-%d %H:%M:%S")
            edit_pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
            if edit_pub_id > 0:
                ok = update_publication_record(
                    edit_pub_id,
                    title=payload["title"],
                    content_text=payload["content_text"],
                    media_type=payload["media_type"],
                    file_id=payload["file_id"],
                    target_type=payload["target_type"],
                    target_value=payload["target_value"],
                    status="active",
                    scheduled_at=first_run_at,
                    is_recurring=1,
                    repeat_every_minutes=every_minutes,
                    recurrence_type=recurrence_type,
                    recurrence_weekdays=recurrence_weekdays,
                    recurrence_day_of_month=recurrence_day_of_month,
                    recurrence_time=recurrence_time,
                    next_run_at=first_run_at,
                    auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
                )
                if not ok:
                    pub_id = 0
                else:
                    replace_publication_buttons_record(edit_pub_id, payload["buttons"])
                    pub_id = edit_pub_id
            else:
                pub_id = create_publication_record(
                    title=payload["title"],
                    content_text=payload["content_text"],
                    media_type=payload["media_type"],
                    file_id=payload["file_id"],
                    target_type=payload["target_type"],
                    target_value=payload["target_value"],
                    status="active",
                    created_by=update.effective_user.id if update.effective_user else None,
                    scheduled_at=first_run_at,
                    is_recurring=1,
                    repeat_every_minutes=every_minutes,
                    recurrence_type=recurrence_type,
                    recurrence_weekdays=recurrence_weekdays,
                    recurrence_day_of_month=recurrence_day_of_month,
                    recurrence_time=recurrence_time,
                    next_run_at=first_run_at,
                    auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
                    buttons=payload["buttons"],
                )
            if pub_id <= 0:
                await update.message.reply_text("⚠️ שגיאה בשמירת מחזוריות. נסה שוב.")
                return

            await _schedule_recurring_job(context, pub_id, first_run_dt)
            context.user_data.pop(_STATE, None)
            await _clear_publication_preview_message(context)
            _clear_publication_draft(context)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "✅ הפרסום המחזורי נשמר בהצלחה\n"
                    f"🕒 הפעלה ראשונה: {first_run_at}\n"
                    f"🔁 תדירות: כל {every_minutes} דקות"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📄 פתח פרסום", callback_data=f"SUBS_PUB_VIEW_{pub_id}")],
                    [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
                ]),
            )
            try:
                await update.message.delete()
            except Exception:
                pass
            return

        run_dt = _parse_user_datetime(raw)
        if run_dt is None:
            await update.message.reply_text(
                "פורמט לא תקין. השתמש באחד מאלה:\n"
                "• YYYY-MM-DD HH:MM\n"
                "• DD/MM/YYYY HH:MM\n"
                "• כל יום HH:MM\n"
                "• כל יום שישי HH:MM\n"
                "• ימים שני,רביעי HH:MM\n"
                "• כל חודש 15 18:00"
            )
            return

        draft = context.user_data.get(_PUB_DRAFT) or {}
        payload = _build_send_payload_from_draft(draft)
        run_at = run_dt.strftime("%Y-%m-%d %H:%M:%S")
        edit_pub_id = int(context.user_data.get(_PUB_EDIT_ID) or 0)
        if edit_pub_id > 0:
            ok = update_publication_record(
                edit_pub_id,
                title=payload["title"],
                content_text=payload["content_text"],
                media_type=payload["media_type"],
                file_id=payload["file_id"],
                target_type=payload["target_type"],
                target_value=payload["target_value"],
                status="scheduled",
                is_recurring=0,
                repeat_every_minutes=None,
                recurrence_type=None,
                recurrence_weekdays=None,
                recurrence_day_of_month=None,
                recurrence_time=None,
                scheduled_at=run_at,
                next_run_at=run_at,
                auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
            )
            if not ok:
                pub_id = 0
            else:
                replace_publication_buttons_record(edit_pub_id, payload["buttons"])
                pub_id = edit_pub_id
        else:
            pub_id = create_publication_record(
                title=payload["title"],
                content_text=payload["content_text"],
                media_type=payload["media_type"],
                file_id=payload["file_id"],
                target_type=payload["target_type"],
                target_value=payload["target_value"],
                status="scheduled",
                created_by=update.effective_user.id if update.effective_user else None,
                scheduled_at=run_at,
                next_run_at=run_at,
                auto_delete_minutes=int(draft.get("auto_delete_minutes") or 0),
                buttons=payload["buttons"],
            )
        if pub_id <= 0:
            await update.message.reply_text("⚠️ שגיאה בשמירת תזמון. נסה שוב.")
            return
        if pub_id > 0:
            await _schedule_one_time_job(context, pub_id, run_dt)
        context.user_data.pop(_STATE, None)
        await _clear_publication_preview_message(context)
        _clear_publication_draft(context)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "✅ הפרסום תוזמן בהצלחה\n"
                f"🕒 {run_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📄 פתח פרסום", callback_data=f"SUBS_PUB_VIEW_{pub_id}")],
                [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
            ]),
        )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if state == _AWAIT_PUB_SEARCH:
        term = (update.message.text or "").strip()
        context.user_data[_PUB_SEARCH_TERM] = "" if term == "-" else term
        context.user_data.pop(_STATE, None)
        chat_id = context.user_data.get(_CHAT_ID)
        msg_id = context.user_data.get(_MSG_ID)
        rows_data, total = list_publications_paged(page=1, per_page=8, search=context.user_data[_PUB_SEARCH_TERM])
        total_pages = max(1, (total + 7) // 8)
        rows = []
        for p in rows_data:
            rows.append([InlineKeyboardButton(f"#{p['id']} · {_publication_status_label(str(p.get('status') or ''))}", callback_data=f"SUBS_PUB_VIEW_{p['id']}")])
        if total_pages > 1:
            rows.append([InlineKeyboardButton("הבא ➡️", callback_data="SUBS_PUB_LIST_PAGE_2")])
        rows.append([InlineKeyboardButton("🔍 חיפוש", callback_data="SUBS_PUB_SEARCH")])
        rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")])
        if chat_id and msg_id:
            await _safe_bot_edit(
                context,
                chat_id=chat_id,
                message_id=msg_id,
                text=f"📚 <b>רשימת פרסומים</b>\nעמוד 1/{total_pages} • סה״כ {total}",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode="HTML",
            )
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if state == _AWAIT_SEARCH:
        term = (update.message.text or "").strip()
        if not term:
            return

        context.user_data[_SEARCH_TERM] = term
        context.user_data.pop(_STATE, None)

        chat_id = context.user_data.get(_CHAT_ID)
        msg_id = context.user_data.get(_MSG_ID)

        try:
            await update.message.delete()
        except Exception:
            pass

        total = count_subscribers_by_search(term)
        per_page = 10

        if total == 0:
            text = f"🔍 <b>תוצאות חיפוש</b>\n\nלא נמצאו תוצאות עבור: <b>{term}</b>"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 חיפוש חדש", callback_data="SUBS_SEARCH")],
                [InlineKeyboardButton("⬅️ חזרה לרשימה", callback_data="SUBS_LIST")],
            ])
        else:
            total_pages = (total + per_page - 1) // per_page
            subscribers = find_subscribers_page(term=term, page=1, per_page=per_page)
            rows = []
            for s in subscribers:
                display_name = s.get("full_name") or (f"@{s['username']}" if s.get("username") else str(s["telegram_id"]))
                rows.append([
                    InlineKeyboardButton(
                        f"👤 {display_name}",
                        callback_data=f"SUBS_CARD_S_1_{s['id']}",
                    )
                ])
            if total_pages > 1:
                rows.append([InlineKeyboardButton("הבא ➡️", callback_data="SUBS_SEARCH_PAGE_2")])
            rows.append([InlineKeyboardButton("🔍 חיפוש חדש", callback_data="SUBS_SEARCH")])
            rows.append([InlineKeyboardButton("⬅️ חזרה לרשימה", callback_data="SUBS_LIST")])
            text = f"🔍 <b>תוצאות חיפוש</b>\n<b>{term}</b>\nעמוד 1/{total_pages} • סה״כ {total}"
            kb = InlineKeyboardMarkup(rows)

        if chat_id and msg_id:
            edited = await _safe_bot_edit(
                context,
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            if edited:
                return

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
        return

    if state == _AWAIT_CHAT_MSG:
        text = (update.message.text or "").strip() if update.message else ""
        media = _extract_message_media(update.message)
        if not text and not media:
            return

        origin = context.user_data.get(_SUB_ORIGIN)
        page = int(context.user_data.get(_SUB_PAGE) or 1)
        subscriber_id = int(context.user_data.get(_SUB_ID) or 0)
        chat_id = int(context.user_data.get(_SUB_CHAT_ID) or 0)
        panel_chat_id = context.user_data.get(_CHAT_ID)
        panel_msg_id = context.user_data.get(_MSG_ID)
        context.user_data.pop(_STATE, None)

        if not subscriber_id:
            return
        if chat_id < 0:
            return

        try:
            await update.message.delete()
        except Exception:
            pass

        admin_id = update.message.from_user.id
        effective_chat_id = chat_id

        if media:
            add_subscriber_chat_message(
                chat_id=effective_chat_id,
                sender_role="admin",
                sender_id=admin_id,
                message_text=_pack_media_meta(media["media_type"], media.get("caption")),
                file_id=media["file_id"],
            )
        else:
            add_subscriber_chat_message(
                chat_id=effective_chat_id,
                sender_role="admin",
                sender_id=admin_id,
                message_text=text,
            )

        s = get_subscriber_card(subscriber_id)
        if s:
            try:
                if media:
                    await _send_media_message(
                        context,
                        chat_id=s["telegram_id"],
                        media_type=media["media_type"],
                        file_id=media["file_id"],
                        caption=media.get("caption"),
                    )
                else:
                    await context.bot.send_message(chat_id=s["telegram_id"], text=text)
            except Exception:
                pass

        rendered_text, rendered_kb = _compose_chat_screen(origin, page, subscriber_id, effective_chat_id)
        if rendered_text and panel_chat_id and panel_msg_id:
            edited = await _safe_bot_edit(
                context,
                chat_id=panel_chat_id,
                message_id=panel_msg_id,
                text=rendered_text,
                reply_markup=rendered_kb,
                parse_mode="HTML",
            )
            if edited:
                return

        if rendered_text:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=rendered_text,
                reply_markup=rendered_kb,
                parse_mode="HTML",
            )


async def handle_subscriber_user_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    if not update.message or not update.effective_user:
        return False

    from services.subscribers_service import get_subscriber_card_by_telegram_id

    subscriber = get_subscriber_card_by_telegram_id(update.effective_user.id)
    if not subscriber:
        return False

    chat = get_open_subscriber_chat(subscriber["id"])
    if not chat:
        if context.user_data.get("support_chat_suppressed"):
            return False
        return False

    history = []
    try:
        history = get_subscriber_chat_history(chat["id"])
    except Exception:
        history = []

    if context.user_data.get("support_chat_suppressed"):
        has_admin_reply = any((item or {}).get("sender_role") == "admin" for item in history)
        if not has_admin_reply:
            return False

    contact_state = context.user_data.get("user_contact_state")
    if contact_state == "awaiting_contact_category":
        await update.message.reply_text(
            "📞 כדי לשלוח פנייה, בחר קודם סוג פנייה מהכפתורים במסך 'צור קשר'.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 הפעל בוט מחדש", callback_data="RESTART_BOT_PENDING")],
            ]),
        )
        return True

    media = _extract_message_media(update.message)
    text = (update.message.text or "").strip() if update.message else ""
    if not text and not media:
        return False

    def _is_contact_request_text(message_text: str) -> bool:
        if not message_text:
            return False
        prefixes = (
            "💬 פנייה כללית\n",
            "⚠️ תלונה\n",
            "💡 הצעה\n",
            "❓ שאלה\n",
            "🆘 דיווח על תקלה\n",
        )
        return message_text.startswith(prefixes)

    try:
        has_pending_contact_request = False
        for item in reversed(history):
            role = item.get("sender_role")
            msg_text = item.get("message_text") or ""
            if role == "admin":
                has_pending_contact_request = False
                break
            if role == "subscriber" and _is_contact_request_text(msg_text):
                has_pending_contact_request = True
                break
        if has_pending_contact_request:
            await update.message.reply_text(
                "⏳ הפנייה שלך בטיפול. עד שמנהל יענה בשיחה, לא ניתן לשלוח הודעה נוספת.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 הפעל בוט מחדש", callback_data="RESTART_BOT_PENDING")],
                ]),
            )
            return True
    except Exception:
        pass

    try:
        if media:
            add_subscriber_chat_message(
                chat_id=chat["id"],
                sender_role="subscriber",
                sender_id=update.effective_user.id,
                message_text=_pack_media_meta(media["media_type"], media.get("caption")),
                file_id=media["file_id"],
            )
            admin_preview = _media_label(media["media_type"])
            if media.get("caption"):
                admin_preview += f"\n{media['caption']}"
        else:
            add_subscriber_chat_message(
                chat_id=chat["id"],
                sender_role="subscriber",
                sender_id=update.effective_user.id,
                message_text=text,
            )
            admin_preview = text

        track_subscriber_activity(
            subscriber_id=int(subscriber["id"]),
            event_key="chat_message",
            payload=None,
            increment_basic_activity=True,
        )

        await context.bot.send_message(
            chat_id=chat["admin_id"],
            text=(
                "📩 <b>תגובה חדשה ממנוי</b>\n\n"
                f"👤 מזהה מנוי: <code>{subscriber['telegram_id']}</code>\n"
                f"💬 {admin_preview}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 פתח שיחה", callback_data=f"SUBS_CHAT_OPEN_{subscriber['id']}_{chat['id']}")],
            ]),
            parse_mode="HTML",
        )
    except Exception:
        return True

    if media:
        try:
            await update.message.delete()
        except Exception:
            pass

    return True
