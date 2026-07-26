"""
admin/subscriptions_admin.py
----------------------------
Standalone subscriptions module admin handler (stage 1 scaffold).
All not-yet-implemented actions return "בקרוב" while screens and callbacks exist.
"""

from __future__ import annotations

import json
import logging

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
    remove_subscriber,
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


logger = logging.getLogger(__name__)


_STATE = "subs_state"
_AWAIT_SEARCH = "SUBS_AWAIT_SEARCH"
_AWAIT_CHAT_MSG = "SUBS_AWAIT_CHAT_MSG"
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
        return await _do_suspend(update, data)

    if data.startswith("SUBS_UNSUSPEND_DO_"):
        return await _do_unsuspend(update, data)

    if data.startswith("SUBS_SUSPEND_"):
        return await _show_suspend_menu(update, data)

    if data.startswith("SUBS_REMOVE_CONFIRM_"):
        return await _confirm_remove_subscriber(update, data)

    if data.startswith("SUBS_REMOVE_DO_"):
        return await _do_remove_subscriber(update, context, data)

    if data.startswith("SUBS_REMOVE_"):
        return await _confirm_remove_subscriber(
            update,
            data.replace("SUBS_REMOVE_", "SUBS_REMOVE_CONFIRM_", 1),
        )

    if data == "SUBS_PUB_MENU":
        return await _show_publications_menu(update)

    if data == "SUBS_PUB_CREATE":
        return await _show_publication_create_flow(update)

    if data == "SUBS_PUB_SCHEDULE":
        return await _show_coming_soon(update, "⏱️ תזמון פרסום", "SUBS_PUB_MENU")

    if data == "SUBS_PUB_AUTO_DELETE":
        return await _show_coming_soon(update, "🧹 מחיקה אוטומטית", "SUBS_PUB_MENU")

    if data == "SUBS_PUB_STATS":
        return await _show_coming_soon(update, "📈 סטטיסטיקת פרסום", "SUBS_PUB_MENU")

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
        f"ID: <code>{s['telegram_id']}</code>\n"
        f"סטטוס: <b>{s.get('status', 'active')}</b>\n\n"
        f"📅 תאריך הצטרפות: {_fmt_dt(stats.get('joined_at'))}\n"
        f"🚪 כניסה ראשונה: {_fmt_dt(stats.get('first_seen_at'))}\n"
        f"⏱️ כניסה אחרונה: {_fmt_dt(stats.get('last_seen_at'))}\n"
        f"🔢 מספר כניסות: {stats.get('login_count', 0)}\n"
        f"📌 פעילות בסיסית: {stats.get('basic_activity', 0)}"
    )

    back_cb = f"SUBS_LIST_PAGE_{page}" if origin == "L" else f"SUBS_SEARCH_PAGE_{page}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 רענן", callback_data=f"SUBS_REFRESH_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("💬 שיחה פרטית", callback_data=f"SUBS_CHAT_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("📜 היסטוריית שיחות", callback_data=f"SUBS_CHAT_HISTORY_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("📊 סטטיסטיקה אישית", callback_data=f"SUBS_STATS_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("⛔ השעיית מנוי", callback_data=f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("🗑️ הסרת מנוי", callback_data=f"SUBS_REMOVE_CONFIRM_{origin}_{page}_{subscriber_id}")],
        [InlineKeyboardButton("⬅️ חזרה", callback_data=back_cb)],
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
            [InlineKeyboardButton("📈 סטטיסטיקת פרסום", callback_data="SUBS_PUB_STATS")],
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_MAIN")],
        ]),
        parse_mode="HTML",
    )


async def _show_publication_create_flow(update: Update) -> None:
    await _safe_query_edit(
        update,
        text=(
            "📝 <b>יצירת פרסום</b>\n\n"
            "סדר העבודה במערכת הפרסום:\n"
            "1. כתיבת הטקסט\n"
            "2. הוספת תמונה/וידאו/מסמך (אופציונלי)\n"
            "3. בחירה האם להוסיף כפתורים\n"
            "4. תצוגה מקדימה\n"
            "5. תזמון או שליחה מיידית\n"
            "6. אפשרות למחיקה אוטומטית\n\n"
            "בקרוב"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="SUBS_PUB_MENU")],
        ]),
        parse_mode="HTML",
    )


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
        if origin not in {"L", "S"} or page <= 0 or subscriber_id <= 0 or chat_id <= 0:
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


def _pack_media_meta(media_type: str, caption: str | None) -> str:
    payload = {
        "media_type": media_type,
        "caption": caption or "",
    }
    return _SUBS_MEDIA_META_PREFIX + json.dumps(payload, ensure_ascii=False)


