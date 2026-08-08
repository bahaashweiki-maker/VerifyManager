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
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from admin.admin import admin_panel
from config.user_permissions import USER_PERMISSIONS
from database.database import get_connection, now_il
from repositories.merchant_channels_repository import (
    create_channel,
    deactivate_channel,
    get_channel_by_id,
    get_channel_join_url,
    get_channel_membership_chat_ref,
    list_channels,
)
from repositories.merchant_publication_repository import (
    DEFAULT_MULTI_PUBLICATION_LIMIT,
    grant_merchant_channel_access,
    grant_merchant_multi_channel_access,
    grant_merchant_required_channel,
    get_merchant_publication_limit,
    list_merchant_allowed_channels,
    list_merchant_multi_allowed_channels,
    list_merchant_required_channels,
    merchant_has_hourly_publish,
    revoke_merchant_channel_access,
    revoke_merchant_multi_channel_access,
    revoke_merchant_required_channel,
    set_merchant_publication_limit,
    set_merchant_hourly_publish,
)
from repositories.merchant_reviews_repository import (
    admin_edit_merchant_reply,
    approve_merchant_review,
    approve_merchant_reply,
    count_reviews_by_status,
    count_pending_merchant_replies,
    delete_merchant_reply,
    delete_merchant_review,
    get_merchant_review,
    list_reviews_by_status,
    reject_merchant_reply,
    reject_merchant_review,
)
from services.merchant_service import list_merchant_profiles
from services.permission_service import grant_permission, revoke_permission
from services.verified_users_service import get_user_general_permissions

logger = logging.getLogger(__name__)

_STATE = "merchant_admin_state"
_CHAT_ID = "merchant_admin_chat_id"
_MSG_ID = "merchant_admin_msg_id"
_SEARCH_TERM = "merchant_admin_search_term"
_WAIT_CHANNEL = "WAITING_MERCHANT_CHANNEL"
_WAIT_REPLY_EDIT = "WAITING_MERCHANT_REPLY_EDIT"
_WAIT_SEARCH = "WAITING_MERCHANT_SEARCH"
_REPLY_EDIT_REVIEW_ID = "merchant_reply_edit_review_id"
_REPLY_EDIT_SOURCE_STATUS = "merchant_reply_edit_source_status"
_REVIEWS_PAGE_SIZE = 8


