"""
admin/subscriptions_admin.py
----------------------------
מטפל ממשק הניהול של מודול המנויים.
כל פעולה שעדיין לא יושמה מחזירה "בקרוב" כל עוד המסכים והקולבקים קיימים.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from services.subscribers_service import (
    list_subscribers_page,
    count_subscribers,
    find_subscribers_page,
    count_subscribers_by_search,
    get_subscriber_card,
    suspend_subscriber,
    unsuspend_subscriber,
    track_subscriber_activity,
)
from services.subscriber_stats_service import (
    get_subscription_system_stats,
    get_subscriber_personal_statistics,
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
    count_publication_recipients,
    create_publication_record,
    dispatch_publication,
    get_publication,
    list_available_publication_permissions,
    list_publication_buttons,
    list_publications_paged,
    publication_stats,
    remove_publication,
    update_publication_record,
)
from services.verified_users_service import get_all_catalogs


logger = logging.getLogger(__name__)


_STATE = "subs_state"
_AWAIT_SEARCH = "SUBS_AWAIT_SEARCH"
_AWAIT_CHAT_MSG = "SUBS_AWAIT_CHAT_MSG"
_AWAIT_PUB_CONTENT = "SUBS_AWAIT_PUB_CONTENT"
_AWAIT_PUB_TARGET_VALUE = "SUBS_AWAIT_PUB_TARGET_VALUE"
_AWAIT_PUB_BUTTONS = "SUBS_AWAIT_PUB_BUTTONS"
_AWAIT_PUB_SEARCH = "SUBS_AWAIT_PUB_SEARCH"
_AWAIT_PUB_SCHEDULE = "SUBS_AWAIT_PUB_SCHEDULE"
_SEARCH_TERM = "subs_search_term"
_CHAT_ID = "subs_chat_id"
_MSG_ID = "subs_msg_id"
_SUB_ID = "subs_subscriber_id"
_SUB_ORIGIN = "subs_origin"
_SUB_PAGE = "subs_page"
_SUB_CHAT_ID = "subs_active_chat_id"
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
_PUB_SCHEDULE_JOBS: dict[int, str] = {}
_PUB_RECURRING_JOBS: dict[int, str] = {}


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

    if data.startswith("SUBS_SUSPEND_DO_"):
        return await _do_suspend(update, context, data)

    if data.startswith("SUBS_UNSUSPEND_DO_"):
        return await _do_unsuspend(update, context, data)

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
        return await _prompt_publication_buttons(update, context)

    if data == "SUBS_PUB_SEND_NOW":
        return await _send_publication_now(update, context)

    if data == "SUBS_PUB_SCHEDULE":
        return await _prompt_publication_schedule(update, context)

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

    if data.startswith("SUBS_PUB_DELETE_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_DELETE_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _delete_publication(update, context, pub_id)

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
        return await update.callback_query.answer("ℹ️ מחיקה אוטומטית תבוצע לפי auto_delete_at כאשר יוגדר.", show_alert=True)

    if data == "SUBS_PUB_STATS":
        return await _show_publication_stats_menu(update, context)

    if data.startswith("SUBS_PUB_STATS_VIEW_"):
        pub_id = _parse_positive_int(data[len("SUBS_PUB_STATS_VIEW_"):])
        if pub_id is None:
            return await _invalid_callback(update)
        return await _show_publication_stats_for_one(update, context, pub_id)

    if data == "SUBS_GLOBAL_STATS":
        return await _show_stats(update)


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
        [InlineKeyboardButton("⛔ השעיית מנוי", callback_data=f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")],
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
        "scheduled": "ממתין",
        "active": "מחזורי פעיל",
        "sent": "הסתיים",
        "canceled": "בוטל",
    }.get(status, status)


def _draft_preview_text(draft: dict) -> str:
    content = (draft.get("content_text") or "").strip()
    media_type = draft.get("media_type") or "אין"
    target_type = draft.get("target_type") or "all"
    target_value = draft.get("target_value")
    buttons = draft.get("buttons") or []
    schedule = draft.get("schedule_at") or "מיידי"
    recurring = draft.get("recurring_every")
    recurring_text = f"כל {recurring} דקות" if recurring else "לא"
    recipients = count_publication_recipients(target_type, target_value)
    content_preview = content[:300] if content else "(ללא טקסט)"
    return (
        "🧾 <b>תצוגה מקדימה לפרסום</b>\n\n"
        f"🎯 יעד: <b>{_publication_target_label(target_type, target_value)}</b>\n"
        f"👥 נמענים: <b>{recipients}</b>\n"
        f"🎞️ מדיה: <b>{media_type}</b>\n"
        f"⏱️ תזמון: <b>{schedule}</b>\n"
        f"🔁 מחזורי: <b>{recurring_text}</b>\n"
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
    rows = []
    for b in buttons:
        title = str(b.get("title") or "").strip()
        url = str(b.get("url") or "").strip()
        if title and url.startswith(("http://", "https://", "tg://")):
            rows.append([InlineKeyboardButton(title, url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


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
    context.user_data[_STATE] = _AWAIT_PUB_BUTTONS
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id
    await _safe_query_edit(
        update,
        text=(
            "🔘 <b>כפתורי פרסום</b>\n\n"
            "שלח כל כפתור בשורה בפורמט:\n"
            "כותרת | https://example.com\n\n"
            "דוגמה:\n"
            "אתר החברה | https://example.com\n"
            "וואטסאפ | https://wa.me/123456\n\n"
            "שלח '-' כדי לנקות כפתורים."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
        ]),
        parse_mode="HTML",
    )


async def _show_publication_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = context.user_data.get(_PUB_DRAFT) or {}
    await _send_real_publication_preview(context, update.callback_query.message.chat_id, draft)
    context.user_data[_PUB_PREVIEW_CONFIRMED] = True
    await _safe_query_edit(
        update,
        text=_draft_preview_text(draft),
        reply_markup=InlineKeyboardMarkup([
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
        buttons=payload["buttons"],
    )
    if pub_id <= 0:
        await update.callback_query.answer("שגיאה ביצירת פרסום.", show_alert=True)
        return

    started = datetime.utcnow()
    result = await dispatch_publication(context.bot, pub_id)
    elapsed = (datetime.utcnow() - started).total_seconds()
    await _clear_publication_preview_message(context)
    _clear_publication_draft(context)
    await _safe_query_edit(
        update,
        text=(
            "✅ <b>הפרסום נשלח</b>\n\n"
            f"📨 נשלח בהצלחה: <b>{result.get('sent', 0)}</b>\n"
            f"❌ נכשלו: <b>{result.get('failed', 0)}</b>\n"
            f"🎯 יעד כולל: <b>{result.get('total', 0)}</b>\n"
            f"⏱️ משך שליחה: <b>{elapsed:.2f} שניות</b>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 פתח פרסום", callback_data=f"SUBS_PUB_VIEW_{pub_id}")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
        ]),
        parse_mode="HTML",
    )


async def _prompt_publication_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            "או שלח תאריך ושעה בפורמט: YYYY-MM-DD HH:MM"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("+10 דקות", callback_data="SUBS_PUB_DELAY_10m")],
            [InlineKeyboardButton("+2 שעות", callback_data="SUBS_PUB_DELAY_2h")],
            [InlineKeyboardButton("+1 יום", callback_data="SUBS_PUB_DELAY_1d")],
            [InlineKeyboardButton("🔁 כל שעה", callback_data="SUBS_PUB_RECUR_60")],
            [InlineKeyboardButton("🔁 כל שעתיים", callback_data="SUBS_PUB_RECUR_120")],
            [InlineKeyboardButton("🔁 כל 6 שעות", callback_data="SUBS_PUB_RECUR_360")],
            [InlineKeyboardButton("🔁 פעם ביום", callback_data="SUBS_PUB_RECUR_1440")],
            [InlineKeyboardButton("🔁 פעם בשבוע", callback_data="SUBS_PUB_RECUR_10080")],
            [InlineKeyboardButton("⬅️ חזרה לתצוגה מקדימה", callback_data="SUBS_PUB_PREVIEW")],
        ]),
        parse_mode="HTML",
    )


async def _set_publication_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    suffix = data[len("SUBS_PUB_DELAY_"):]
    now = datetime.utcnow()
    if suffix.endswith("m"):
        dt = now + timedelta(minutes=int(suffix[:-1]))
    elif suffix.endswith("h"):
        dt = now + timedelta(hours=int(suffix[:-1]))
    elif suffix.endswith("d"):
        dt = now + timedelta(days=int(suffix[:-1]))
    else:
        await update.callback_query.answer("טיימר לא תקין", show_alert=True)
        return
    await _save_scheduled_publication(update, context, dt)


async def _set_publication_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    minutes = _parse_positive_int(data[len("SUBS_PUB_RECUR_"):])
    if minutes is None:
        await update.callback_query.answer("מחזור לא תקין", show_alert=True)
        return
    if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
        await update.callback_query.answer("יש לפתוח תצוגה מקדימה לפני הפעלה.", show_alert=True)
        return
    draft = context.user_data.get(_PUB_DRAFT) or {}
    if not (draft.get("content_text") or draft.get("file_id")):
        await update.callback_query.answer("אין תוכן לפרסום", show_alert=True)
        return

    payload = _build_send_payload_from_draft(draft)
    next_run_at = (datetime.utcnow() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
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
        next_run_at=next_run_at,
        buttons=payload["buttons"],
    )
    if pub_id <= 0:
        await update.callback_query.answer("שגיאה ביצירת פרסום מחזורי", show_alert=True)
        return
    await _schedule_recurring_job(context, pub_id, minutes)
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


async def _save_scheduled_publication(update: Update, context: ContextTypes.DEFAULT_TYPE, run_dt: datetime) -> None:
    if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
        await update.callback_query.answer("יש לפתוח תצוגה מקדימה לפני תזמון.", show_alert=True)
        return
    draft = context.user_data.get(_PUB_DRAFT) or {}
    if not (draft.get("content_text") or draft.get("file_id")):
        await update.callback_query.answer("אין תוכן לפרסום", show_alert=True)
        return
    payload = _build_send_payload_from_draft(draft)
    run_at = run_dt.strftime("%Y-%m-%d %H:%M:%S")
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
        buttons=payload["buttons"],
    )
    if pub_id <= 0:
        await update.callback_query.answer("שגיאה בשמירת תזמון", show_alert=True)
        return
    await _schedule_one_time_job(context, pub_id, run_dt)
    await _clear_publication_preview_message(context)
    _clear_publication_draft(context)
    await _safe_query_edit(
        update,
        text=f"✅ הפרסום תוזמן ל- <b>{run_at}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 פתח פרסום", callback_data=f"SUBS_PUB_VIEW_{pub_id}")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
        ]),
        parse_mode="HTML",
    )


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
    for p in rows_data:
        status = _publication_status_label(str(p.get("status") or ""))
        title = (p.get("title") or "פרסום").strip()
        rows.append([InlineKeyboardButton(f"#{p['id']} · {status} · {title[:20]}", callback_data=f"SUBS_PUB_VIEW_{p['id']}")])

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
        text=f"📚 <b>רשימת פרסומים</b>\nעמוד {page}/{total_pages} • סה״כ {total}",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_publication_details(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    p = get_publication(publication_id)
    if not p:
        await update.callback_query.answer("פרסום לא נמצא", show_alert=True)
        return
    status = str(p.get("status") or "")
    text = (
        f"📄 <b>פרסום #{publication_id}</b>\n\n"
        f"מצב: <b>{_publication_status_label(status)}</b>\n"
        f"יעד: <b>{_publication_target_label(str(p.get('target_type') or 'all'), p.get('target_value'))}</b>\n"
        f"תזמון: <b>{p.get('scheduled_at') or '-'}</b>\n"
        f"מחזורי: <b>{'כן' if int(p.get('is_recurring') or 0) == 1 else 'לא'}</b>\n"
        f"מוצלח: <b>{p.get('sent_success_count') or 0}</b> | נכשל: <b>{p.get('sent_fail_count') or 0}</b>\n"
        f"יעד כולל: <b>{p.get('total_targets') or 0}</b>"
    )
    rows = [[InlineKeyboardButton("🚀 שלח עכשיו", callback_data=f"SUBS_PUB_RUN_{publication_id}")]]
    if status in {"scheduled", "active"}:
        rows.append([InlineKeyboardButton("⛔ עצור", callback_data=f"SUBS_PUB_CANCEL_{publication_id}")])
    if status == "canceled" and int(p.get("is_recurring") or 0) == 1:
        rows.append([InlineKeyboardButton("▶️ הפעלה מחדש", callback_data=f"SUBS_PUB_RESUME_{publication_id}")])
    rows.append([InlineKeyboardButton("📈 סטטיסטיקה", callback_data=f"SUBS_PUB_STATS_VIEW_{publication_id}")])
    rows.append([InlineKeyboardButton("🗑️ מחיקה", callback_data=f"SUBS_PUB_DELETE_{publication_id}")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_LIST")])
    await _safe_query_edit(update, text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")


async def _delete_publication(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    await _cancel_publication_jobs(context, publication_id)
    ok = remove_publication(publication_id)
    await update.callback_query.answer("נמחק" if ok else "מחיקה נכשלה", show_alert=not ok)
    await _show_publications_list(update, context, page=1)


async def _run_publication_now(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    result = await dispatch_publication(context.bot, publication_id)
    await update.callback_query.answer("נשלח" if result.get("ok") else "שליחה נכשלה", show_alert=not result.get("ok"))
    await _show_publication_details(update, context, publication_id)


async def _cancel_publication(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    await _cancel_publication_jobs(context, publication_id)
    update_publication_record(publication_id, status="canceled")
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
    minutes = int(p.get("repeat_every_minutes") or 0)
    if minutes <= 0:
        await update.callback_query.answer("תדירות לא תקינה", show_alert=True)
        return
    update_publication_record(publication_id, status="active")
    await _schedule_recurring_job(context, publication_id, minutes)
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
        kb_rows.append([InlineKeyboardButton(f"#{p['id']} · {_publication_status_label(str(p.get('status') or ''))}", callback_data=f"SUBS_PUB_STATS_VIEW_{p['id']}")])
    kb_rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")])
    await _safe_query_edit(update, text="\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="HTML")


async def _show_publication_stats_for_one(update: Update, context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    stats = publication_stats(publication_id)
    pub = stats.get("publication") or {}
    events = stats.get("events") or {}
    text = (
        f"📈 <b>סטטיסטיקה לפרסום #{publication_id}</b>\n\n"
        f"יעד: <b>{_publication_target_label(str(pub.get('target_type') or 'all'), pub.get('target_value'))}</b>\n"
        f"זמן שליחה אחרון: <b>{pub.get('last_sent_at') or '-'}</b>\n"
        f"נשלחו: <b>{events.get('sent', 0)}</b>\n"
        f"נכשלו: <b>{events.get('failed', 0)}</b>\n"
        f"מונה הצלחות: <b>{pub.get('sent_success_count') or 0}</b>\n"
        f"מונה כישלונות: <b>{pub.get('sent_fail_count') or 0}</b>"
    )
    await _safe_query_edit(
        update,
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה לפרסום", callback_data=f"SUBS_PUB_VIEW_{publication_id}")],
        ]),
        parse_mode="HTML",
    )


async def _bootstrap_publication_jobs(context: ContextTypes.DEFAULT_TYPE) -> None:
    rows, _ = list_publications_paged(page=1, per_page=200)
    now = datetime.utcnow()
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
                await _schedule_recurring_job(context, pub_id, minutes)


async def _run_publication_job(context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    await dispatch_publication(context.bot, publication_id)


async def _schedule_one_time_job(context: ContextTypes.DEFAULT_TYPE, publication_id: int, run_at: datetime) -> None:
    await _cancel_publication_jobs(context, publication_id)
    if not context.job_queue:
        return
    job = context.job_queue.run_once(
        _publication_job_callback,
        when=run_at,
        data={"publication_id": publication_id, "mode": "once"},
        name=f"pub_once_{publication_id}",
    )
    _PUB_SCHEDULE_JOBS[publication_id] = job.name


async def _schedule_recurring_job(context: ContextTypes.DEFAULT_TYPE, publication_id: int, minutes: int) -> None:
    await _cancel_publication_jobs(context, publication_id)
    if not context.job_queue:
        return
    interval = max(1, minutes) * 60
    job = context.job_queue.run_repeating(
        _publication_job_callback,
        interval=interval,
        first=5,
        data={"publication_id": publication_id, "mode": "repeat"},
        name=f"pub_repeat_{publication_id}",
    )
    _PUB_RECURRING_JOBS[publication_id] = job.name


async def _cancel_publication_jobs(context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    if context.job_queue:
        for job in context.job_queue.jobs():
            if job.name in {f"pub_once_{publication_id}", f"pub_repeat_{publication_id}"}:
                job.schedule_removal()
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

    await dispatch_publication(job_context.bot, publication_id)


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
        f"🔘 לחיצות על כפתורי פרסום: <b>{stats.get('publication_button_clicks', 0)}</b>"
    )

    await _safe_query_edit(
        update,
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 רענן", callback_data=f"SUBS_STATS_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("🧹 איפוס סטטיסטיקה", callback_data=f"SUBS_STATS_RESET_CONFIRM_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


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


async def _show_suspend_menu(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_SUSPEND_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    s = get_subscriber_card(subscriber_id)
    if not s:
        await update.callback_query.answer("⚠️ מנוי לא נמצא.", show_alert=True)
        return

    is_suspended = s.get("status") == "suspended"
    text = f"⛔ <b>סטטוס נוכחי:</b> {'מושעה' if is_suspended else 'פעיל'}"
    rows = []
    if is_suspended:
        rows.append([InlineKeyboardButton("✅ ביטול השעיה", callback_data=f"SUBS_UNSUSPEND_DO_{origin}_{page}_{subscriber_id}")])
    else:
        rows.append([InlineKeyboardButton("⛔ השעה מנוי", callback_data=f"SUBS_SUSPEND_DO_{origin}_{page}_{subscriber_id}")])
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


async def _show_stats(update: Update) -> None:
    snapshots = get_subscription_system_stats(limit=1)
    last = snapshots[0] if snapshots else None

    total_subscribers = (last.get("total_subscribers", 0) if last else 0)
    active_subscribers = (last.get("active_subscribers", 0) if last else 0)
    suspended_subscribers = (last.get("suspended_subscribers", 0) if last else 0)
    total_publications = (last.get("total_publications", 0) if last else 0)
    total_private_msgs = (last.get("total_private_msgs", 0) if last else 0)

    text = (
        "📊 <b>סטטיסטיקה</b>\n\n"
        f"👥 מנויים: <b>{total_subscribers}</b>\n"
        f"✅ פעילים: <b>{active_subscribers}</b>\n"
        f"⛔ מושעים: <b>{suspended_subscribers}</b>\n"
        f"📣 פרסומים: <b>{total_publications}</b>\n"
        f"💬 הודעות פרטיות: <b>{total_private_msgs}</b>"
    )

    await _safe_query_edit(
        update,
        text=text,
        reply_markup=InlineKeyboardMarkup([
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
        text=f"{title}\n\nבקרוב",
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

    if state == _AWAIT_PUB_CONTENT:
        draft = context.user_data.get(_PUB_DRAFT) or {}
        text = (update.message.text or "").strip() if update.message else ""
        media = _extract_message_media(update.message)
        if not text and not media:
            await update.message.reply_text("שלח טקסט ו/או מדיה לפרסום.")
            return

        draft["content_text"] = text
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

    if state == _AWAIT_PUB_SCHEDULE:
        if not context.user_data.get(_PUB_PREVIEW_CONFIRMED):
            await update.message.reply_text("יש לפתוח תצוגה מקדימה לפני תזמון.")
            return
        raw = (update.message.text or "").strip()
        try:
            run_dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        except Exception:
            await update.message.reply_text("פורמט לא תקין. השתמש: YYYY-MM-DD HH:MM")
            return

        draft = context.user_data.get(_PUB_DRAFT) or {}
        payload = _build_send_payload_from_draft(draft)
        pub_id = create_publication_record(
            title=payload["title"],
            content_text=payload["content_text"],
            media_type=payload["media_type"],
            file_id=payload["file_id"],
            target_type=payload["target_type"],
            target_value=payload["target_value"],
            status="scheduled",
            created_by=update.effective_user.id if update.effective_user else None,
            scheduled_at=run_dt.strftime("%Y-%m-%d %H:%M:%S"),
            next_run_at=run_dt.strftime("%Y-%m-%d %H:%M:%S"),
            buttons=payload["buttons"],
        )
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
    media = _extract_message_media(update.message)
    text = (update.message.text or "").strip() if update.message else ""
    if not text and not media:
        return False

    from services.subscribers_service import get_subscriber_card_by_telegram_id

    subscriber = get_subscriber_card_by_telegram_id(update.effective_user.id)
    if not subscriber:
        return False

    chat = get_open_subscriber_chat(subscriber["id"])
    if not chat:
        return False

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
    try:
        track_subscriber_activity(
            subscriber_id=int(subscriber["id"]),
            event_key="chat_message",
            payload=None,
            increment_basic_activity=True,
        )
    except Exception:
        pass

    try:
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
        pass

    return True