def _unpack_media_meta(message_text: str | None):
    if not message_text or not isinstance(message_text, str):
        return None
    if not message_text.startswith(_SUBS_MEDIA_META_PREFIX):
        return None
    raw = message_text[len(_SUBS_MEDIA_META_PREFIX):]
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
    if getattr(message, "sticker", None):
        return {"media_type": "sticker", "file_id": message.sticker.file_id, "caption": caption}
    return None


def _media_label(media_type: str) -> str:
    labels = {
        "photo": "📷 תמונה",
        "video": "🎥 וידאו",
        "document": "📎 מסמך",
        "voice": "🎙️ הודעת קול",
        "audio": "🎵 אודיו",
        "animation": "🌀 אנימציה",
        "sticker": "🏷️ מדבקה",
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

    admin_id = update.callback_query.from_user.id
    chat_id = open_subscriber_chat(subscriber_id=subscriber_id, admin_id=admin_id)
    try:
        await update.get_bot().send_message(
            chat_id=subscriber["telegram_id"],
            text=(
                "📩 נפתחה שיחה בינך לבין צוות הבוט.\n"
                "כעת ניתן להשיב ישירות להודעות.\n"
                "תודה."
            ),
        )
    except Exception:
        pass
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
    chat = get_subscriber_chat(chat_id)
    if not subscriber or not chat:
        return None, None

    messages = get_subscriber_chat_history(chat_id)
    display_name = subscriber.get("full_name") or (f"@{subscriber['username']}" if subscriber.get("username") else str(subscriber["telegram_id"]))
    status = "🟢 פתוחה" if chat.get("is_open") else "🔴 סגורה"

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
    if chat.get("is_open"):
        rows.append([InlineKeyboardButton("✉️ שלח הודעה", callback_data=f"SUBS_CHAT_SEND_{origin}_{page}_{subscriber_id}_{chat_id}")])
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
    context.user_data[_STATE] = _AWAIT_CHAT_MSG
    context.user_data[_SUB_ORIGIN] = origin
    context.user_data[_SUB_PAGE] = page
    context.user_data[_SUB_ID] = subscriber_id
    context.user_data[_SUB_CHAT_ID] = chat_id
    context.user_data[_CHAT_ID] = update.callback_query.message.chat_id
    context.user_data[_MSG_ID] = update.callback_query.message.message_id

    await _safe_query_edit(
        update,
        text="✉️ <b>שלח הודעה למנוי</b>\n\nכתוב הודעה:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_CHAT_VIEW_{origin}_{page}_{subscriber_id}_{chat_id}")],
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


async def _do_suspend(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_SUSPEND_DO_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    ok = suspend_subscriber(subscriber_id, performed_by=update.callback_query.from_user.id)
    await update.callback_query.answer("✅ המנוי הושעה." if ok else "❌ לא ניתן להשעות.", show_alert=not ok)
    await _show_suspend_menu(update, f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")


async def _do_unsuspend(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_UNSUSPEND_DO_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    ok = unsuspend_subscriber(subscriber_id, performed_by=update.callback_query.from_user.id)
    await update.callback_query.answer("✅ ההשעיה בוטלה." if ok else "❌ לא ניתן לבטל השעיה.", show_alert=not ok)
    await _show_suspend_menu(update, f"SUBS_SUSPEND_{origin}_{page}_{subscriber_id}")


async def _confirm_remove_subscriber(update: Update, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_REMOVE_CONFIRM_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    await _safe_query_edit(
        update,
        text="🗑️ האם למחוק את המנוי מטבלת subscribers?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן", callback_data=f"SUBS_REMOVE_DO_{origin}_{page}_{subscriber_id}")],
            [InlineKeyboardButton("❌ ביטול", callback_data=f"SUBS_CARD_{origin}_{page}_{subscriber_id}")],
        ]),
        parse_mode="HTML",
    )


async def _do_remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    payload = _parse_card_payload(data, "SUBS_REMOVE_DO_")
    if payload is None:
        return await _invalid_callback(update)
    origin, page, subscriber_id = payload
    ok = remove_subscriber(subscriber_id)
    await update.callback_query.answer("✅ המנוי נמחק." if ok else "❌ מחיקה נכשלה.", show_alert=not ok)
    back_cb = _card_back_callback(origin, page)
    if back_cb.startswith("SUBS_LIST_PAGE_"):
        await _show_subscribers_list(update, int(back_cb.split("_")[-1]))
    else:
        await _show_search_results(update, context, int(back_cb.split("_")[-1]))


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

        if not subscriber_id or not chat_id:
            return

        try:
            await update.message.delete()
        except Exception:
            pass

        admin_id = update.message.from_user.id
        if media:
            add_subscriber_chat_message(
                chat_id=chat_id,
                sender_role="admin",
                sender_id=admin_id,
                message_text=_pack_media_meta(media["media_type"], media.get("caption")),
            )
        else:
            add_subscriber_chat_message(
                chat_id=chat_id,
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

        rendered_text, rendered_kb = _compose_chat_screen(origin, page, subscriber_id, chat_id)
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