async def merchant_admin_route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    if data == "ADMIN_MERCHANTS":
        return await _show_main_menu(update, context)
    if data == "MERCHANT_ADM_CHANNELS":
        return await _show_channels(update, context)
    if data == "MERCHANT_ADM_CHANNEL_HEALTH":
        return await _show_channel_integrity(update, context)
    if data == "MERCHANT_ADM_HEALTH":
        return await _show_merchants_health(update, context)
    if data == "MERCHANT_ADM_TRIAGE":
        return await _show_merchants_triage(update, context)
    if data == "MERCHANT_ADM_CHANNEL_ADD":
        return await _prompt_add_channel(update, context)
    if data.startswith("MERCHANT_ADM_CHANNEL_VIEW_"):
        return await _show_channel_details(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_CHANNEL_DEL_"):
        return await _delete_channel(update, context, int(data.rsplit("_", 1)[1]))
    if data == "MERCHANT_ADM_LIST":
        return await _show_merchants(update, context)
    if data == "MERCHANT_ADM_SEARCH":
        return await _prompt_merchant_search(update, context)
    if data.startswith("MERCHANT_ADM_SEARCH_PAGE_"):
        page = int(data[len("MERCHANT_ADM_SEARCH_PAGE_"):])
        return await _show_merchant_search_results(update, context, page)
    if data.startswith("MERCHANT_ADM_VIEW_"):
        return await _show_merchant(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_PERMS_"):
        return await _show_merchant_permissions(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_STATS_"):
        return await _show_merchant_publication_stats(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_HEALTH_VIEW_"):
        return await _show_merchant_health_details(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_PERM_TOGGLE_"):
        raw = data.removeprefix("MERCHANT_ADM_PERM_TOGGLE_")
        telegram_id_raw, permission_key = raw.split("|", 1)
        return await _toggle_merchant_permission(update, context, int(telegram_id_raw), permission_key)
    if data.startswith("MERCHANT_ADM_HOURLY_"):
        return await _toggle_hourly(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_LIMIT_MENU_"):
        return await _show_publication_limit_menu(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_LIMIT_SET_"):
        raw = data.removeprefix("MERCHANT_ADM_LIMIT_SET_")
        telegram_id_raw, limit_raw = raw.split("_", 1)
        return await _set_publication_limit(update, context, int(telegram_id_raw), int(limit_raw))
    if data.startswith("MERCHANT_ADM_ASSIGN_"):
        return await _show_channel_assignment(update, context, int(data.rsplit("_", 1)[1]))
    if data.startswith("MERCHANT_ADM_MULTI_ASSIGN_"):
        return await _show_multi_channel_assignment(update, context, int(data.rsplit("_", 1)[1]))
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
    if data.startswith("MERCHANT_ADM_MCH_TOGGLE_"):
        raw = data.removeprefix("MERCHANT_ADM_MCH_TOGGLE_")
        telegram_id_raw, channel_id_raw = raw.split("_", 1)
        return await _toggle_merchant_multi_channel(update, context, int(telegram_id_raw), int(channel_id_raw))
    if data == "MERCHANT_ADM_REVIEWS":
        return await _show_reviews_status_menu(update, context)
    if data == "MERCHANT_ADM_REVIEWS_PENDING":
        return await _show_reviews_list(update, context, "pending", page=0)
    if data == "MERCHANT_ADM_REVIEWS_APPROVED":
        return await _show_reviews_list(update, context, "approved", page=0)
    if data == "MERCHANT_ADM_REVIEWS_REJECTED":
        return await _show_reviews_list(update, context, "rejected", page=0)
    if data.startswith("MERCHANT_ADM_REVIEWS_PAGE_"):
        payload = data.removeprefix("MERCHANT_ADM_REVIEWS_PAGE_")
        status_key, page_raw = payload.rsplit("_", 1)
        page_index = max(0, int(page_raw))
        return await _show_reviews_list(update, context, status_key, page=page_index)
    if data.startswith("MERCHANT_ADM_REVIEW_VIEW_"):
        payload = data.removeprefix("MERCHANT_ADM_REVIEW_VIEW_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _show_review_details(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REVIEW_APPROVE_"):
        payload = data.removeprefix("MERCHANT_ADM_REVIEW_APPROVE_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _approve_review(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REVIEW_REJECT_"):
        payload = data.removeprefix("MERCHANT_ADM_REVIEW_REJECT_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _reject_review(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REVIEW_DELETE_"):
        payload = data.removeprefix("MERCHANT_ADM_REVIEW_DELETE_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _delete_review(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REPLY_APPROVE_"):
        payload = data.removeprefix("MERCHANT_ADM_REPLY_APPROVE_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _approve_merchant_reply_action(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REPLY_REJECT_"):
        payload = data.removeprefix("MERCHANT_ADM_REPLY_REJECT_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _reject_merchant_reply_action(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REPLY_EDIT_"):
        payload = data.removeprefix("MERCHANT_ADM_REPLY_EDIT_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _prompt_edit_merchant_reply(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REPLY_DELETE_"):
        payload = data.removeprefix("MERCHANT_ADM_REPLY_DELETE_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _delete_merchant_reply_action(update, context, int(review_id_raw), status_key)
    if data.startswith("MERCHANT_ADM_REPLY_MANAGE_"):
        payload = data.removeprefix("MERCHANT_ADM_REPLY_MANAGE_")
        status_key, review_id_raw = payload.split("_", 1)
        return await _show_reply_management(update, context, int(review_id_raw), status_key)
    if data == "MERCHANT_ADM_BACK":
        return await _show_main_menu(update, context)


async def handle_merchant_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get(_STATE)
    if not update.message:
        return

    if state == _WAIT_REPLY_EDIT:
        review_id = int(context.user_data.get(_REPLY_EDIT_REVIEW_ID) or 0)
        source_status = str(context.user_data.get(_REPLY_EDIT_SOURCE_STATUS) or "approved")
        text = (update.message.text or "").strip()
        _clear_state(context)
        if review_id <= 0 or not text:
            return

        review = get_merchant_review(review_id)
        keep_status = str((review or {}).get("merchant_reply_status") or "pending")
        if keep_status not in {"pending", "approved", "rejected"}:
            keep_status = "pending"
        ok = admin_edit_merchant_reply(review_id, text, keep_status=keep_status)

        try:
            await update.message.delete()
        except Exception:
            pass

        await update.message.reply_text(
            "✅ מענה הסוחר עודכן." if ok else "❌ לא ניתן לעדכן כרגע.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ חזרה לביקורת", callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{source_status}_{review_id}")],
                [InlineKeyboardButton("📂 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")],
            ]),
        )
        return

    if state == _WAIT_SEARCH:
        term = (update.message.text or "").strip()
        if not term:
            await update.message.reply_text("⚠️ שלח מילה לחיפוש או '-' לאיפוס.")
            return
        context.user_data[_SEARCH_TERM] = "" if term == "-" else term
        await _show_merchant_search_results(update, context, page=1)
        return

    if state != _WAIT_CHANNEL:
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
            (
                "❌ לא ניתן לשמור ערוץ.\n\n"
                "פורמט ציבורי תקין לדוגמה:\n"
                "• @mychannel\n"
                "• https://t.me/mychannel\n"
                "• שם ערוץ | @mychannel"
            ),
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
            [InlineKeyboardButton("🧭 דורש טיפול עכשיו", callback_data="MERCHANT_ADM_TRIAGE")],
            [InlineKeyboardButton("🩺 בריאות סוחרים", callback_data="MERCHANT_ADM_HEALTH")],
            [InlineKeyboardButton("📡 ערוצים מורשים", callback_data="MERCHANT_ADM_CHANNELS")],
            [InlineKeyboardButton("⭐ ניהול חוות דעת", callback_data="MERCHANT_ADM_REVIEWS")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="ADMIN_PANEL")],
        ]),
        parse_mode="HTML",
    )


def _review_status_label(status: str) -> str:
    labels = {
        "pending": "ממתינה",
        "approved": "מאושרת",
        "rejected": "נדחתה",
    }
    return labels.get(status, status)


def _merchant_reply_status_label(status: str) -> str:
    labels = {
        "pending": "ממתין לאישור מנהל",
        "approved": "אושר לפרסום",
        "rejected": "נדחה",
    }
    return labels.get(status, "ללא תגובה")


def _status_back_callback(status: str) -> str:
    mapping = {
        "pending": "MERCHANT_ADM_REVIEWS_PENDING",
        "approved": "MERCHANT_ADM_REVIEWS_APPROVED",
        "rejected": "MERCHANT_ADM_REVIEWS_REJECTED",
    }
    return mapping.get(status, "MERCHANT_ADM_REVIEWS")


def _format_dt_full(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return "-"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            continue
    return text


def _format_review_dt_full(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return "-"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt_utc = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(now_il().tzinfo).strftime("%d/%m/%Y %H:%M")
        except Exception:
            continue
    return text


def _format_review_dt_short(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return "-"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt_utc = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(now_il().tzinfo).strftime("%d/%m %H:%M")
        except Exception:
            continue
    return text


def _compact_review_body(review_text: str) -> str:
    raw_lines = [str(line or "").strip() for line in str(review_text or "").splitlines()]
    lines = [line for line in raw_lines if line and line != "━━━━━━━━━━━━━━" and line != "⭐ חוות דעת על השירות"]
    if not lines:
        return "-"

    compact: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "⭐ דירוג:" and i + 1 < len(lines):
            stars = lines[i + 1]
            if all(ch in "★☆" for ch in stars):
                score = stars.count("★")
                compact.append(f"⭐ דירוג: {score}/5 | {stars}")
                i += 2
                continue
        if line.endswith(":") and i + 1 < len(lines):
            nxt = lines[i + 1]
            if not nxt.endswith(":"):
                compact.append(f"{line} {nxt}")
                i += 2
                continue
        compact.append(line)
        i += 1
    return "\n".join(compact)


async def _show_reviews_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    pending_count = count_reviews_by_status("pending")
    approved_count = count_reviews_by_status("approved")
    rejected_count = count_reviews_by_status("rejected")
    pending_replies = count_pending_merchant_replies()
    await update.callback_query.edit_message_text(
        (
            "⭐ <b>ניהול חוות דעת</b>\n\n"
            "בחר סטטוס לצפייה ברשימת הביקורות:\n"
            f"💬 תגובות סוחר ממתינות לאישור: <b>{pending_replies}</b>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⏳ ממתינים ({pending_count})", callback_data="MERCHANT_ADM_REVIEWS_PENDING")],
            [InlineKeyboardButton(f"✅ מאושרים ({approved_count})", callback_data="MERCHANT_ADM_REVIEWS_APPROVED")],
            [InlineKeyboardButton(f"❌ נדחו ({rejected_count})", callback_data="MERCHANT_ADM_REVIEWS_REJECTED")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="MERCHANT_ADM_BACK")],
        ]),
        parse_mode="HTML",
    )


async def _show_reviews_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status: str,
    page: int = 0,
) -> None:
    _clear_state(context)
    rows: list[list[InlineKeyboardButton]] = []
    all_reviews = list_reviews_by_status(status, limit=500)
    total = len(all_reviews)
    page = max(0, page)
    start = page * _REVIEWS_PAGE_SIZE
    end = start + _REVIEWS_PAGE_SIZE
    reviews = all_reviews[start:end]
    for review in reviews:
        review_id = int(review.get("id") or 0)
        reviewer_name = str(review.get("reviewer_name") or "משתמש").strip() or "משתמש"
        created_at = _format_review_dt_short(str(review.get("created_at") or ""))
        rows.append([
            InlineKeyboardButton(
                f"RV-{review_id} | {reviewer_name} | {created_at}",
                callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{status}_{review_id}",
            )
        ])
    if not reviews:
        rows.append([InlineKeyboardButton("אין ביקורות בסטטוס זה", callback_data="MERCHANT_ADM_REVIEWS")])

    nav_row: list[InlineKeyboardButton] = []
    if start > 0:
        nav_row.append(
            InlineKeyboardButton(
                "⬅️ קודם",
                callback_data=f"MERCHANT_ADM_REVIEWS_PAGE_{status}_{page - 1}",
            )
        )
    if end < total:
        nav_row.append(
            InlineKeyboardButton(
                "הבא ➡️",
                callback_data=f"MERCHANT_ADM_REVIEWS_PAGE_{status}_{page + 1}",
            )
        )
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("🔙 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")])
    await update.callback_query.edit_message_text(
        (
            f"⭐ <b>חוות דעת - {_review_status_label(status)}</b>\n"
            f"עמוד {page + 1} | סה\"כ {total}\n\n"
            "בחר ביקורת:"
        ),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_review_details(update: Update, context: ContextTypes.DEFAULT_TYPE, review_id: int, source_status: str) -> None:
    review = get_merchant_review(review_id)
    if review is None:
        await update.callback_query.answer("⚠️ ביקורת לא נמצאה", show_alert=True)
        return await _show_reviews_list(update, context, source_status)

    status_key = str(review.get("status") or "pending")
    reviewer_id = int(review.get("reviewer_id") or 0)
    merchant_id = int(review.get("merchant_id") or 0)
    reviewer_name = str(review.get("reviewer_name") or "משתמש").strip() or "משתמש"
    created_at = _format_review_dt_full(str(review.get("created_at") or ""))
    review_text = _compact_review_body(str(review.get("review_text") or "-"))
    merchant_reply_text = str(review.get("merchant_reply_text") or "").strip()
    merchant_reply_status = str(review.get("merchant_reply_status") or "").strip()
    merchant_reply_dt = _format_review_dt_full(str(review.get("merchant_reply_updated_at") or ""))
    merchant_name = str((_get_merchant_or_none(merchant_id) or {}).get("display_name") or merchant_id)

    if merchant_reply_text:
        reply_block = (
            f"💬 תגובת סוחר: <b>{_merchant_reply_status_label(merchant_reply_status)}</b>\n"
            f"🕒 עדכון תגובה: <b>{merchant_reply_dt}</b>\n"
            f"{merchant_reply_text}"
        )
    else:
        reply_block = "💬 תגובת סוחר: <b>טרם נשלחה</b>"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("✅ אשר ביקורת", callback_data=f"MERCHANT_ADM_REVIEW_APPROVE_{source_status}_{review_id}")],
        [InlineKeyboardButton("❌ דחה ביקורת", callback_data=f"MERCHANT_ADM_REVIEW_REJECT_{source_status}_{review_id}")],
        [InlineKeyboardButton("🗑 מחק ביקורת", callback_data=f"MERCHANT_ADM_REVIEW_DELETE_{source_status}_{review_id}")],
    ]

    if merchant_reply_text:
        rows.append([InlineKeyboardButton("🛠️ ניהול תגובת סוחר", callback_data=f"MERCHANT_ADM_REPLY_MANAGE_{source_status}_{review_id}")])

    rows.extend([
        [InlineKeyboardButton("📞 צור קשר עם הלקוח", url=f"tg://user?id={reviewer_id}")],
        [InlineKeyboardButton("🏪 צור קשר עם הסוחר", url=f"tg://user?id={merchant_id}")],
        [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data=_status_back_callback(source_status))],
    ])

    await update.callback_query.edit_message_text(
        (
            f"⭐ <b>פרטי חוות דעת</b>\n"
            f"🆔 פנייה: <b>RV-{review_id}</b>\n"
            f"📌 סטטוס: <b>{_review_status_label(status_key)}</b>\n"
            f"👤 שולח: <b>{reviewer_name}</b>\n"
            f"🏪 סוחר: <b>{merchant_name}</b>\n"
            f"🕒 תאריך ושעה: <b>{created_at}</b>\n"
            f"{review_text}\n\n"
            f"{reply_block}"
        ),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _notify_reviewer_after_decision(
    context: ContextTypes.DEFAULT_TYPE,
    review: dict,
    decision: str,
) -> None:
    reviewer_id = int(review.get("reviewer_id") or 0)
    if reviewer_id <= 0:
        return
    if decision == "approved":
        text = (
            "✅ <b>חוות הדעת אושרה בהצלחה</b>\n\n"
            "תודה על המשוב שלך. חוות הדעת אושרה על ידי המנהל "
            "וכעת זמינה להצגה בכרטיס הסוחר."
        )
    else:
        text = (
            "❌ <b>חוות הדעת לא אושרה לפרסום</b>\n\n"
            "חוות הדעת נבדקה על ידי המנהל ולא אושרה לפרסום. "
            "תודה על ההבנה."
        )
    try:
        await context.bot.send_message(
            reviewer_id,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזור לבוט הראשי", callback_data="pub:user:home")],
            ]),
        )
    except Exception:
        logger.debug("Failed to notify reviewer %s", reviewer_id)


async def _approve_review(update: Update, context: ContextTypes.DEFAULT_TYPE, review_id: int, source_status: str) -> None:
    review = get_merchant_review(review_id)
    if review is None:
        await update.callback_query.answer("⚠️ ביקורת לא נמצאה", show_alert=True)
        return await _show_reviews_list(update, context, source_status)
    ok = approve_merchant_review(review_id, response_text="אושר על ידי מנהל")
    if ok:
        review["status"] = "approved"
        await _notify_reviewer_after_decision(context, review, "approved")
    await update.callback_query.edit_message_text(
        "✅ הביקורת אושרה." if ok else "❌ לא ניתן לאשר כרגע.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 חזרה לרשימת מאושרים", callback_data="MERCHANT_ADM_REVIEWS_APPROVED")],
            [InlineKeyboardButton("📂 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")],
        ]),
    )


async def _reject_review(update: Update, context: ContextTypes.DEFAULT_TYPE, review_id: int, source_status: str) -> None:
    review = get_merchant_review(review_id)
    if review is None:
        await update.callback_query.answer("⚠️ ביקורת לא נמצאה", show_alert=True)
        return await _show_reviews_list(update, context, source_status)
    ok = reject_merchant_review(review_id, response_text="נדחה על ידי מנהל")
    if ok:
        review["status"] = "rejected"
        await _notify_reviewer_after_decision(context, review, "rejected")
    await update.callback_query.edit_message_text(
        "❌ הביקורת נדחתה." if ok else "❌ לא ניתן לדחות כרגע.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 חזרה לרשימת נדחו", callback_data="MERCHANT_ADM_REVIEWS_REJECTED")],
            [InlineKeyboardButton("📂 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")],
        ]),
    )


async def _delete_review(update: Update, context: ContextTypes.DEFAULT_TYPE, review_id: int, source_status: str) -> None:
    ok = delete_merchant_review(review_id)
    await update.callback_query.edit_message_text(
        "🗑 הביקורת נמחקה." if ok else "❌ לא ניתן למחוק כרגע.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data=_status_back_callback(source_status))],
            [InlineKeyboardButton("📂 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")],
        ]),
    )


async def _notify_merchant_reply_decision(
    context: ContextTypes.DEFAULT_TYPE,
    review: dict,
    decision: str,
) -> None:
    merchant_id = int(review.get("merchant_id") or 0)
    review_id = int(review.get("id") or 0)
    if merchant_id <= 0 or review_id <= 0:
        return
    if decision == "approved":
        text = (
            "✅ <b>תגובת הסוחר שלך אושרה</b>\n\n"
            f"המענה לביקורת RV-{review_id} אושר על ידי המנהל וכעת מוצג ללקוחות."
        )
    else:
        text = (
            "❌ <b>תגובת הסוחר שלך לא אושרה</b>\n\n"
            f"המענה לביקורת RV-{review_id} נבדק ולא אושר. ניתן לערוך ולשלוח שוב."
        )
    try:
        await context.bot.send_message(
            merchant_id,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזור לבוט הראשי", callback_data="pub:user:home")],
            ]),
        )
    except Exception:
        logger.debug("Failed to notify merchant %s about reply decision", merchant_id)


async def _approve_merchant_reply_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    review_id: int,
    source_status: str,
) -> None:
    review = get_merchant_review(review_id)
    if review is None:
        await update.callback_query.answer("⚠️ ביקורת לא נמצאה", show_alert=True)
        return await _show_reviews_list(update, context, source_status)
    ok = approve_merchant_reply(review_id, admin_note="מענה הסוחר אושר על ידי מנהל")
    if ok:
        await _notify_merchant_reply_decision(context, review, "approved")
    await update.callback_query.edit_message_text(
        "✅ תגובת הסוחר אושרה." if ok else "❌ לא ניתן לאשר את תגובת הסוחר כרגע.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ חזרה לביקורת", callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{source_status}_{review_id}")],
            [InlineKeyboardButton("📂 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")],
        ]),
    )


async def _reject_merchant_reply_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    review_id: int,
    source_status: str,
) -> None:
    review = get_merchant_review(review_id)
    if review is None:
        await update.callback_query.answer("⚠️ ביקורת לא נמצאה", show_alert=True)
        return await _show_reviews_list(update, context, source_status)
    ok = reject_merchant_reply(review_id, admin_note="מענה הסוחר נדחה על ידי מנהל")
    if ok:
        await _notify_merchant_reply_decision(context, review, "rejected")
    await update.callback_query.edit_message_text(
        "❌ תגובת הסוחר נדחתה." if ok else "❌ לא ניתן לדחות את תגובת הסוחר כרגע.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ חזרה לביקורת", callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{source_status}_{review_id}")],
            [InlineKeyboardButton("📂 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")],
        ]),
    )


async def _prompt_edit_merchant_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    review_id: int,
    source_status: str,
) -> None:
    review = get_merchant_review(review_id)
    if review is None:
        await update.callback_query.answer("⚠️ ביקורת לא נמצאה", show_alert=True)
        return await _show_reviews_list(update, context, source_status)
    current_text = str(review.get("merchant_reply_text") or "").strip()
    context.user_data[_STATE] = _WAIT_REPLY_EDIT
    context.user_data[_REPLY_EDIT_REVIEW_ID] = review_id
    context.user_data[_REPLY_EDIT_SOURCE_STATUS] = source_status
    await update.callback_query.edit_message_text(
        (
            "✏️ <b>עריכת מענה סוחר</b>\n\n"
            "שלח עכשיו את נוסח המענה החדש בהודעה אחת."
            + (f"\n\nנוסח נוכחי:\n{current_text}" if current_text else "")
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ ביטול", callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{source_status}_{review_id}")],
        ]),
    )


async def _delete_merchant_reply_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    review_id: int,
    source_status: str,
) -> None:
    ok = delete_merchant_reply(review_id)
    await update.callback_query.edit_message_text(
        "🗑 תגובת הסוחר נמחקה." if ok else "❌ לא ניתן למחוק את תגובת הסוחר כרגע.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ חזרה לביקורת", callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{source_status}_{review_id}")],
            [InlineKeyboardButton("📂 חזרה לסטטוסים", callback_data="MERCHANT_ADM_REVIEWS")],
        ]),
    )


async def _show_reply_management(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    review_id: int,
    source_status: str,
) -> None:
    review = get_merchant_review(review_id)
    if review is None:
        await update.callback_query.answer("⚠️ ביקורת לא נמצאה", show_alert=True)
        return await _show_reviews_list(update, context, source_status)

    reply_text = str(review.get("merchant_reply_text") or "").strip()
    reply_status = str(review.get("merchant_reply_status") or "").strip()
    reply_dt = _format_review_dt_full(str(review.get("merchant_reply_updated_at") or ""))

    if not reply_text:
        return await update.callback_query.edit_message_text(
            "ℹ️ אין עדיין תגובת סוחר לביקורת זו.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ חזרה לביקורת", callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{source_status}_{review_id}")],
            ]),
        )

    await update.callback_query.edit_message_text(
        (
            "🛠️ <b>ניהול תגובת סוחר</b>\n\n"
            f"🆔 ביקורת: <b>RV-{review_id}</b>\n"
            f"📌 סטטוס תגובה: <b>{_merchant_reply_status_label(reply_status)}</b>\n"
            f"🕒 תאריך/שעה: <b>{reply_dt}</b>\n\n"
            f"💬 תוכן התגובה:\n{reply_text}"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ אשר תגובה", callback_data=f"MERCHANT_ADM_REPLY_APPROVE_{source_status}_{review_id}")],
            [InlineKeyboardButton("❌ דחה תגובה", callback_data=f"MERCHANT_ADM_REPLY_REJECT_{source_status}_{review_id}")],
            [InlineKeyboardButton("✏️ ערוך תגובה", callback_data=f"MERCHANT_ADM_REPLY_EDIT_{source_status}_{review_id}")],
            [InlineKeyboardButton("🗑 מחק תגובה", callback_data=f"MERCHANT_ADM_REPLY_DELETE_{source_status}_{review_id}")],
            [InlineKeyboardButton("↩️ חזרה לביקורת", callback_data=f"MERCHANT_ADM_REVIEW_VIEW_{source_status}_{review_id}")],
        ]),
    )


async def _resolve_required_join_status_for_channel(
    bot,
    merchant_telegram_id: int,
    channel: dict,
) -> str:
    chat_ref = get_channel_membership_chat_ref(channel)
    if not chat_ref:
        return "unknown"
    try:
        member = await bot.get_chat_member(chat_id=chat_ref, user_id=merchant_telegram_id)
        if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}:
            return "missing"
        return "joined"
    except TelegramError as exc:
        message = str(exc).lower()
        if any(token in message for token in (
            "user not found",
            "participant_id_invalid",
            "chat not found",
            "user not participant",
            "user_id_invalid",
        )):
            return "missing"
        return "unknown"
    except Exception:
        return "unknown"


async def _compute_merchant_join_health(
    bot,
    merchant_telegram_id: int,
    by_key: dict[str, dict],
) -> dict:
    required_keys = [k for k in list_merchant_required_channels(merchant_telegram_id) if k in by_key]
    if not required_keys:
        return {
            "status": "none",
            "required_count": 0,
            "missing_count": 0,
            "unknown_count": 0,
            "channel_items": [],
        }

    channel_items: list[dict] = []
    missing_count = 0
    unknown_count = 0
    for key in required_keys:
        channel = by_key[key]
        status = await _resolve_required_join_status_for_channel(bot, merchant_telegram_id, channel)
        if status == "missing":
            missing_count += 1
        elif status == "unknown":
            unknown_count += 1
        channel_items.append({"channel": channel, "status": status})

    if missing_count > 0:
        status_key = "blocked"
    elif unknown_count > 0:
        status_key = "warning"
    else:
        status_key = "open"

    return {
        "status": status_key,
        "required_count": len(required_keys),
        "missing_count": missing_count,
        "unknown_count": unknown_count,
        "channel_items": channel_items,
    }


def _health_status_label(status_key: str) -> str:
    labels = {
        "open": "✅ פתוח לפרסום",
        "blocked": "⛔ חסום (חסר הצטרפות)",
        "warning": "⚠️ פתוח עם אימות חלקי",
        "none": "➖ ללא ערוצי חובה",
    }
    return labels.get(status_key, status_key)


async def _show_merchants_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    merchants = list_merchant_profiles()
    channels = list_channels(active_only=True)
    by_key = {str(c.get("channel_key") or ""): c for c in channels}

    rows: list[list[InlineKeyboardButton]] = []
    blocked_total = 0
    warning_total = 0
    open_total = 0
    none_total = 0
    merchant_rows: list[tuple[int, str, str, int]] = []

    for merchant in merchants:
        telegram_id = int(merchant["telegram_id"])
        health = await _compute_merchant_join_health(context.bot, telegram_id, by_key)
        status_key = str(health["status"])
        if status_key == "blocked":
            blocked_total += 1
            icon = "⛔"
        elif status_key == "warning":
            warning_total += 1
            icon = "⚠️"
        elif status_key == "open":
            open_total += 1
            icon = "✅"
        else:
            none_total += 1
            icon = "➖"

        status_rank = {"blocked": 0, "warning": 1, "open": 2, "none": 3}.get(status_key, 9)
        merchant_rows.append((status_rank, str(merchant["display_name"]).lower(), f"{icon} {merchant['display_name']}", telegram_id))

    merchant_rows.sort(key=lambda item: (item[0], item[1]))
    for _, __, title, telegram_id in merchant_rows:
        rows.append([
            InlineKeyboardButton(
                title,
                callback_data=f"MERCHANT_ADM_HEALTH_VIEW_{telegram_id}",
            )
        ])

    rows.append([InlineKeyboardButton("🔙 חזרה", callback_data="MERCHANT_ADM_BACK")])

    await update.callback_query.edit_message_text(
        (
            "🩺 <b>בריאות סוחרים - חובת הצטרפות</b>\n\n"
            f"סה\"כ סוחרים: <b>{len(merchants)}</b>\n"
            f"✅ פתוחים: <b>{open_total}</b>\n"
            f"⛔ חסומים: <b>{blocked_total}</b>\n"
            f"⚠️ אימות חלקי: <b>{warning_total}</b>\n"
            f"➖ ללא חובת הצטרפות: <b>{none_total}</b>\n\n"
            "לחץ על סוחר לפירוט מלא."
        ),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_merchant_health_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
) -> None:
    _clear_state(context)
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants_health(update, context)

    channels = list_channels(active_only=True)
    by_key = {str(c.get("channel_key") or ""): c for c in channels}
    health = await _compute_merchant_join_health(context.bot, telegram_id, by_key)

    lines = []
    for item in health["channel_items"]:
        channel = item["channel"]
        status = item["status"]
        if status == "joined":
            mark = "✅"
        elif status == "missing":
            mark = "❌"
        else:
            mark = "⚠️"
        membership_ref = get_channel_membership_chat_ref(channel)
        lines.append(f"{mark} {channel['display_name']} ({membership_ref or 'ללא מזהה בדיקה'})")

    if not lines:
        lines.append("אין ערוצי חובה לסוחר זה.")

    await update.callback_query.edit_message_text(
        (
            f"🩺 <b>בריאות סוחר</b>\n\n"
            f"סוחר: <b>{merchant['display_name']}</b>\n"
            f"🆔 <code>{telegram_id}</code>\n"
            f"סטטוס: <b>{_health_status_label(str(health['status']))}</b>\n\n"
            f"🔐 ערוצי חובה: <b>{health['required_count']}</b>\n"
            f"❌ חסרים: <b>{health['missing_count']}</b>\n"
            f"⚠️ לא מאומתים אוטומטית: <b>{health['unknown_count']}</b>\n\n"
            + "\n".join(lines)
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📞 פתח שיחה עם הסוחר", url=f"tg://user?id={telegram_id}")],
            [InlineKeyboardButton("🔐 עריכת חובת הצטרפות", callback_data=f"MERCHANT_ADM_REQUIRED_{telegram_id}")],
            [InlineKeyboardButton("🔙 חזרה לבריאות סוחרים", callback_data="MERCHANT_ADM_HEALTH")],
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
    rows.append([InlineKeyboardButton("🧪 בדיקת תקינות ערוצים", callback_data="MERCHANT_ADM_CHANNEL_HEALTH")])
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
            f"מזהה/קישור: <code>{channel['channel_ref']}</code>\n\n"
            "ℹ️ סוג הערוץ (חובת הצטרפות / ערוץ פרסום) לא נקבע כאן.\n"
            "הבחירה מתבצעת לכל סוחר בנפרד במסך ניהול סוחרים."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 מעבר לניהול סוחרים", callback_data="MERCHANT_ADM_LIST")],
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
    rows.append([InlineKeyboardButton("🔍 חיפוש", callback_data="MERCHANT_ADM_SEARCH")])
    rows.append([InlineKeyboardButton("🔙 חזרה", callback_data="MERCHANT_ADM_BACK")])

    await update.callback_query.edit_message_text(
        f"👤 <b>רשימת סוחרים</b> ({len(merchants)})\n\nבחר סוחר לניהול:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


def _search_merchant_profiles(term: str) -> list[dict]:
    needle = term.strip().lower()
    username_term = needle.lstrip("@")
    if not needle:
        return []

    matches: list[dict] = []
    for merchant in list_merchant_profiles():
        full_name = str(merchant.get("full_name") or "").lower()
        username = str(merchant.get("username") or "").lower()
        telegram_id = str(merchant.get("telegram_id") or "").lower()
        display_name = str(merchant.get("display_name") or "").lower()
        if (
            needle in full_name
            or needle in username
            or needle in telegram_id
            or needle in display_name
            or username_term in username
        ):
            matches.append(merchant)
    return matches


async def _prompt_merchant_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[_STATE] = _WAIT_SEARCH
    context.user_data.pop(_SEARCH_TERM, None)
    await update.callback_query.edit_message_text(
        text="🔍 <b>חיפוש סוחרים</b>\n\nשלח שם, יוזר או מזהה טלגרם:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="MERCHANT_ADM_LIST")],
        ]),
        parse_mode="HTML",
    )


async def _show_merchant_search_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 1,
) -> None:
    term = (context.user_data.get(_SEARCH_TERM) or "").strip()
    if not term:
        return await _prompt_merchant_search(update, context)

    per_page = 10
    merchants = _search_merchant_profiles(term)
    total = len(merchants)

    if total == 0:
        await update.callback_query.edit_message_text(
            text=f"🔍 <b>תוצאות חיפוש</b>\n\nלא נמצאו תוצאות עבור: <b>{term}</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 חיפוש חדש", callback_data="MERCHANT_ADM_SEARCH")],
                [InlineKeyboardButton("⬅️ חזרה לרשימת סוחרים", callback_data="MERCHANT_ADM_LIST")],
            ]),
            parse_mode="HTML",
        )
        return

    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    current = merchants[start:start + per_page]

    rows = []
    for merchant in current:
        rows.append([
            InlineKeyboardButton(
                f"🏪 {merchant['display_name']}",
                callback_data=f"MERCHANT_ADM_VIEW_{merchant['telegram_id']}",
            )
        ])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"MERCHANT_ADM_SEARCH_PAGE_{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("הבא ➡️", callback_data=f"MERCHANT_ADM_SEARCH_PAGE_{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton("🔍 חיפוש חדש", callback_data="MERCHANT_ADM_SEARCH")])
    rows.append([InlineKeyboardButton("⬅️ חזרה לרשימת סוחרים", callback_data="MERCHANT_ADM_LIST")])

    await update.callback_query.edit_message_text(
        text=f"🔍 <b>תוצאות חיפוש</b>\n<b>{term}</b>\nעמוד {page}/{total_pages} • סה״כ {total}",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _show_merchant(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    channels, required_channels = _sanitize_merchant_channel_permissions(telegram_id)
    multi_channels = _sanitize_merchant_multi_channel_permissions(telegram_id)
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
    multi_enabled = "user.publish.multi" in set(get_user_general_permissions(telegram_id))
    pub_limit = get_merchant_publication_limit(telegram_id, multi_enabled=multi_enabled)
    multi_label = "פעיל" if multi_enabled else "לא פעיל"
    stats_24h = _merchant_publication_metrics_24h(telegram_id)

    await update.callback_query.edit_message_text(
        (
            f"🏪 <b>{merchant['display_name']}</b>\n"
            f"🆔 <code>{telegram_id}</code>\n\n"
            f"⏱️ פרסום כל שעה: <b>{hourly_label}</b>\n"
            f"🧩 פרסומים מרובים: <b>{multi_label}</b>\n"
            f"🧮 מכסת פרסומים פתוחים: <b>{pub_limit}</b>\n"
            f"📡 ערוצי פרסום: <b>{len(channels)}</b>\n"
            f"🧩 ערוצי פרסום מרובה: <b>{len(multi_channels)}</b>\n"
            f"🔐 ערוצי חובה: <b>{len(required_channels)}</b>\n\n"
            f"📨 נשלח ב-24ש: <b>{stats_24h['sent_24h']}</b> | ❌ נכשל ב-24ש: <b>{stats_24h['failed_24h']}</b>\n"
            f"🗂️ פרסומים שמורים: <b>{stats_24h['saved_count']}</b> | 🟢 פעילים: <b>{stats_24h['active_count']}</b>\n\n"
            f"📡 משויך לפרסום: <b>{_format_channel_list(channels)}</b>\n"
            f"🧩 משויך לפרסום מרובה: <b>{_format_channel_list(multi_channels)}</b>\n"
            f"🔐 חובת הצטרפות: <b>{_format_channel_list(required_channels)}</b>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 שיוך ערוצים", callback_data=f"MERCHANT_ADM_ASSIGN_{telegram_id}")],
            [InlineKeyboardButton("🧩 שיוך ערוצי פרסום מרובה", callback_data=f"MERCHANT_ADM_MULTI_ASSIGN_{telegram_id}")],
            [InlineKeyboardButton("🔐 חובת הצטרפות", callback_data=f"MERCHANT_ADM_REQUIRED_{telegram_id}")],
            [InlineKeyboardButton("🔑 הרשאות סוחר", callback_data=f"MERCHANT_ADM_PERMS_{telegram_id}")],
            [InlineKeyboardButton("🧮 מכסת פרסומים", callback_data=f"MERCHANT_ADM_LIMIT_MENU_{telegram_id}")],
            [InlineKeyboardButton("📊 נתוני פרסום 24 שעות", callback_data=f"MERCHANT_ADM_STATS_{telegram_id}")],
            [InlineKeyboardButton("⏱️ הפעל/כבה כל שעה", callback_data=f"MERCHANT_ADM_HOURLY_{telegram_id}")],
            [InlineKeyboardButton("🔙 חזרה לסוחרים", callback_data="MERCHANT_ADM_LIST")],
        ]),
        parse_mode="HTML",
    )


async def _show_publication_limit_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    multi_enabled = "user.publish.multi" in set(get_user_general_permissions(telegram_id))
    current_limit = get_merchant_publication_limit(telegram_id, multi_enabled=multi_enabled)
    options = [1, 2, 3, 5, 10]
    rows: list[list[InlineKeyboardButton]] = []
    for value in options:
        mark = "✅" if value == current_limit else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {value} פרסומים פתוחים",
                callback_data=f"MERCHANT_ADM_LIMIT_SET_{telegram_id}_{value}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 חזרה לסוחר", callback_data=f"MERCHANT_ADM_VIEW_{telegram_id}")])

    await update.callback_query.edit_message_text(
        (
            "🧮 <b>מכסת פרסומים פתוחים לסוחר</b>\n\n"
            f"סוחר: <b>{merchant['display_name']}</b>\n"
            f"🆔 <code>{telegram_id}</code>\n"
            f"פרסומים מרובים: <b>{'פעיל' if multi_enabled else 'לא פעיל'}</b>\n"
            f"מכסה נוכחית: <b>{current_limit}</b>\n\n"
            f"אם לא הוגדרה מכסה מפורשת, ברירת המחדל לפרסומים מרובים היא {DEFAULT_MULTI_PUBLICATION_LIMIT}."
        ),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _set_publication_limit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    limit_value: int,
) -> None:
    ok = set_merchant_publication_limit(
        telegram_id,
        limit_value,
        granted_by=update.callback_query.from_user.id,
    )
    await update.callback_query.answer("✅ נשמר" if ok else "❌ שגיאה", show_alert=not ok)
    await _show_publication_limit_menu(update, context, telegram_id)


def _merchant_permission_items() -> list[dict]:
    items: list[dict] = []
    for item in USER_PERMISSIONS:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        if key.startswith("user.merchant.") or key.startswith("user.media.") or key in {
            "user.publish.multi",
            "user.review.write",
            "user.review.reply",
        }:
            items.append({"key": key, "label": str(item.get("label") or key)})
    if not any(i.get("key") == "user.review.link" for i in items):
        items.append({"key": "user.review.link", "label": "🔗 כפתור: הקישור האישי שלי"})
    return items


def _format_dt_short(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return "-"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%d/%m %H:%M")
        except Exception:
            continue
    return text


def _merchant_publication_metrics_24h(telegram_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN s.event_key = 'sent' THEN 1 ELSE 0 END), 0) AS sent_24h,
                COALESCE(SUM(CASE WHEN s.event_key = 'failed' THEN 1 ELSE 0 END), 0) AS failed_24h,
                COALESCE(COUNT(DISTINCT p.id), 0) AS saved_count,
                COALESCE(SUM(CASE WHEN p.status = 'active' THEN 1 ELSE 0 END), 0) AS active_count,
                MAX(p.last_sent_at) AS last_sent_at
            FROM subscriber_publications p
            LEFT JOIN subscriber_publication_stats s
              ON s.publication_id = p.id
             AND s.created_at >= datetime('now', '-1 day')
            WHERE p.created_by = ?
              AND p.target_type = 'chat_list'
            """,
            (telegram_id,),
        ).fetchone()
    return {
        "sent_24h": int((row[0] or 0) if row else 0),
        "failed_24h": int((row[1] or 0) if row else 0),
        "saved_count": int((row[2] or 0) if row else 0),
        "active_count": int((row[3] or 0) if row else 0),
        "last_sent_at": str((row[4] or "") if row else "").strip(),
    }


async def _show_merchant_permissions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    current = set(get_user_general_permissions(telegram_id))
    rows: list[list[InlineKeyboardButton]] = []
    enabled_count = 0
    permission_items = _merchant_permission_items()
    for item in permission_items:
        key = item["key"]
        mark = "✅" if key in current else "⬜"
        if key in current:
            enabled_count += 1
        rows.append([
            InlineKeyboardButton(
                f"{mark} {item['label']}",
                callback_data=f"MERCHANT_ADM_PERM_TOGGLE_{telegram_id}|{key}",
            )
        ])

    rows.append([InlineKeyboardButton("🔙 חזרה לסוחר", callback_data=f"MERCHANT_ADM_VIEW_{telegram_id}")])

    await update.callback_query.edit_message_text(
        (
            "🔑 <b>הרשאות סוחר</b>\n\n"
            f"סוחר: <b>{merchant['display_name']}</b>\n"
            f"🆔 <code>{telegram_id}</code>\n"
            f"פעילות: <b>{enabled_count}</b> מתוך <b>{len(permission_items)}</b>\n\n"
            "כולל הרשאת <b>פרסומים מרובים במקביל</b> עבור הרחבת פרסום לשלב הבא."
        ),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )


async def _toggle_merchant_permission(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    permission_key: str,
) -> None:
    key = str(permission_key or "").strip()
    allowed_keys = {item["key"] for item in _merchant_permission_items()}
    if key not in allowed_keys:
        await update.callback_query.answer("⚠️ הרשאה לא נתמכת במסך זה", show_alert=True)
        return await _show_merchant_permissions(update, context, telegram_id)

    current = set(get_user_general_permissions(telegram_id))
    if key in current:
        ok = revoke_permission(telegram_id, key)
    else:
        ok = grant_permission(telegram_id, key, granted_by=update.callback_query.from_user.id)

    await update.callback_query.answer("✅ נשמר" if ok else "❌ שגיאה", show_alert=not ok)
    await _show_merchant_permissions(update, context, telegram_id)


async def _show_merchant_publication_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    metrics = _merchant_publication_metrics_24h(telegram_id)
    await update.callback_query.edit_message_text(
        (
            "📊 <b>נתוני פרסום - 24 שעות אחרונות</b>\n\n"
            f"סוחר: <b>{merchant['display_name']}</b>\n"
            f"🆔 <code>{telegram_id}</code>\n\n"
            f"📨 נשלח בהצלחה: <b>{metrics['sent_24h']}</b>\n"
            f"❌ שליחות שנכשלו: <b>{metrics['failed_24h']}</b>\n"
            f"🗂️ פרסומים שמורים: <b>{metrics['saved_count']}</b>\n"
            f"🟢 פרסומים פעילים: <b>{metrics['active_count']}</b>\n"
            f"🕓 שליחה אחרונה: <b>{_format_dt_short(metrics['last_sent_at'])}</b>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 חזרה לסוחר", callback_data=f"MERCHANT_ADM_VIEW_{telegram_id}")],
        ]),
        parse_mode="HTML",
    )


async def _show_channel_integrity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    channels = list_channels(active_only=True)
    ok_count = 0
    warn_count = 0
    broken_count = 0
    lines: list[str] = []

    for channel in channels:
        display = str(channel.get("display_name") or channel.get("channel_key") or "")
        join_url = get_channel_join_url(channel)
        membership_ref = get_channel_membership_chat_ref(channel)
        if membership_ref and (membership_ref.startswith("@") or membership_ref.startswith("-100")):
            ok_count += 1
            lines.append(f"✅ {display} | בדיקה: {membership_ref}")
            continue
        if join_url:
            warn_count += 1
            lines.append(f"⚠️ {display} | יש קישור הצטרפות אבל חסר מזהה בדיקה (@ / -100)")
            continue
        broken_count += 1
        lines.append(f"❌ {display} | ערוץ לא תקין: חסר גם קישור וגם מזהה בדיקה")

    preview = "\n".join(lines[:25]) if lines else "אין ערוצים פעילים."
    if len(lines) > 25:
        preview += f"\n... ועוד {len(lines) - 25}"

    await update.callback_query.edit_message_text(
        (
            "🧪 <b>בדיקת תקינות ערוצים</b>\n\n"
            f"סה\"כ: <b>{len(channels)}</b>\n"
            f"✅ תקינים לאימות: <b>{ok_count}</b>\n"
            f"⚠️ אימות חלקי: <b>{warn_count}</b>\n"
            f"❌ שבורים: <b>{broken_count}</b>\n\n"
            "כדי אימות חובת הצטרפות מלא, לכל ערוץ חובה צריך מזהה בדיקה: @username או -100...\n\n"
            + preview
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה לערוצים", callback_data="MERCHANT_ADM_CHANNELS")],
        ]),
        parse_mode="HTML",
    )


async def _show_merchants_triage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_state(context)
    merchants = list_merchant_profiles()
    channels = list_channels(active_only=True)
    by_key = {str(c.get("channel_key") or ""): c for c in channels}

    rows: list[list[InlineKeyboardButton]] = []
    items: list[tuple[int, str, str, int]] = []

    for merchant in merchants:
        telegram_id = int(merchant["telegram_id"])
        health = await _compute_merchant_join_health(context.bot, telegram_id, by_key)
        metrics = _merchant_publication_metrics_24h(telegram_id)

        status = str(health["status"])
        failed_24h = int(metrics["failed_24h"])
        if status == "blocked":
            priority = 0
            label = f"⛔ {merchant['display_name']} | חסום"
        elif failed_24h > 0:
            priority = 1
            label = f"❌ {merchant['display_name']} | {failed_24h} כשלונות ב-24ש"
        elif status == "warning":
            priority = 2
            label = f"⚠️ {merchant['display_name']} | אימות חלקי"
        else:
            continue

        items.append((priority, str(merchant["display_name"]).lower(), label, telegram_id))

    items.sort(key=lambda row: (row[0], row[1]))
    for _, __, label, telegram_id in items:
        rows.append([
            InlineKeyboardButton(label, callback_data=f"MERCHANT_ADM_HEALTH_VIEW_{telegram_id}"),
            InlineKeyboardButton("📞", url=f"tg://user?id={telegram_id}"),
        ])

    if not rows:
        rows.append([InlineKeyboardButton("✅ אין כרגע סוחרים שדורשים טיפול", callback_data="IGNORE")])
    rows.append([InlineKeyboardButton("🔙 חזרה", callback_data="MERCHANT_ADM_BACK")])

    await update.callback_query.edit_message_text(
        (
            "🧭 <b>דורש טיפול עכשיו</b>\n\n"
            "מציג קודם כל חסימות הצטרפות, אחר כך כשלונות שליחה, ואז אימות חלקי."
        ),
        reply_markup=InlineKeyboardMarkup(rows),
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


async def _show_multi_channel_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> None:
    merchant = _get_merchant_or_none(telegram_id)
    if merchant is None:
        await update.callback_query.answer("⚠️ סוחר לא נמצא", show_alert=True)
        return await _show_merchants(update, context)

    assigned = set(_sanitize_merchant_multi_channel_permissions(telegram_id))
    channels = list_channels(active_only=True)
    rows = []
    for channel in channels:
        mark = "✅" if channel["channel_key"] in assigned else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {channel['display_name']}",
                callback_data=f"MERCHANT_ADM_MCH_TOGGLE_{telegram_id}_{channel['id']}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 חזרה לסוחר", callback_data=f"MERCHANT_ADM_VIEW_{telegram_id}")])

    await update.callback_query.edit_message_text(
        (
            "🧩 <b>ערוצי פרסום מרובה</b>\n\n"
            f"סוחר: <b>{merchant['display_name']}</b>\n"
            "הערוצים כאן תקפים ל-'פרסום נוסף (מרובה)' בלבד."
        ),
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


async def _toggle_merchant_multi_channel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    channel_id: int,
) -> None:
    channel = get_channel_by_id(channel_id)
    if channel is None:
        await update.callback_query.answer("⚠️ ערוץ לא נמצא", show_alert=True)
        return await _show_multi_channel_assignment(update, context, telegram_id)

    assigned = set(list_merchant_multi_allowed_channels(telegram_id))
    if channel["channel_key"] in assigned:
        ok = revoke_merchant_multi_channel_access(telegram_id, channel["channel_key"])
    else:
        ok = grant_merchant_multi_channel_access(
            telegram_id,
            channel["channel_key"],
            granted_by=update.callback_query.from_user.id,
        )

    await update.callback_query.answer("✅ נשמר" if ok else "❌ שגיאה", show_alert=not ok)
    await _show_multi_channel_assignment(update, context, telegram_id)


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


def _sanitize_merchant_multi_channel_permissions(telegram_id: int) -> list[str]:
    active_channel_keys = {c["channel_key"] for c in list_channels(active_only=True)}
    assigned = list_merchant_multi_allowed_channels(telegram_id)
    stale = [key for key in assigned if key not in active_channel_keys]
    for key in stale:
        revoke_merchant_multi_channel_access(telegram_id, key)
    if stale:
        assigned = list_merchant_multi_allowed_channels(telegram_id)
    return assigned


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
    context.user_data.pop(_SEARCH_TERM, None)
    context.user_data.pop(_CHAT_ID, None)
    context.user_data.pop(_MSG_ID, None)
    context.user_data.pop(_REPLY_EDIT_REVIEW_ID, None)
    context.user_data.pop(_REPLY_EDIT_SOURCE_STATUS, None)
