"""
app/engine/publishing_renderer.py

פונקציות render למשתמש — דף הבית ועמודים.

רישום ב-app/bot.py:
    from app.engine.publishing_renderer import handle_user_nav, render_home
    # ניתוב pub:user: מתבצע בתוך button_click — ראה bot.py
"""

from __future__ import annotations

import json
import logging
from typing import Optional
from datetime import datetime, timedelta

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from repositories.home_repository import get_home
from database.database import now_il
from repositories.pub_page_repository import pub_get_page_by_id, pub_get_pages_by_parent
from repositories.pub_button_repository import (
    pub_get_buttons_for_home,
    pub_get_buttons_for_page,
    pub_get_button_by_id,
)
from config.constants import ADMIN_ID
from services.subscribers_service import (
    register_or_touch_subscriber,
    track_subscriber_activity,
)
from services.subscriber_chat_service import (
    open_subscriber_chat,
    get_open_subscriber_chat,
    add_subscriber_chat_message,
    get_subscriber_chat_history,
)
from services.verified_users_service import (
    get_auto_catalogs_for_user,
    get_user_catalog_slugs,
)
from services.merchant_service import is_merchant
from services.merchant_service import (
    MERCHANT_CAPABILITY_LABELS,
    can_merchant_start_publication,
    get_merchant_profile,
    get_merchant_capability_flags,
    list_merchant_allowed_channel_records,
    list_merchant_multi_allowed_channel_records,
    list_merchant_required_channel_records,
)
from services.subscriber_publication_service import (
    count_open_creator_publications,
    create_publication_record,
    get_creator_last_sent_at,
    get_publication,
    list_creator_publications,
    remove_publication,
    replace_publication_buttons_record,
    run_publication_now,
    schedule_publication_recurring,
    update_publication_record,
)
from repositories.merchant_publication_repository import merchant_has_hourly_publish
from repositories.merchant_publication_repository import get_merchant_publication_limit
from repositories.merchant_channels_repository import (
    get_channel_join_url,
    get_channel_membership_chat_ref,
)
from repositories.merchant_reviews_repository import (
    count_merchant_reviews,
    create_merchant_review,
    list_merchant_reviews,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# מעקב הודעת בית — מניעת הצפה בעת לחיצות חוזרות על /start
# ---------------------------------------------------------------------------
# מפתח: chat_id, ערך: message_id של הודעת הבית האחרונה.
# לפני כל שליחת בית — מוחקים את הקודמת אם קיימת.
_last_home_msg: dict[int, int] = {}


# ---------------------------------------------------------------------------
# כפתורי מערכת — חלק מליבת הבוט, לא ניתנים לניהול דרך מודול הפרסום.
# מוצגים תמיד בתחתית דף הבית, גם אם המנהל מחק את כל שאר הכפתורים.
#
# כדי להוסיף את כפתור הפרופיל בעתיד:
#   הוסף שורה: [InlineKeyboardButton("👤 הפרופיל שלי", callback_data="<callback_data_קיים>")]
# ---------------------------------------------------------------------------

_SYSTEM_BUTTONS: list[list[InlineKeyboardButton]] = [
    [InlineKeyboardButton("🪪 שלח אימות", callback_data="START_VERIFY")],
    [InlineKeyboardButton("📞 צור קשר", callback_data="pub:user:contact")],
]


def _build_system_buttons(telegram_id: Optional[int] = None) -> list[list[InlineKeyboardButton]]:
    """Build home system buttons and add merchant entry only for merchants."""
    rows = [row[:] for row in _SYSTEM_BUTTONS]
    if telegram_id and is_merchant(telegram_id):
        rows.insert(1, [InlineKeyboardButton("💼 אזור סוחר", callback_data="pub:user:merchant")])
    return rows

_CONTACT_STATE_KEY = "user_contact_state"
_CONTACT_CATEGORY_KEY = "user_contact_category"
_CONTACT_SUBSCRIBER_ID_KEY = "user_contact_subscriber_id"
_CONTACT_CHAT_ID_KEY = "user_contact_chat_id"
_SUPPORT_CHAT_SUPPRESSED_KEY = "support_chat_suppressed"
_MERCHANT_SELECTED_CHANNELS_KEY = "merchant_selected_channels"
_MERCHANT_DRAFT_KEY = "merchant_publication_draft"
_MERCHANT_STATE_KEY = "merchant_publication_state"
_MERCHANT_REVIEW_TARGET_KEY = "merchant_review_target"
_MERCHANT_CONTACT_TARGET_KEY = "merchant_contact_target"
_MERCHANT_EDIT_PUB_ID_KEY = "merchant_edit_publication_id"
_MERCHANT_CHANNEL_PICKER_SOURCE_KEY = "merchant_channel_picker_source"
_MERCHANT_REQUIRED_JOIN_LAST_STATE_KEY = "merchant_required_join_last_state"
_MERCHANT_PUBLICATION_MODE_KEY = "merchant_publication_mode"

_AWAIT_MERCHANT_TEXT = "merchant_await_text"
_AWAIT_MERCHANT_MEDIA = "merchant_await_media"
_AWAIT_MERCHANT_REVIEW = "merchant_await_review"
_AWAIT_MERCHANT_CONTACT = "merchant_await_contact"

_MERCHANT_START_HOME = "merchant_home"
_MERCHANT_START_REVIEW = "merchant_review_"
_MERCHANT_START_REVIEWS = "merchant_reviews_"
_MERCHANT_START_CONTACT = "merchant_contact_"
_MERCHANT_BUILD_TAG = "M-2026-08-06-3"

_CONTACT_CATEGORIES: dict[str, str] = {
    "general": "💬 פנייה כללית",
    "complaint": "⚠️ תלונה",
    "suggestion": "💡 הצעה",
    "question": "❓ שאלה",
    "bug": "🆘 דיווח על תקלה",
}


def _merchant_deeplink_payload(prefix: str, merchant_id: int) -> str:
    return f"{prefix}{merchant_id}"


async def _get_bot_username(bot: Bot, context: ContextTypes.DEFAULT_TYPE) -> str:
    cached = str(context.bot_data.get("bot_username") or "").strip()
    if cached:
        return cached
    me = await bot.get_me()
    username = str(getattr(me, "username", "") or "").strip()
    if username:
        context.bot_data["bot_username"] = username
    return username


def _merchant_deeplink_url(bot_username: str, payload: str) -> str:
    return f"https://t.me/{bot_username}?start={payload}"


def _build_merchant_publication_button_defs(bot_username: str, merchant_id: int) -> list[dict]:
    return [
        {"title": "⭐ חוות דעת", "url": _merchant_deeplink_url(bot_username, _merchant_deeplink_payload(_MERCHANT_START_REVIEWS, merchant_id)), "row_index": 0},
        {"title": "📞 פנה לסוחר", "url": f"tg://user?id={merchant_id}", "row_index": 0},
        {"title": "🤖 חזרה לבוט הראשי", "url": _merchant_deeplink_url(bot_username, _MERCHANT_START_HOME), "row_index": 1},
    ]


def _build_markup_from_button_defs(buttons: list[dict]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    rows_by_index: dict[int, list[InlineKeyboardButton]] = {}
    for idx, button in enumerate(buttons):
        title = str(button.get("title") or "").strip()
        url = str(button.get("url") or "").strip()
        if not title or not url:
            continue
        row_index = int(button.get("row_index") if button.get("row_index") is not None else idx)
        rows_by_index.setdefault(row_index, []).append(InlineKeyboardButton(title, url=url))
    rows = [rows_by_index[key] for key in sorted(rows_by_index) if rows_by_index.get(key)]
    return InlineKeyboardMarkup(rows) if rows else None


def _get_merchant_draft(context: ContextTypes.DEFAULT_TYPE, selected_keys: Optional[set[str]] = None) -> dict:
    draft = context.user_data.get(_MERCHANT_DRAFT_KEY)
    if not isinstance(draft, dict):
        draft = {}
    if selected_keys is not None:
        draft["selected_channel_keys"] = sorted(selected_keys)
    draft.setdefault("content_text", "")
    draft.setdefault("media_type", None)
    draft.setdefault("file_id", None)
    context.user_data[_MERCHANT_DRAFT_KEY] = draft
    return draft


def _reset_merchant_publication_state(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    clear_selection: bool,
) -> None:
    context.user_data.pop(_MERCHANT_DRAFT_KEY, None)
    context.user_data.pop(_MERCHANT_EDIT_PUB_ID_KEY, None)
    context.user_data.pop(_MERCHANT_STATE_KEY, None)
    context.user_data.pop(_MERCHANT_PUBLICATION_MODE_KEY, None)
    if clear_selection:
        context.user_data.pop(_MERCHANT_SELECTED_CHANNELS_KEY, None)


def _get_merchant_publication_mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    mode = str(context.user_data.get(_MERCHANT_PUBLICATION_MODE_KEY) or "regular").strip().lower()
    return mode if mode in {"regular", "multi"} else "regular"


def _set_merchant_publication_mode(context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    normalized = str(mode or "regular").strip().lower()
    context.user_data[_MERCHANT_PUBLICATION_MODE_KEY] = normalized if normalized in {"regular", "multi"} else "regular"


def _next_hour_from_now(now: datetime) -> datetime:
    return (now + timedelta(hours=1)).replace(second=0, microsecond=0)


def _manual_send_wait_seconds(merchant_id: int) -> int:
    last_sent_raw = get_creator_last_sent_at(merchant_id)
    return _manual_send_wait_seconds_by_last_sent(last_sent_raw)


def _manual_send_wait_seconds_by_last_sent(last_sent_raw: str | None) -> int:
    if not last_sent_raw:
        return 0
    try:
        last_sent = datetime.strptime(last_sent_raw, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0
    elapsed = (now_il().replace(tzinfo=None) - last_sent).total_seconds()
    remaining = int(3600 - elapsed)
    return remaining if remaining > 0 else 0


def _format_wait_minutes_seconds(wait_seconds: int) -> str:
    mins = wait_seconds // 60
    secs = wait_seconds % 60
    return f"{mins:02d}:{secs:02d}"


def _has_any_media_permission(capability_flags: dict[str, bool]) -> bool:
    return any(
        capability_flags.get(k)
        for k in ("user.media.image", "user.media.video", "user.media.animation", "user.media.document", "user.media.audio")
    )


def _kb_merchant_back_to_compose() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזרה לעריכת פרסום", callback_data="pub:user:merchant:compose")],
        [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
    ])


def _kb_merchant_cancel_input() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ביטול קלט", callback_data="pub:user:merchant:cancelinput")],
        [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
    ])


async def _send_manual_cooldown_message(bot: Bot, chat_id: int, wait_seconds: int) -> None:
    await _send_manual_cooldown_message_scoped(bot, chat_id, wait_seconds, per_publication=False)


async def _send_manual_cooldown_message_scoped(
    bot: Bot,
    chat_id: int,
    wait_seconds: int,
    *,
    per_publication: bool,
) -> None:
    scope_line = "לפרסום הזה" if per_publication else "לחשבון"
    await bot.send_message(
        chat_id,
        (
            "⏳ <b>שליחה מיידית מוגבלת לפעם בשעה</b>\n\n"
            f"ההגבלה כרגע מחושבת {scope_line}.\n"
            f"אפשר לשלוח שוב בעוד: <b>{_format_wait_minutes_seconds(wait_seconds)}</b>"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
        ]),
    )


def _is_multi_publication_enabled_for_creator(creator_id: int) -> bool:
    if creator_id <= 0:
        return False
    flags = get_merchant_capability_flags(creator_id)
    return bool(flags.get("user.publish.multi"))


def _merchant_open_publication_limit(merchant_id: int, capability_flags: dict[str, bool]) -> int:
    multi_enabled = bool(capability_flags.get("user.publish.multi"))
    return get_merchant_publication_limit(merchant_id, multi_enabled=multi_enabled)


def _manual_send_wait_seconds_for_publication(publication: dict | None) -> int:
    if not publication:
        return 0
    return _manual_send_wait_seconds_by_last_sent(str(publication.get("last_sent_at") or "").strip())


def _resolve_manual_wait_seconds(
    merchant_id: int,
    capability_flags: dict[str, bool],
    publication_id: int,
) -> tuple[int, bool]:
    if capability_flags.get("user.publish.multi"):
        if publication_id > 0:
            publication = get_publication(publication_id)
            return _manual_send_wait_seconds_for_publication(publication), True
        return 0, True
    return _manual_send_wait_seconds(merchant_id), False


def _draft_media_summary(draft: dict) -> str:
    media_type = str(draft.get("media_type") or "").strip()
    if not media_type or not draft.get("file_id"):
        return "ללא מדיה"
    labels = {
        "photo": "תמונה",
        "video": "וידאו",
        "animation": "אנימציה",
        "document": "מסמך",
        "audio": "אודיו",
    }
    return labels.get(media_type, media_type)


def _publication_status_label(status: str) -> str:
    mapping = {
        "draft": "טיוטה (נשמר לפני שליחה)",
        "sending": "שולח",
        "sent": "נשלח",
        "scheduled": "מתוזמן",
        "active": "פעיל",
        "canceled": "בוטל",
    }
    return mapping.get((status or "").strip(), status or "לא ידוע")


def _publication_has_content(pub: dict) -> bool:
    content_text = str(pub.get("content_text") or "").strip()
    file_id = str(pub.get("file_id") or "").strip()
    return bool(content_text or file_id)


def _merchant_publication_status_label(pub: dict) -> str:
    status = str(pub.get("status") or "").strip()
    if status == "draft" and not _publication_has_content(pub):
        return "טיוטה ריקה (נשמר שלד לפני שליחה)"
    return _publication_status_label(status)


def _merchant_publication_display_title(pub: dict, fallback_id: int) -> str:
    content = " ".join(str(pub.get("content_text") or "").strip().split())
    if content:
        return (content[:36] + "...") if len(content) > 36 else content
    media_label = _draft_media_summary({"media_type": pub.get("media_type"), "file_id": pub.get("file_id")})
    if media_label != "ללא מדיה":
        return f"פרסום עם {media_label.lower()}"
    return f"פרסום #{fallback_id}"


def _merchant_publication_meta(pub: dict) -> str:
    status = str(pub.get("status") or "").strip()
    if status == "draft":
        raw = str(pub.get("updated_at") or pub.get("created_at") or "").strip()
    else:
        raw = str(pub.get("last_sent_at") or pub.get("updated_at") or pub.get("created_at") or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%d/%m %H:%M")
        except Exception:
            continue
    return raw


def _parse_publication_dt(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _format_duration_from_now(target_dt: datetime) -> str:
    delta = target_dt - now_il().replace(tzinfo=None)
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "מייד"
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}ש {minutes:02d}ד"
    return f"{minutes}ד"


def _merchant_next_run_display(pub: dict) -> str:
    next_run_dt = _parse_publication_dt(pub.get("next_run_at"))
    if next_run_dt:
        return f"{next_run_dt.strftime('%d/%m %H:%M')} (בעוד {_format_duration_from_now(next_run_dt)})"

    creator_id = int(pub.get("created_by") or 0)
    if _is_multi_publication_enabled_for_creator(creator_id):
        last_sent_raw = str(pub.get("last_sent_at") or "").strip() or None
    else:
        last_sent_raw = get_creator_last_sent_at(creator_id) if creator_id > 0 else None
    last_sent_dt = _parse_publication_dt(last_sent_raw)
    if not last_sent_dt:
        return "אפשר עכשיו"

    next_manual_dt = last_sent_dt + timedelta(hours=1)
    if next_manual_dt <= now_il().replace(tzinfo=None):
        return "אפשר עכשיו"
    return f"{next_manual_dt.strftime('%d/%m %H:%M')} (בעוד {_format_duration_from_now(next_manual_dt)})"


def _merchant_next_run_label(pub: dict) -> str:
    if _parse_publication_dt(pub.get("next_run_at")):
        return "הפעלה הבאה"
    creator_id = int(pub.get("created_by") or 0)
    if _is_multi_publication_enabled_for_creator(creator_id):
        return "שליחה ידנית הבאה לפרסום זה"
    return "שליחה ידנית הבאה לכל החשבון"


def _merchant_feature_allowed(capability_flags: dict[str, bool], key: str) -> bool:
    return bool(capability_flags.get(key))


def _parse_chat_refs_from_target_value(target_value: str | None) -> list[str]:
    raw = (target_value or "").strip()
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, list):
            return [str(x).strip() for x in decoded if str(x).strip()]
    except Exception:
        pass
    return [part.strip() for part in raw.split(",") if part.strip()]


def _detect_selected_keys_from_publication(pub: dict, allowed_channel_records: list[dict]) -> set[str]:
    refs = set(_parse_chat_refs_from_target_value(pub.get("target_value")))
    selected: set[str] = set()
    for ch in allowed_channel_records:
        key = str(ch.get("channel_key") or "")
        if not key:
            continue
        membership_ref = get_channel_membership_chat_ref(ch)
        if membership_ref and (membership_ref in refs or str(membership_ref) in refs):
            selected.add(key)
            continue
        if membership_ref and membership_ref.startswith("-100") and membership_ref.lstrip("+") in refs:
            selected.add(key)
            continue
    return selected


async def _cancel_merchant_publication_jobs(context: ContextTypes.DEFAULT_TYPE, publication_id: int) -> None:
    if not context.job_queue:
        return
    for job in context.job_queue.jobs():
        if job.name in {f"merchant_repeat_{publication_id}", f"merchant_once_{publication_id}"}:
            job.schedule_removal()


async def _show_merchant_publication_list(
    bot: Bot,
    chat_id: int,
    merchant_id: int,
) -> None:
    rows_data = list_creator_publications(merchant_id, limit=12)
    rows: list[list[InlineKeyboardButton]] = []
    lines = [
        "🗂️ <b>הפרסומים שלי</b>",
        "",
        "כאן אפשר לפתוח פרסום קיים, לערוך אותו, לשלוח שוב או למחוק.",
        (
            "זמן השליחה הידנית מחושב בנפרד לכל פרסום (פרסומים מרובים פעיל)."
            if get_merchant_capability_flags(merchant_id).get("user.publish.multi")
            else "זמן השליחה הידנית משותף לכל הפרסומים של החשבון, ולא מחושב בנפרד לכל פרסום."
        ),
    ]
    if not rows_data:
        lines.append("אין עדיין פרסומים שמורים.")
    else:
        for pub in rows_data:
            pid = int(pub.get("id") or 0)
            status = _merchant_publication_status_label(pub)
            title = _merchant_publication_display_title(pub, pid)
            next_run = _merchant_next_run_display(pub)
            next_label = _merchant_next_run_label(pub)
            meta = _merchant_publication_meta(pub)
            short_next = f" | {next_label}: {next_run}" if next_run else ""
            meta_suffix = f" | {meta}" if meta else ""
            lines.append(f"• <b>{title}</b>")
            lines.append(f"  מצב: {status}{meta_suffix}{short_next}")
            button_title = (title[:24] + "...") if len(title) > 24 else title
            rows.append([InlineKeyboardButton(f"📄 {button_title}", callback_data=f"pub:user:merchant:pubview:{pid}")])
    rows.append([InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")])
    await bot.send_message(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _show_merchant_publication_details(
    bot: Bot,
    chat_id: int,
    publication_id: int,
) -> None:
    pub = get_publication(publication_id)
    if not pub:
        await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
        return
    status = _merchant_publication_status_label(pub)
    title = _merchant_publication_display_title(pub, publication_id)
    next_run_at = _merchant_next_run_display(pub)
    next_run_label = _merchant_next_run_label(pub)
    content_preview = (str(pub.get("content_text") or "").strip() or "ללא טקסט")[:220]
    media_line = _draft_media_summary({"media_type": pub.get("media_type"), "file_id": pub.get("file_id")})
    meta = _merchant_publication_meta(pub)

    rows = [
        [InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data=f"pub:user:merchant:pubpreview:{publication_id}")],
        [InlineKeyboardButton("✏️ ערוך ושמור", callback_data=f"pub:user:merchant:pubedit:{publication_id}")],
    ]
    creator_id = int(pub.get("created_by") or 0)
    hourly_permission_enabled = merchant_has_hourly_publish(creator_id)
    if int(pub.get("is_recurring") or 0) == 1 and str(pub.get("status") or "") == "active":
        rows.append([InlineKeyboardButton("📨 שליחה מיידית נוספת", callback_data=f"pub:user:merchant:pubrun:{publication_id}")])
        rows.append([InlineKeyboardButton("⛔ עצור שעתי", callback_data=f"pub:user:merchant:pubstop:{publication_id}")])
    else:
        rows.append([InlineKeyboardButton("🚀 פרסם עכשיו", callback_data=f"pub:user:merchant:pubrun:{publication_id}")])
        if hourly_permission_enabled:
            rows.append([InlineKeyboardButton("⏱️ הפעל אוטומטי כל שעה", callback_data=f"pub:user:merchant:pubhourly:{publication_id}")])
    rows.append([InlineKeyboardButton("🗑️ מחק פרסום", callback_data=f"pub:user:merchant:pubdel:{publication_id}")])
    rows.append([InlineKeyboardButton("⬅️ חזרה לרשימה", callback_data="pub:user:merchant:mypubs")])

    await bot.send_message(
        chat_id,
        (
            f"📄 <b>פרטי פרסום</b>\n\n"
            + f"כותרת: <b>{title}</b>\n"
            + f"סטטוס: <b>{status}</b>\n"
            + (f"🕓 עדכון/שליחה אחרונה: <b>{meta}</b>\n" if meta else "")
            + f"🖼️ מדיה: <b>{media_line}</b>\n"
            + f"🕒 {next_run_label}: <b>{next_run_at}</b>\n\n"
            + ("ℹ️ הזמן הידני הבא משותף לכל הפרסומים בחשבון זה.\n\n" if next_run_label == "שליחה ידנית הבאה לכל החשבון" else "")
            + f"{content_preview}"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _send_merchant_compose_screen(
    bot: Bot,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    merchant_id: int,
    allowed_channel_records: list[dict],
    capability_flags: dict[str, bool],
    *,
    publication_mode: str = "regular",
) -> None:
    selected = _get_selected_merchant_channels(context, allowed_channel_records)
    draft = _get_merchant_draft(context, selected)
    selected_names = [
        ch["display_name"]
        for ch in allowed_channel_records
        if str(ch.get("channel_key") or "") in selected
    ]
    content_preview = (str(draft.get("content_text") or "").strip() or "ללא טקסט")[:350]
    media_summary = _draft_media_summary(draft)
    has_saved_content = bool(str(draft.get("content_text") or "").strip() or str(draft.get("file_id") or "").strip())
    save_line = "💾 נשמר אוטומטית כטיוטה לפני שליחה.\n" if has_saved_content else "💾 טיוטה תישמר אוטומטית אחרי טקסט או מדיה ראשונים.\n"
    edit_pub_id = int(context.user_data.get(_MERCHANT_EDIT_PUB_ID_KEY) or 0)
    mode_label = "פרסום מרובה" if publication_mode == "multi" else "פרסום רגיל"
    mode_line = f"✏️ מצב עריכה לפרסום #{edit_pub_id}" if edit_pub_id > 0 else f"🆕 {mode_label}"
    hourly_only = merchant_has_hourly_publish(merchant_id)

    rows = [
        [InlineKeyboardButton("📡 בחר ערוצים", callback_data="pub:user:merchant:startcompose")],
        [InlineKeyboardButton("📝 ערוך טקסט", callback_data="pub:user:merchant:settext")],
    ]
    if _has_any_media_permission(capability_flags):
        rows.append([InlineKeyboardButton("🖼️ העלה מדיה", callback_data="pub:user:merchant:setmedia")])
    rows.append([InlineKeyboardButton("👁️ תצוגה מקדימה", callback_data="pub:user:merchant:preview")])
    rows.append([InlineKeyboardButton("🚀 פרסם עכשיו", callback_data="pub:user:merchant:sendnow")])
    if capability_flags.get("user.merchant.schedule") and hourly_only:
        rows.append([InlineKeyboardButton("⏱️ הפעל אוטומטי כל שעה", callback_data="pub:user:merchant:sendhourly")])
    rows.append([InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")])

    await bot.send_message(
        chat_id,
        (
            "🧾 <b>יצירת פרסום</b>\n\n"
            + f"{mode_line}\n"
            + save_line
            + ("⏱️ החשבון מוגדר לשליחה ידנית פעם בשעה + אוטומטית כל שעה.\n" if hourly_only else "")
            + f"📡 ערוצים נבחרים: <b>{len(selected_names)}</b>\n"
            + ("\n".join(f"• {name}" for name in selected_names[:8]) if selected_names else "אין ערוצים נבחרים")
            + "\n\n"
            + f"🖼️ מדיה: <b>{media_summary}</b>\n"
            + f"💬 טקסט:\n{content_preview}"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _send_merchant_publication_preview(
    bot: Bot,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    merchant_id: int,
) -> None:
    draft = _get_merchant_draft(context)
    content = str(draft.get("content_text") or "").strip()
    file_id = str(draft.get("file_id") or "").strip()
    media_type = str(draft.get("media_type") or "").strip() or None
    bot_username = await _get_bot_username(bot, context)
    preview_rows = _build_merchant_publication_button_defs(bot_username, merchant_id)
    keyboard = _build_markup_from_button_defs(preview_rows)
    back_row = [InlineKeyboardButton("⬅️ חזרה לעמוד פרסום", callback_data="pub:user:merchant:compose")]
    if keyboard:
        keyboard = InlineKeyboardMarkup(list(keyboard.inline_keyboard) + [back_row])
    else:
        keyboard = InlineKeyboardMarkup([back_row])

    if not content and not file_id:
        await bot.send_message(
            chat_id,
            "⚠️ עדיין לא הוזן תוכן לתצוגה מקדימה. הטיוטה שמורה, אבל צריך להוסיף טקסט או מדיה כדי לראות תצוגה.",
            reply_markup=_kb_merchant_back_to_compose(),
        )
        return

    if file_id:
        await _send_media(
            bot,
            chat_id,
            file_id,
            media_type=media_type,
            caption=content or "(ללא טקסט)",
            keyboard=keyboard,
        )
        return

    await bot.send_message(
        chat_id,
        content or "(ללא טקסט)",
        reply_markup=keyboard,
    )


def _resolve_selected_publish_refs(selected_channels: list[dict]) -> tuple[list[str | int], list[str]]:
    refs: list[str | int] = []
    invalid_names: list[str] = []
    for channel in selected_channels:
        ref = get_channel_membership_chat_ref(channel)
        if ref is None:
            invalid_names.append(channel["display_name"])
            continue
        if ref.startswith("-100"):
            try:
                refs.append(int(ref))
                continue
            except Exception:
                invalid_names.append(channel["display_name"])
                continue
        refs.append(ref)
    return refs, invalid_names


def _build_target_value_from_selected_channels(selected_channels: list[dict]) -> str:
    refs, _ = _resolve_selected_publish_refs(selected_channels)
    return json.dumps(refs, ensure_ascii=False)


def _ensure_merchant_draft_record(
    context: ContextTypes.DEFAULT_TYPE,
    merchant_id: int,
    allowed_channel_records: list[dict],
    capability_flags: dict[str, bool],
) -> tuple[int, str]:
    selected = _get_selected_merchant_channels(context, allowed_channel_records)
    selected_channels = [
        ch for ch in allowed_channel_records if str(ch.get("channel_key") or "") in selected
    ]
    draft = _get_merchant_draft(context, selected)
    content_text = str(draft.get("content_text") or "").strip()
    file_id = str(draft.get("file_id") or "").strip() or None
    media_type = str(draft.get("media_type") or "").strip() or None
    title = f"פרסום סוחר #{merchant_id}"
    target_value = _build_target_value_from_selected_channels(selected_channels)
    edit_pub_id = int(context.user_data.get(_MERCHANT_EDIT_PUB_ID_KEY) or 0)

    if edit_pub_id > 0:
        pub = get_publication(edit_pub_id)
        if pub and int(pub.get("created_by") or 0) == merchant_id and str(pub.get("status") or "") == "draft":
            ok = update_publication_record(
                edit_pub_id,
                title=title,
                content_text=content_text,
                media_type=media_type,
                file_id=file_id,
                target_type="chat_list",
                target_value=target_value,
                status="draft",
            )
            if not ok:
                return 0, "error"
        return edit_pub_id, "ok"

    if not content_text and not file_id:
        return 0, "no_content"

    open_count = count_open_creator_publications(merchant_id)
    max_open = _merchant_open_publication_limit(merchant_id, capability_flags)
    if open_count >= max_open:
        return 0, "blocked"

    new_pub_id = create_publication_record(
        title=title,
        content_text=content_text,
        media_type=media_type,
        file_id=file_id,
        target_type="chat_list",
        target_value=target_value,
        status="draft",
        created_by=merchant_id,
    )
    if new_pub_id <= 0:
        return 0, "error"
    context.user_data[_MERCHANT_EDIT_PUB_ID_KEY] = new_pub_id
    return new_pub_id, "ok"


async def _notify_admin_required_join_completed(
    bot: Bot,
    merchant_id: int,
    merchant_name: str,
    required_count: int,
) -> None:
    if ADMIN_ID <= 0:
        return
    try:
        await bot.send_message(
            ADMIN_ID,
            (
                "✅ <b>אימות חובת הצטרפות הושלם</b>\n\n"
                f"👤 סוחר: <b>{merchant_name}</b>\n"
                f"🆔 משתמש: <code>{merchant_id}</code>\n"
                f"🔐 ערוצי חובה מאומתים: <b>{required_count}</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _run_merchant_publication_send(
    bot: Bot,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    merchant_id: int,
    allowed_channel_records: list[dict],
    capability_flags: dict[str, bool],
    *,
    recurring_hourly: bool,
) -> None:
    edit_pub_id = int(context.user_data.get(_MERCHANT_EDIT_PUB_ID_KEY) or 0)
    wait_seconds, per_publication_wait = _resolve_manual_wait_seconds(
        merchant_id,
        capability_flags,
        edit_pub_id,
    )
    if wait_seconds > 0:
        await _send_manual_cooldown_message_scoped(
            bot,
            chat_id,
            wait_seconds,
            per_publication=per_publication_wait,
        )
        return

    selected = _get_selected_merchant_channels(context, allowed_channel_records)
    selected_channels = [
        ch for ch in allowed_channel_records if str(ch.get("channel_key") or "") in selected
    ]
    if not selected_channels:
        await bot.send_message(
            chat_id,
            "⚠️ צריך לבחור לפחות ערוץ אחד.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📡 בחר ערוצים", callback_data="pub:user:merchant:start")],
                [InlineKeyboardButton("⬅️ חזרה לעריכת פרסום", callback_data="pub:user:merchant:compose")],
            ]),
        )
        return

    refs, invalid_names = _resolve_selected_publish_refs(selected_channels)
    if invalid_names:
        await bot.send_message(
            chat_id,
            "⛔ אי אפשר לפרסם לערוצים הבאים כי חסר להם @username ציבורי או מזהה -100:\n"
            + "\n".join(f"• {name}" for name in invalid_names),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📡 חזור לבחירת ערוצים", callback_data="pub:user:merchant:start")],
                [InlineKeyboardButton("⬅️ חזרה לעריכת פרסום", callback_data="pub:user:merchant:compose")],
            ]),
        )
        return

    draft = _get_merchant_draft(context, selected)
    content_text = str(draft.get("content_text") or "").strip()
    file_id = str(draft.get("file_id") or "").strip() or None
    media_type = str(draft.get("media_type") or "").strip() or None
    if not content_text and not file_id:
        await bot.send_message(
            chat_id,
            "⚠️ צריך להוסיף טקסט או מדיה לפני שליחה.",
            reply_markup=_kb_merchant_back_to_compose(),
        )
        return

    bot_username = await _get_bot_username(bot, context)
    buttons = _build_merchant_publication_button_defs(bot_username, merchant_id)
    target_value = json.dumps(refs, ensure_ascii=False)
    title = f"פרסום סוחר #{merchant_id}"

    if edit_pub_id <= 0 and not capability_flags.get("user.publish.multi"):
        pass

    if edit_pub_id <= 0:
        open_count = count_open_creator_publications(merchant_id)
        max_open = _merchant_open_publication_limit(merchant_id, capability_flags)
        if open_count >= max_open:
            await bot.send_message(
                chat_id,
                f"⛔ הגעת למכסת הפרסומים שלך ({max_open}). מחק/עצור פרסום קיים או פנה למנהל להגדלת המכסה.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗂️ הפרסומים שלי", callback_data="pub:user:merchant:mypubs")],
                    [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                ]),
            )
            return

    if recurring_hourly:
        if edit_pub_id > 0:
            ok = update_publication_record(
                edit_pub_id,
                title=title,
                content_text=content_text,
                media_type=media_type,
                file_id=file_id,
                target_type="chat_list",
                target_value=target_value,
                status="active",
                is_recurring=1,
                repeat_every_minutes=60,
                recurrence_type="interval",
                next_run_at=None,
                scheduled_at=None,
            )
            if not ok:
                await bot.send_message(chat_id, "❌ שגיאה בעדכון פרסום שעתי.")
                return
            replace_publication_buttons_record(edit_pub_id, buttons)
            pub_id = edit_pub_id
        else:
            pub_id = create_publication_record(
                title=title,
                content_text=content_text,
                media_type=media_type,
                file_id=file_id,
                target_type="chat_list",
                target_value=target_value,
                status="active",
                created_by=merchant_id,
                is_recurring=1,
                repeat_every_minutes=60,
                recurrence_type="interval",
                next_run_at=None,
                buttons=buttons,
            )
        if pub_id <= 0:
            await bot.send_message(chat_id, "❌ שגיאה בשמירת פרסום שעתי.")
            return
        result = await run_publication_now(bot, pub_id)
        refreshed = get_publication(pub_id) or {}
        next_run_raw = str(refreshed.get("next_run_at") or "").strip()
        next_run_text = "-"
        if next_run_raw:
            try:
                next_run_dt = datetime.strptime(next_run_raw, "%Y-%m-%d %H:%M:%S")
                await schedule_publication_recurring(context, pub_id, next_run_dt, job_prefix="merchant_repeat")
                next_run_text = next_run_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                next_run_text = next_run_raw
        context.user_data[_MERCHANT_EDIT_PUB_ID_KEY] = pub_id
        await bot.send_message(
            chat_id,
            (
                "✅ <b>הפרסום נשלח והאוטומציה הופעלה</b>\n\n"
                f"📨 נשלחו עכשיו: <b>{result.get('sent', 0)}</b>\n"
                f"❌ נכשלו: <b>{result.get('failed', 0)}</b>\n"
                f"🎯 יעדים ייחודיים: <b>{result.get('total', 0)}</b>\n"
                f"🕒 פרסום הבא: <b>{next_run_text}</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
            ]),
        )
        return

    existing_pub = get_publication(edit_pub_id) if edit_pub_id > 0 else None
    keep_recurring = bool(
        existing_pub
        and int(existing_pub.get("is_recurring") or 0) == 1
        and str(existing_pub.get("status") or "") == "active"
    )

    if edit_pub_id > 0:
        ok = update_publication_record(
            edit_pub_id,
            title=title,
            content_text=content_text,
            media_type=media_type,
            file_id=file_id,
            target_type="chat_list",
            target_value=target_value,
            status="active" if keep_recurring else "sending",
            is_recurring=1 if keep_recurring else 0,
            repeat_every_minutes=int(existing_pub.get("repeat_every_minutes") or 60) if keep_recurring else None,
            recurrence_type=str(existing_pub.get("recurrence_type") or "interval") if keep_recurring else None,
            next_run_at=str(existing_pub.get("next_run_at") or "").strip() if keep_recurring else None,
            scheduled_at=str(existing_pub.get("scheduled_at") or "").strip() if keep_recurring else None,
        )
        if not ok:
            await bot.send_message(chat_id, "❌ שגיאה בעדכון פרסום.")
            return
        replace_publication_buttons_record(edit_pub_id, buttons)
        pub_id = edit_pub_id
    else:
        pub_id = create_publication_record(
            title=title,
            content_text=content_text,
            media_type=media_type,
            file_id=file_id,
            target_type="chat_list",
            target_value=target_value,
            status="sending",
            created_by=merchant_id,
            buttons=buttons,
        )
    if pub_id <= 0:
        await bot.send_message(chat_id, "❌ שגיאה ביצירת פרסום.")
        return

    result = await run_publication_now(bot, pub_id)
    context.user_data[_MERCHANT_EDIT_PUB_ID_KEY] = pub_id
    headline = "✅ <b>הפרסום נשלח</b>"
    if edit_pub_id > 0:
        headline = "✅ <b>הפרסום עודכן ונשלח</b>"
    targets_line = "\n".join(f"• {str(ch.get('display_name') or ch.get('channel_key') or '')}" for ch in selected_channels[:6])
    if len(selected_channels) > 6:
        targets_line += f"\n• ועוד {len(selected_channels) - 6}"
    await bot.send_message(
        chat_id,
        (
            f"{headline}\n\n"
            f"📨 נשלחו: <b>{result.get('sent', 0)}</b>\n"
            f"❌ נכשלו: <b>{result.get('failed', 0)}</b>\n"
            f"🎯 יעדים ייחודיים: <b>{result.get('total', 0)}</b>\n\n"
            f"📡 נשלח אל:\n{targets_line or '• ללא יעד'}"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
        ]),
    )


async def _show_public_reviews(
    bot: Bot,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    merchant_id: int,
) -> None:
    profile = get_merchant_profile(merchant_id)
    display_name = profile["display_name"] if profile else str(merchant_id)
    reviews = list_merchant_reviews(merchant_id, limit=10)
    count = count_merchant_reviews(merchant_id)
    if reviews:
        lines = [f"• {str(r.get('review_text') or '').strip()}" for r in reviews]
    else:
        lines = ["אין עדיין חוות דעת."]

    bot_username = await _get_bot_username(bot, context)
    await bot.send_message(
        chat_id,
        (
            f"⭐ <b>חוות דעת על {display_name}</b>\n\n"
            f"סה\"כ חוות דעת: <b>{count}</b>\n\n"
            + "\n".join(lines)
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ הגש חוות דעת", url=_merchant_deeplink_url(bot_username, _merchant_deeplink_payload(_MERCHANT_START_REVIEW, merchant_id)))],
            [InlineKeyboardButton("🤖 חזרה לבוט", url=_merchant_deeplink_url(bot_username, _MERCHANT_START_HOME))],
        ]),
    )


async def handle_merchant_start_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not getattr(context, "args", None):
        return False
    if not update.effective_chat or not update.effective_user:
        return False

    payload = str(context.args[0] or "").strip()
    if not payload:
        return False

    if payload == _MERCHANT_START_HOME:
        await render_home(context.bot, update.effective_chat.id, telegram_id=update.effective_user.id)
        return True

    for prefix, state_key, prompt in (
        (_MERCHANT_START_REVIEW, _AWAIT_MERCHANT_REVIEW, "⭐ כתוב עכשיו את חוות הדעת שלך בהודעה אחת."),
        (_MERCHANT_START_CONTACT, _AWAIT_MERCHANT_CONTACT, "📞 כתוב עכשיו את ההודעה שברצונך לשלוח לסוחר."),
    ):
        if payload.startswith(prefix):
            merchant_id_raw = payload[len(prefix):]
            try:
                merchant_id = int(merchant_id_raw)
            except Exception:
                return False
            key = _MERCHANT_REVIEW_TARGET_KEY if state_key == _AWAIT_MERCHANT_REVIEW else _MERCHANT_CONTACT_TARGET_KEY
            context.user_data[_MERCHANT_STATE_KEY] = state_key
            context.user_data[key] = merchant_id
            await context.bot.send_message(update.effective_chat.id, prompt)
            return True

    if payload.startswith(_MERCHANT_START_REVIEWS):
        try:
            merchant_id = int(payload[len(_MERCHANT_START_REVIEWS):])
        except Exception:
            return False
        await _show_public_reviews(context.bot, update.effective_chat.id, context, merchant_id)
        return True

    return False


async def handle_merchant_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = str(context.user_data.get(_MERCHANT_STATE_KEY) or "")
    if not state or not update.message or not update.effective_user:
        return False

    if state == _AWAIT_MERCHANT_TEXT:
        content = (update.message.text or "").strip()
        if not content:
            await update.message.reply_text(
                "✍️ שלח טקסט לפרסום.",
                reply_markup=_kb_merchant_cancel_input(),
            )
            return True
        draft = _get_merchant_draft(context)
        draft["content_text"] = content
        allowed_channels = list_merchant_allowed_channel_records(update.effective_user.id)
        capability_flags = get_merchant_capability_flags(update.effective_user.id)
        _, draft_state = _ensure_merchant_draft_record(
            context,
            update.effective_user.id,
            allowed_channels,
            capability_flags,
        )
        if draft_state == "blocked":
            context.user_data.pop(_MERCHANT_STATE_KEY, None)
            limit = _merchant_open_publication_limit(update.effective_user.id, capability_flags)
            await update.message.reply_text(
                f"⛔ הגעת למכסה המותרת ({limit}) ולא ניתן לפתוח עוד פרסום כרגע.",
                reply_markup=_kb_merchant_back_to_compose(),
            )
            return True
        if draft_state == "error":
            await update.message.reply_text(
                "❌ שגיאה בשמירת הטיוטה.",
                reply_markup=_kb_merchant_back_to_compose(),
            )
            return True
        context.user_data.pop(_MERCHANT_STATE_KEY, None)
        await _send_merchant_compose_screen(
            context.bot,
            update.effective_chat.id,
            context,
            update.effective_user.id,
            allowed_channels,
            capability_flags,
        )
        return True

    if state == _AWAIT_MERCHANT_MEDIA:
        media_type = None
        file_id = None
        if update.message.photo:
            media_type = "photo"
            file_id = update.message.photo[-1].file_id
        elif update.message.video:
            media_type = "video"
            file_id = update.message.video.file_id
        elif update.message.animation:
            media_type = "animation"
            file_id = update.message.animation.file_id
        elif update.message.document:
            media_type = "document"
            file_id = update.message.document.file_id
        elif update.message.audio:
            media_type = "audio"
            file_id = update.message.audio.file_id
        if not media_type or not file_id:
            await update.message.reply_text(
                "🖼️ שלח תמונה, וידאו, אנימציה, מסמך או אודיו.",
                reply_markup=_kb_merchant_cancel_input(),
            )
            return True

        capability_flags = get_merchant_capability_flags(update.effective_user.id)
        media_perm_by_type = {
            "photo": "user.media.image",
            "video": "user.media.video",
            "animation": "user.media.animation",
            "document": "user.media.document",
            "audio": "user.media.audio",
        }
        required_perm = media_perm_by_type.get(media_type)
        if required_perm and not capability_flags.get(required_perm):
            await update.message.reply_text(
                "⛔ אין לך הרשאה לסוג המדיה הזה.",
                reply_markup=_kb_merchant_cancel_input(),
            )
            return True
        draft = _get_merchant_draft(context)
        draft["media_type"] = media_type
        draft["file_id"] = file_id
        allowed_channels = list_merchant_allowed_channel_records(update.effective_user.id)
        _, draft_state = _ensure_merchant_draft_record(
            context,
            update.effective_user.id,
            allowed_channels,
            capability_flags,
        )
        if draft_state == "blocked":
            context.user_data.pop(_MERCHANT_STATE_KEY, None)
            limit = _merchant_open_publication_limit(update.effective_user.id, capability_flags)
            await update.message.reply_text(
                f"⛔ הגעת למכסה המותרת ({limit}) ולא ניתן לפתוח עוד פרסום כרגע.",
                reply_markup=_kb_merchant_back_to_compose(),
            )
            return True
        if draft_state == "error":
            await update.message.reply_text(
                "❌ שגיאה בשמירת הטיוטה.",
                reply_markup=_kb_merchant_back_to_compose(),
            )
            return True
        context.user_data.pop(_MERCHANT_STATE_KEY, None)
        await _send_merchant_compose_screen(
            context.bot,
            update.effective_chat.id,
            context,
            update.effective_user.id,
            allowed_channels,
            get_merchant_capability_flags(update.effective_user.id),
        )
        return True

    if state == _AWAIT_MERCHANT_REVIEW:
        merchant_id = int(context.user_data.pop(_MERCHANT_REVIEW_TARGET_KEY, 0) or 0)
        context.user_data.pop(_MERCHANT_STATE_KEY, None)
        review_text = (update.message.text or "").strip()
        if merchant_id <= 0 or not review_text:
            await update.message.reply_text("⚠️ לא ניתן לשמור חוות דעת ריקה.")
            return True
        reviewer_name = update.effective_user.full_name or update.effective_user.username or str(update.effective_user.id)
        create_merchant_review(merchant_id, update.effective_user.id, reviewer_name, review_text)
        await update.message.reply_text("✅ חוות הדעת נשמרה בהצלחה.")
        await _show_public_reviews(context.bot, update.effective_chat.id, context, merchant_id)
        return True

    if state == _AWAIT_MERCHANT_CONTACT:
        merchant_id = int(context.user_data.pop(_MERCHANT_CONTACT_TARGET_KEY, 0) or 0)
        context.user_data.pop(_MERCHANT_STATE_KEY, None)
        content = (update.message.text or "").strip()
        if merchant_id <= 0 or not content:
            await update.message.reply_text("⚠️ שלח טקסט תקין להודעה.")
            return True
        profile = get_merchant_profile(merchant_id)
        target_merchant_id = int(profile.get("telegram_id") or 0) if profile else merchant_id
        if target_merchant_id <= 0:
            await update.message.reply_text("⚠️ לא נמצא בעל הפרסום לקבלת ההודעה.")
            return True
        try:
            await context.bot.send_message(
                target_merchant_id,
                (
                    "📞 <b>פנייה חדשה לגבי פרסום</b>\n\n"
                    f"👤 מאת: <b>{update.effective_user.full_name}</b>\n"
                    f"🆔 משתמש: <code>{update.effective_user.id}</code>\n\n"
                    f"{content}"
                ),
                parse_mode="HTML",
            )
            await update.message.reply_text("✅ ההודעה נשלחה לבעל הפרסום.")
        except Exception:
            await update.message.reply_text("⚠️ כרגע לא ניתן להעביר את ההודעה לבעל הפרסום.")
        return True

    return False


def _is_contact_request_text(message_text: str) -> bool:
    if not message_text:
        return False
    for label in _CONTACT_CATEGORIES.values():
        if message_text.startswith(f"{label}\n"):
            return True
    return False


def _has_pending_contact_request(messages: list[dict]) -> bool:
    """True when the newest relevant message indicates a waiting contact request.

    Relevant messages are:
    - subscriber messages that match contact-request format
    - admin replies in the same chat
    """
    for m in reversed(messages):
        role = m.get("sender_role")
        text = m.get("message_text") or ""
        if role == "admin":
            return False
        if role == "subscriber" and _is_contact_request_text(text):
            return True
    return False


def _contact_categories_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 פנייה כללית", callback_data="pub:user:contactcat:general")],
        [InlineKeyboardButton("⚠️ תלונה", callback_data="pub:user:contactcat:complaint")],
        [InlineKeyboardButton("💡 הצעה", callback_data="pub:user:contactcat:suggestion")],
        [InlineKeyboardButton("❓ שאלה", callback_data="pub:user:contactcat:question")],
        [InlineKeyboardButton("🆘 דיווח על תקלה", callback_data="pub:user:contactcat:bug")],
        [InlineKeyboardButton("⬅️ חזרה", callback_data="pub:user:home")],
    ])


async def _notify_admin_contact_open(
    bot: Bot,
    user,
    subscriber_id: int,
    chat_id: int,
) -> None:
    username_line = f"👤 Username: @{user.username}\n" if user.username else ""
    ts = now_il().strftime("%d.%m.%Y %H:%M")
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📞 <b>נפתחה בקשת צור קשר חדשה</b>\n\n"
            f"👤 שם: <b>{user.full_name}</b>\n"
            f"{username_line}"
            f"🆔 Telegram ID: <code>{user.id}</code>\n"
            f"🕒 תאריך ושעה: <b>{ts}</b>"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 פתח שיחה", callback_data=f"SUBS_CHAT_OPEN_{subscriber_id}_{chat_id}")],
        ]),
        parse_mode="HTML",
    )


async def _notify_admin_contact_message(
    bot: Bot,
    user,
    subscriber_id: int,
    chat_id: int,
    category_label: str,
    content: str,
) -> None:
    username_line = f"👤 Username: @{user.username}\n" if user.username else ""
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📩 <b>התקבלה פנייה חדשה ממשתמש</b>\n\n"
            f"👤 שם: <b>{user.full_name}</b>\n"
            f"{username_line}"
            f"🆔 Telegram ID: <code>{user.id}</code>\n"
            f"🏷️ סוג פנייה: <b>{category_label}</b>\n"
            f"💬 תוכן הפנייה:\n{content}"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 פתח שיחה", callback_data=f"SUBS_CHAT_OPEN_{subscriber_id}_{chat_id}")],
        ]),
        parse_mode="HTML",
    )


async def handle_contact_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get(_CONTACT_STATE_KEY)
    if state != "awaiting_contact_text":
        return False

    if not update.message or not update.effective_user:
        return False

    content = (update.message.text or "").strip()
    if not content:
        await update.message.reply_text("✍️ אנא כתוב את תוכן הפנייה בהודעת טקסט.")
        return True

    subscriber_id = int(context.user_data.get(_CONTACT_SUBSCRIBER_ID_KEY) or 0)
    chat_id = int(context.user_data.get(_CONTACT_CHAT_ID_KEY) or 0)
    category_key = str(context.user_data.get(_CONTACT_CATEGORY_KEY) or "general")
    category_label = _CONTACT_CATEGORIES.get(category_key, _CONTACT_CATEGORIES["general"])

    if subscriber_id <= 0:
        subscriber = register_or_touch_subscriber(update.effective_user)
        subscriber_id = int(subscriber["id"])
    if chat_id <= 0:
        open_chat = get_open_subscriber_chat(subscriber_id)
        chat_id = int(open_chat["id"]) if open_chat else int(open_subscriber_chat(subscriber_id, ADMIN_ID))

    add_subscriber_chat_message(
        chat_id=chat_id,
        sender_role="subscriber",
        sender_id=update.effective_user.id,
        message_text=f"{category_label}\n{content}",
    )

    try:
        track_subscriber_activity(
            subscriber_id=subscriber_id,
            event_key="contact_request",
            payload=category_key,
            increment_basic_activity=True,
        )
    except Exception:
        pass

    try:
        await _notify_admin_contact_message(
            context.bot,
            update.effective_user,
            subscriber_id,
            chat_id,
            category_label,
            content,
        )
    except Exception:
        pass

    context.user_data.pop(_CONTACT_STATE_KEY, None)
    context.user_data.pop(_CONTACT_CATEGORY_KEY, None)
    context.user_data.pop(_CONTACT_SUBSCRIBER_ID_KEY, None)
    context.user_data.pop(_CONTACT_CHAT_ID_KEY, None)
    context.user_data[_SUPPORT_CHAT_SUPPRESSED_KEY] = True

    await update.message.reply_text(
        "✅ הפנייה נשלחה בהצלחה. צוות ההנהלה יחזור אליך בהקדם.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזרה", callback_data="pub:user:home")],
        ]),
    )
    return True


# ---------------------------------------------------------------------------
# המרת כפתור DB → InlineKeyboardButton
# ---------------------------------------------------------------------------

def _db_btn_to_tg(btn) -> Optional[InlineKeyboardButton]:
    """
    ממיר שורת publishing_buttons ל-InlineKeyboardButton.
    מחזיר None אם הסוג לא מוכר או חסר ערך הכרחי.
    """
    btype = btn["button_type"]
    label = btn["label"]
    value = btn["value"] or ""

    try:
        if btype == "text":
            return InlineKeyboardButton(label, callback_data=f"pub:user:msg:{btn['id']}")

        elif btype == "url":
            if not value.startswith(("http://", "https://", "tg://")):
                logger.warning("Button %d has invalid URL: %s", btn["id"], value)
                return None
            return InlineKeyboardButton(label, url=value)

        elif btype == "page_link":
            # שורש הבאג ההיסטורי: פעם הייתה כאן נפילה-לאחור ל-`value`
            # (`target = btn["target_page_id"] or value`) שיכלה לחשוף טקסט
            # ישן/ארוך שנשאר תקוע בעמודת value לתוך ה-callback_data.
            # כעת: page_link מציית *רק* ל-target_page_id. אם הוא חסר,
            # או מצביע לעמוד שלא קיים, או שה-callback_data שייווצר חורג
            # ממגבלת טלגרם (64 בתים) — הכפתור מושמט לגמרי במקום לקרוס.
            target = btn["target_page_id"]
            if not target:
                logger.warning(
                    "Button %d (page_link, label='%s') has no target_page_id — "
                    "omitting from keyboard", btn["id"], label,
                )
                return None

            target_page = pub_get_page_by_id(target)
            if target_page is None:
                logger.warning(
                    "Button %d (page_link, label='%s') target_page_id=%s does not "
                    "exist — omitting from keyboard", btn["id"], label, target,
                )
                return None

            callback_data = f"pub:user:page:{target}"
            if len(callback_data) > 64:
                logger.warning(
                    "Button %d (page_link, label='%s') callback_data exceeds 64 "
                    "chars (%d) — omitting from keyboard",
                    btn["id"], label, len(callback_data),
                )
                return None

            return InlineKeyboardButton(label, callback_data=callback_data)

        elif btype in ("phone", "email"):
            return InlineKeyboardButton(label, callback_data=f"pub:user:msg:{btn['id']}")

        elif btype == "location":
            return InlineKeyboardButton(label, callback_data=f"pub:user:loc:{btn['id']}")

        elif btype == "share":
            return InlineKeyboardButton(label, switch_inline_query="")

        else:
            logger.warning("Unknown button type '%s' for btn id=%d", btype, btn["id"])
            return None

    except Exception as exc:
        logger.error("_db_btn_to_tg failed for btn %d: %s", btn["id"], exc, exc_info=True)
        return None


# כפתור עם עד _SHORT_LABEL_MAX תווים נחשב "קצר" ומוזווג עם קצר אחר.
# כפתור ארוך יותר מקבל שורה מלאה לעצמו.
_SHORT_LABEL_MAX = 11


def _row_sort_key(btn) -> tuple:
    """מפתח מיון תואם sqlite3.Row — ללא שימוש ב-.get()."""
    row_index = btn["row_index"] or 0
    try:
        sort_order = btn["sort_order"]
        sort_order = sort_order if sort_order is not None else 0
    except IndexError:
        sort_order = 0
    return (row_index, sort_order)


def _build_keyboard(
    buttons: list,
    include_system: bool = False,
    telegram_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    בונה InlineKeyboardMarkup בפריסה מקצועית — greedy packing.

    כפתורים קצרים (label <= _SHORT_LABEL_MAX) מוזווגים לשורה אחת.
    כפתורים ארוכים מקבלים שורה מלאה לעצמם.
    כפתורים כבויים (is_active=0) מושמטים.
    כפתורי המערכת (_SYSTEM_BUTTONS) מוצמדים תמיד לתחתית כש-include_system=True.
    """
    active = [b for b in buttons if b["is_active"]]
    active.sort(key=_row_sort_key)

    rows: list[list[InlineKeyboardButton]] = []
    pending: Optional[InlineKeyboardButton] = None

    for btn in active:
        tg = _db_btn_to_tg(btn)
        if tg is None:
            continue
        is_short = len(tg.text) <= _SHORT_LABEL_MAX
        if is_short:
            if pending is not None:
                rows.append([pending, tg])
                pending = None
            else:
                pending = tg
        else:
            if pending is not None:
                rows.append([pending])
                pending = None
            rows.append([tg])

    if pending is not None:
        rows.append([pending])

    if include_system:
        rows.extend(_build_system_buttons(telegram_id))
    return InlineKeyboardMarkup(rows)


def _back_keyboard(btn) -> InlineKeyboardMarkup:
    """מקלדת עם כפתור חזור לעמוד המקור של כפתור התוכן."""
    page_id = btn["page_id"]
    back_cb = f"pub:user:page:{page_id}" if page_id else "pub:user:home"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("חזור", callback_data=back_cb)]
    ])


# ---------------------------------------------------------------------------
# _send_media — helper פנימי
# ---------------------------------------------------------------------------

async def _send_media(
    bot: Bot,
    chat_id: int,
    file_id: str,
    media_type: Optional[str],
    caption: str,
    keyboard: InlineKeyboardMarkup,
):
    """
    שולח מדיה לפי media_type ומחזיר את אובייקט ה-Message.

    media_type:
        "photo"      -> send_photo
        "animation"  -> send_animation
        "video"      -> send_video
        "audio"      -> send_audio
        "voice"      -> send_voice
        "document"   -> send_document
        "video_note" -> send_video_note  (ללא caption/parse_mode)
        "sticker"    -> send_sticker     (ללא caption/parse_mode)
        כל ערך אחר / None -> send_photo (ברירת מחדל)
    """
    kwargs = dict(
        chat_id=chat_id,
        caption=caption,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    kwargs_no_caption = dict(
        chat_id=chat_id,
        reply_markup=keyboard,
    )

    if media_type == "animation":
        return await bot.send_animation(animation=file_id, **kwargs)
    elif media_type == "video":
        return await bot.send_video(video=file_id, **kwargs)
    elif media_type == "audio":
        return await bot.send_audio(audio=file_id, **kwargs)
    elif media_type == "voice":
        return await bot.send_voice(voice=file_id, **kwargs)
    elif media_type == "document":
        return await bot.send_document(document=file_id, **kwargs)
    elif media_type == "video_note":
        return await bot.send_video_note(video_note=file_id, **kwargs_no_caption)
    elif media_type == "sticker":
        return await bot.send_sticker(sticker=file_id, **kwargs_no_caption)
    else:
        return await bot.send_photo(photo=file_id, **kwargs)


# ---------------------------------------------------------------------------
# render_home
# ---------------------------------------------------------------------------

async def render_home(
    bot: Bot,
    chat_id: int,
    telegram_id: Optional[int] = None,
) -> None:
    """
    שולח את דף הבית למשתמש.

    לפני שליחה — מוחק את הודעת הבית הקודמת של אותו chat_id.
    אם דף הבית לא מוגדר או כבוי — שולח הודעת ברירת-מחדל עם כפתורי מערכת בלבד.
    """
    prev_msg_id = _last_home_msg.pop(chat_id, None)
    if prev_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
        except Exception:
            pass

    try:
        _raw  = get_home()
        home  = dict(_raw) if _raw is not None else None
        text  = "ברוך הבא!"
        image = None

        if home and home["is_active"]:
            text     = home["text"] or text
            image    = home["image_file_id"]
            buttons  = pub_get_buttons_for_home(1)
            keyboard = _build_keyboard(buttons, include_system=True, telegram_id=telegram_id)
        else:
            keyboard = InlineKeyboardMarkup(_build_system_buttons(telegram_id))

        if image:
            msg = await _send_media(
                bot, chat_id, image,
                media_type=home.get("media_type"),
                caption=text,
                keyboard=keyboard,
            )
        else:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        if msg:
            _last_home_msg[chat_id] = msg.message_id

    except TelegramError as exc:
        logger.error("render_home failed for chat_id=%d: %s", chat_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# _get_allowed_slugs
# ---------------------------------------------------------------------------

def _get_allowed_slugs(telegram_id: int) -> set:
    """
    מחזיר קבוצת catalog slugs שהמשתמש מורשה לגשת אליהם.

    מקורות:
      - get_auto_catalogs_for_user: קטלוגים לפי audience/סוג-משתמש
      - get_user_catalog_slugs: קטלוגים שהוקצו ידנית

    בכשל — מחזיר קבוצה ריקה (fail-closed).
    """
    try:
        auto_catalogs = get_auto_catalogs_for_user(telegram_id)
        manual_slugs  = get_user_catalog_slugs(telegram_id)
        auto_slugs    = {cat["slug"] for cat in auto_catalogs}
        combined      = auto_slugs | manual_slugs
        return combined
    except Exception as exc:
        logger.error(
            "_get_allowed_slugs failed for telegram_id=%s: %s", telegram_id, exc
        )
        return set()


# ---------------------------------------------------------------------------
# _filter_pages_for_user
# ---------------------------------------------------------------------------

def _filter_pages_for_user(
    pages: list,
    telegram_id: Optional[int],
    allowed_slugs: Optional[set] = None,
) -> list:
    """
    מסנן רשימת עמודים לפי הרשאות המשתמש.

    כללי סינון:
      - page_type != 'catalog'  -> תמיד מוצג
      - catalog_slug חסר/ריק   -> תמיד מוצג (תאימות לאחור)
      - catalog_slug קיים       -> מוצג אם ה-slug נמצא ב-allowed_slugs

    אם telegram_id הוא None — מחזיר את הרשימה ללא סינון.
    """
    if telegram_id is None:
        return pages

    catalog_pages_with_slug = [
        p for p in pages
        if p["page_type"] == "catalog" and p["catalog_slug"]
    ]
    if not catalog_pages_with_slug:
        return pages

    if allowed_slugs is None:
        try:
            allowed_slugs = _get_allowed_slugs(telegram_id)
        except Exception as exc:
            logger.error("_filter_pages_for_user failed for telegram_id=%s: %s", telegram_id, exc)
            return [p for p in pages if p["page_type"] != "catalog" or not p["catalog_slug"]]

    result = []
    for page in pages:
        if page["page_type"] != "catalog":
            result.append(page)
        elif not page["catalog_slug"]:
            result.append(page)
        elif page["catalog_slug"] in allowed_slugs:
            result.append(page)

    return result


# ---------------------------------------------------------------------------
# _filter_buttons_for_user
# ---------------------------------------------------------------------------

def _filter_buttons_for_user(
    buttons: list,
    telegram_id: Optional[int],
    allowed_slugs: Optional[set] = None,
) -> list:
    """
    מסנן כפתורי page_link שמובילים לקטלוגים שהמשתמש אינו מורשה לגשת אליהם.

    כללי סינון:
      - כפתורים שאינם page_link              -> תמיד מוצגים
      - page_link ללא target_page_id          -> תמיד מוצגים
      - page_link שיעדו אינו קטלוג עם slug   -> תמיד מוצגים
      - page_link שיעדו קטלוג עם slug חסום  -> מושמטים

    אם telegram_id הוא None — מחזיר את הרשימה ללא סינון.
    """
    if telegram_id is None:
        return buttons

    link_buttons = [
        btn for btn in buttons
        if btn["button_type"] == "page_link" and btn["target_page_id"]
    ]
    if not link_buttons:
        return buttons

    if allowed_slugs is None:
        allowed_slugs = _get_allowed_slugs(telegram_id)

    blocked_target_ids: set = set()
    for btn in link_buttons:
        target_raw = pub_get_page_by_id(btn["target_page_id"])
        if target_raw is None:
            continue
        if target_raw["page_type"] == "catalog" and target_raw["catalog_slug"]:
            if target_raw["catalog_slug"] not in allowed_slugs:
                blocked_target_ids.add(btn["target_page_id"])

    if not blocked_target_ids:
        return buttons

    return [
        btn for btn in buttons
        if not (
            btn["button_type"] == "page_link"
            and btn["target_page_id"] in blocked_target_ids
        )
    ]


# ---------------------------------------------------------------------------
# render_page
# ---------------------------------------------------------------------------

async def render_page(
    bot: Bot,
    chat_id: int,
    page_id: int,
    telegram_id: Optional[int] = None,
) -> bool:
    """
    שולח עמוד פרסום למשתמש כהודעה חדשה.

    Returns:
        True אם הצליח, False בכשל.
    """
    try:
        _raw = pub_get_page_by_id(page_id)
        if _raw is None or not _raw["is_active"]:
            return False
        page = dict(_raw)

        allowed_slugs: Optional[set] = None
        if telegram_id is not None:
            allowed_slugs = _get_allowed_slugs(telegram_id)

        page_slug = page.get("catalog_slug")
        if page_slug and telegram_id is not None:
            if allowed_slugs is not None and page_slug not in allowed_slugs:
                logger.info(
                    "render_page: access denied telegram_id=%s page_id=%d slug=%s",
                    telegram_id, page_id, page_slug,
                )
                return False

        active_sub = [dict(p) for p in pub_get_pages_by_parent(page_id) if p["is_active"]]
        sub_pages  = _filter_pages_for_user(active_sub, telegram_id, allowed_slugs)
        nav_rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton(
                f"{'📂' if sp['page_type'] == 'catalog' else '📄'} {sp['title']}",
                callback_data=f"pub:user:page:{sp['id']}",
            )]
            for sp in sub_pages
        ]

        buttons = pub_get_buttons_for_page(page_id)
        buttons = _filter_buttons_for_user(buttons, telegram_id, allowed_slugs)
        db_kb   = _build_keyboard(buttons, include_system=False)

        back_cb = (
            f"pub:user:page:{page['parent_id']}"
            if page["parent_id"]
            else "pub:user:home"
        )
        all_rows = (
            nav_rows
            + list(db_kb.inline_keyboard)
            + [[InlineKeyboardButton("חזור", callback_data=back_cb)]]
        )
        keyboard = InlineKeyboardMarkup(all_rows)

        caption = f"<b>{page['title']}</b>"
        if page["text"]:
            caption += f"\n\n{page['text']}"
        image = page["image_file_id"]

        if image:
            await _send_media(
                bot, chat_id, image,
                media_type=page.get("media_type"),
                caption=caption,
                keyboard=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return True

    except TelegramError as exc:
        logger.error(
            "render_page failed for chat_id=%d page_id=%d: %s",
            chat_id, page_id, exc, exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# handle_user_nav — callback handler לניווט משתמש
# ---------------------------------------------------------------------------

async def _get_required_channel_statuses(
    bot: Bot,
    telegram_id: int,
    channels: list[dict],
) -> list[dict]:
    statuses: list[dict] = []
    for channel in channels:
        chat_ref = get_channel_membership_chat_ref(channel)
        status = "unknown"
        if chat_ref:
            try:
                member = await bot.get_chat_member(chat_id=chat_ref, user_id=telegram_id)
                if member.status not in {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}:
                    status = "joined"
                else:
                    status = "missing"
            except TelegramError as exc:
                message = str(exc).lower()
                if any(token in message for token in (
                    "user not found",
                    "participant_id_invalid",
                    "chat not found",
                )):
                    status = "missing"
                else:
                    status = "unknown"
            except Exception:
                status = "unknown"
        statuses.append({"channel": channel, "status": status})
    return statuses


def _build_required_join_buttons(items: list[dict]) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        if item.get("status") == "joined":
            continue
        join_url = get_channel_join_url(item["channel"])
        if not join_url:
            continue
        rows.append([
            InlineKeyboardButton(
                f"🔗 הצטרף: {item['channel']['display_name']}",
                url=join_url,
            )
        ])
    return rows


async def _send_required_channels_gate(bot: Bot, chat_id: int, items: list[dict]) -> None:
    lines = []
    has_unknown = False
    for item in items:
        prefix = "❌" if item["status"] == "missing" else "⚠️"
        if item["status"] == "unknown":
            has_unknown = True
        lines.append(f"{prefix} {item['channel']['display_name']}")

    extra_note = ""
    if has_unknown:
        extra_note = (
            "\n\nℹ️ בחלק מהערוצים הפרטיים אין אימות אוטומטי מלא. "
            "כדי לאמת אותם בזמן אמת צריך להגדיר לערוץ גם מזהה בדיקה: -100... או @username."
        )

    await bot.send_message(
        chat_id,
        (
            "🔐 <b>לפני פרסום צריך להשלים הצטרפות</b>\n\n"
            "צריך להצטרף לכל הערוצים שמסומנים ב-❌ ואז לחזור לבדיקה מחדש.\n\n"
            + "\n".join(lines)
            + extra_note
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            _build_required_join_buttons(items)
            + [[InlineKeyboardButton("🔄 בדוק שוב", callback_data="pub:user:merchant")]]
            + [[InlineKeyboardButton("🔁 הפעל מחדש", callback_data="RESTART_BOT_PENDING")]]
            + [[InlineKeyboardButton("⬅️ חזרה לבית", callback_data="pub:user:home")]]
        ),
    )


async def _send_required_channels_status(
    bot: Bot,
    chat_id: int,
    statuses: list[dict],
    all_joined: bool,
) -> None:
    if not statuses:
        await bot.send_message(
            chat_id,
            "🔐 אין כרגע ערוצי חובה שמוגדרים לך.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
            ]),
        )
        return

    lines = []
    for item in statuses:
        if item["status"] == "joined":
            mark = "✅"
        elif item["status"] == "missing":
            mark = "❌"
        else:
            mark = "ℹ️"
        lines.append(f"{mark} {item['channel']['display_name']}")

    only_unknown = bool(statuses) and all(item["status"] == "unknown" for item in statuses)

    header = (
        "✅ <b>הצטרפות הושלמה לכל ערוצי החובה</b>\n\n"
        if all_joined
        else "🔐 <b>הצטרפות לערוצים לפני פרסום</b>\n\n"
    )

    if only_unknown:
        header += (
            "אלו ערוצים פרטיים שלא ניתן לאמת אוטומטית בהגדרה הנוכחית.\n"
            "כדי אימות מלא בזמן אמת יש להגדיר להם מזהה בדיקה: -100... או @username.\n\n"
        )

    has_missing = any(item["status"] == "missing" for item in statuses)
    if not has_missing and not all_joined:
        header += "ℹ️ כרגע אין חסימת הצטרפות פעילה, אבל יש ערוצים שלא אומתו אוטומטית.\n\n"

    rows = _build_required_join_buttons(statuses)
    rows.append([InlineKeyboardButton("🔄 בדוק שוב", callback_data="pub:user:merchant:required")])
    rows.append([InlineKeyboardButton("▶️ המשך לפרסום", callback_data="pub:user:merchant:start")])
    rows.append([InlineKeyboardButton("🔁 הפעל מחדש", callback_data="RESTART_BOT_PENDING")])
    rows.append([InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")])

    await bot.send_message(
        chat_id,
        header + "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _get_selected_merchant_channels(
    context: ContextTypes.DEFAULT_TYPE,
    allowed_channel_records: list[dict],
) -> set[str]:
    allowed_keys = {str(ch.get("channel_key") or "") for ch in allowed_channel_records}
    allowed_keys.discard("")
    raw_selected = context.user_data.get(_MERCHANT_SELECTED_CHANNELS_KEY)
    selected: set[str] = set(raw_selected) if isinstance(raw_selected, list) else set(allowed_keys)
    selected &= allowed_keys
    context.user_data[_MERCHANT_SELECTED_CHANNELS_KEY] = sorted(selected)
    return selected


async def _send_merchant_start_screen(
    bot: Bot,
    chat_id: int,
    allowed_channel_records: list[dict],
    selected_channel_keys: set[str],
    capability_flags: dict[str, bool],
    *,
    publication_mode: str = "regular",
    back_callback_data: str = "pub:user:merchant",
) -> None:
    allowed_media_labels = []
    if capability_flags.get("user.media.image"):
        allowed_media_labels.append("תמונה")
    if capability_flags.get("user.media.video"):
        allowed_media_labels.append("וידאו")
    if capability_flags.get("user.media.animation"):
        allowed_media_labels.append("אנימציה")
    if capability_flags.get("user.media.document"):
        allowed_media_labels.append("מסמך")
    if capability_flags.get("user.media.audio"):
        allowed_media_labels.append("אודיו")
    media_line = " / ".join(allowed_media_labels) if allowed_media_labels else "טקסט בלבד"

    lines = []
    rows: list[list[InlineKeyboardButton]] = []
    for channel in allowed_channel_records:
        key = str(channel.get("channel_key") or "")
        if not key:
            continue
        mark = "✅" if key in selected_channel_keys else "⬜"
        lines.append(f"{mark} {channel['display_name']}")
        rows.append([
            InlineKeyboardButton(
                f"{mark} {channel['display_name']}",
                callback_data=f"pub:user:merchant:pickch:{key}",
            )
        ])

    rows.extend([
        [InlineKeyboardButton("▶️ המשך", callback_data="pub:user:merchant:startconfirm")],
        [InlineKeyboardButton("⬅️ חזרה", callback_data=back_callback_data)],
    ])

    await bot.send_message(
        chat_id,
        (
            f"▶️ <b>התחל {'פרסום מרובה' if publication_mode == 'multi' else 'פרסום רגיל'}</b>\n\n"
            f"מותר לך כרגע להעלות: <b>{media_line}</b>\n"
            "בחר את הערוצים שאליהם תרצה לפרסם:\n\n"
            + "\n".join(lines)
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _send_merchant_channels_picker_screen(
    bot: Bot,
    chat_id: int,
    allowed_channel_records: list[dict],
    selected_channel_keys: set[str],
    *,
    publication_mode: str = "regular",
    back_callback_data: str = "pub:user:merchant",
) -> None:
    lines = []
    rows: list[list[InlineKeyboardButton]] = []
    for channel in allowed_channel_records:
        key = str(channel.get("channel_key") or "")
        if not key:
            continue
        mark = "✅" if key in selected_channel_keys else "⬜"
        lines.append(f"{mark} {channel['display_name']}")
        rows.append([
            InlineKeyboardButton(
                f"{mark} {channel['display_name']}",
                callback_data=f"pub:user:merchant:pickch:{key}",
            )
        ])

    rows.extend([
        [InlineKeyboardButton("▶️ המשך לפרסום", callback_data="pub:user:merchant:startconfirm")],
        [InlineKeyboardButton("⬅️ חזרה", callback_data=back_callback_data)],
    ])

    await bot.send_message(
        chat_id,
        (
            f"📡 <b>{'ערוצי פרסום מרובה' if publication_mode == 'multi' else 'הערוצים שלי'}</b>\n\n"
            "בחר כאן את הערוצים שאליהם הפרסום יישלח כרגע.\n\n"
            + ("\n".join(lines) if lines else "אין עדיין ערוצים מורשים.")
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )

async def handle_user_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    מטפל בכל callback_data שמתחיל ב-pub:user:.

    Patterns:
        pub:user:home         — דף הבית
        pub:user:page:<id>    — ניווט לעמוד
        pub:user:msg:<btn_id> — שליחת הודעה (text / phone / email)
        pub:user:loc:<btn_id> — שליחת מיקום

    עקבי עם PageEngine: מוחק את ההודעה הקיימת ושולח הודעה חדשה.
    """
    query = update.callback_query
    parts   = query.data.split(":")
    action  = parts[2] if len(parts) > 2 else ""
    bot     = context.bot
    chat_id = query.message.chat_id

    try:
        from services.subscribers_service import (
            get_subscriber_card_by_telegram_id,
            track_subscriber_activity,
        )

        subscriber = get_subscriber_card_by_telegram_id(query.from_user.id)
        if subscriber:
            track_subscriber_activity(
                subscriber_id=int(subscriber["id"]),
                event_key=f"pub_nav_{action or 'unknown'}",
                payload=(query.data or "")[:120],
                increment_basic_activity=True,
            )
    except Exception:
        pass

    if action == "page" and len(parts) > 3:
        page_id = int(parts[3])
        _raw    = pub_get_page_by_id(page_id)
        if _raw is not None and _raw["is_active"]:
            page_slug = _raw["catalog_slug"]
            if page_slug:
                allowed = _get_allowed_slugs(query.from_user.id)
                if page_slug not in allowed:
                    await query.answer(
                        "אין לך הרשאה לצפות בתוכן זה.",
                        show_alert=True,
                    )
                    return
        try:
            await query.answer()
        except TelegramError:
            pass
        try:
            await query.message.delete()
        except TelegramError:
            pass
        await render_page(bot, chat_id, page_id, telegram_id=query.from_user.id)
        return

    try:
        await query.answer()
    except TelegramError:
        pass
    try:
        await query.message.delete()
    except TelegramError:
        pass

    if action == "home":
        context.user_data[_SUPPORT_CHAT_SUPPRESSED_KEY] = True
        context.user_data.pop(_CONTACT_STATE_KEY, None)
        context.user_data.pop(_CONTACT_CATEGORY_KEY, None)
        await render_home(bot, chat_id, telegram_id=query.from_user.id)

    elif action == "page" and len(parts) > 3:
        await render_page(bot, chat_id, int(parts[3]), telegram_id=query.from_user.id)

    elif action == "merchant":
        if not is_merchant(query.from_user.id):
            await bot.send_message(chat_id, "⛔ אין לך גישה לאזור הסוחר.")
            await render_home(bot, chat_id, telegram_id=query.from_user.id)
            return

        sub_action = parts[3] if len(parts) > 3 else ""
        if not sub_action:
            _set_merchant_publication_mode(context, "regular")
            has_saved_publications = bool(list_creator_publications(query.from_user.id, limit=1))
            if not has_saved_publications:
                _reset_merchant_publication_state(context, clear_selection=True)

        regular_channel_records = list_merchant_allowed_channel_records(query.from_user.id)
        multi_channel_records = list_merchant_multi_allowed_channel_records(query.from_user.id)
        current_mode = _get_merchant_publication_mode(context)
        if sub_action == "newpub":
            current_mode = "multi"
        allowed_channel_records = multi_channel_records if current_mode == "multi" else regular_channel_records
        required_channel_records = list_merchant_required_channel_records(query.from_user.id)
        channels = [channel["display_name"] for channel in allowed_channel_records]
        regular_channels_count = len(regular_channel_records)
        multi_channels_count = len(multi_channel_records)
        is_hourly = merchant_has_hourly_publish(query.from_user.id)
        capability_flags = get_merchant_capability_flags(query.from_user.id)
        can_start_publication = can_merchant_start_publication(query.from_user.id)
        required_statuses = await _get_required_channel_statuses(bot, query.from_user.id, required_channel_records)
        missing_required = [item for item in required_statuses if item["status"] == "missing"]
        unknown_required = [item for item in required_statuses if item["status"] == "unknown"]
        not_joined_required = [item for item in required_statuses if item["status"] != "joined"]

        required_gate_actions = {
            "compose", "newpub", "start", "startcompose", "pickch", "startconfirm", "settext", "setmedia", "preview", "sendnow", "sendhourly",
            "schedule", "mypubs", "pubview", "pubpreview", "pubedit", "pubrun", "pubhourly", "pubstop", "pubdel",
        }
        if sub_action in required_gate_actions and missing_required:
            await _send_required_channels_gate(bot, chat_id, required_statuses)
            context.user_data[_MERCHANT_REQUIRED_JOIN_LAST_STATE_KEY] = False
            return

        all_required_joined = len(missing_required) == 0
        if required_channel_records:
            prev_join_state = context.user_data.get(_MERCHANT_REQUIRED_JOIN_LAST_STATE_KEY)
            context.user_data[_MERCHANT_REQUIRED_JOIN_LAST_STATE_KEY] = all_required_joined
            if prev_join_state is False and all_required_joined:
                merchant_name = str(query.from_user.full_name or query.from_user.username or query.from_user.id)
                await bot.send_message(
                    chat_id,
                    "✅ לא נשארו חסימות הצטרפות. אפשר להמשיך לפרסום.",
                )
                await _notify_admin_required_join_completed(
                    bot,
                    query.from_user.id,
                    merchant_name,
                    len(required_channel_records),
                )
        else:
            context.user_data.pop(_MERCHANT_REQUIRED_JOIN_LAST_STATE_KEY, None)

        if sub_action in {"compose", "newpub", "start", "startcompose", "pickch", "startconfirm", "settext", "setmedia", "preview", "sendnow", "sendhourly", "cancelinput"}:
            if not _merchant_feature_allowed(capability_flags, "user.merchant.start"):
                await bot.send_message(chat_id, "⛔ אין לך הרשאה: התחל פרסום.")
                return

        if sub_action in {"mypubs", "pubview", "pubpreview", "pubedit", "pubrun", "pubhourly", "pubstop", "pubdel"}:
            if not _merchant_feature_allowed(capability_flags, "user.merchant.publications"):
                await bot.send_message(chat_id, "⛔ אין לך הרשאה: הפרסומים שלי.")
                return

        if sub_action == "required" and not _merchant_feature_allowed(capability_flags, "user.merchant.required"):
            await bot.send_message(chat_id, "⛔ אין לך הרשאה: חובת הצטרפות.")
            return

        if sub_action == "channels" and not _merchant_feature_allowed(capability_flags, "user.merchant.channels"):
            await bot.send_message(chat_id, "⛔ אין לך הרשאה: הערוצים שלי.")
            return

        if sub_action == "status" and not _merchant_feature_allowed(capability_flags, "user.merchant.status"):
            await bot.send_message(chat_id, "⛔ אין לך הרשאה: סטטוס הרשאות.")
            return

        if sub_action == "schedule" and not _merchant_feature_allowed(capability_flags, "user.merchant.schedule"):
            await bot.send_message(chat_id, "⛔ אין לך הרשאה: תזמון פרסום.")
            return

        if sub_action == "required":
            await _send_required_channels_status(
                bot,
                chat_id,
                required_statuses,
                all_joined=(len(missing_required) == 0),
            )
            return

        if sub_action == "compose":
            if current_mode not in {"regular", "multi"}:
                current_mode = "regular"
            _set_merchant_publication_mode(context, current_mode)
            await _send_merchant_compose_screen(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                publication_mode=current_mode,
            )
            return

        if sub_action == "newpub":
            # יצירת פרסום נוסף צריכה להתחיל מטיוטה נפרדת ונקיה.
            if not capability_flags.get("user.publish.multi"):
                await bot.send_message(chat_id, "⛔ אין לך הרשאה לפרסום מרובה.")
                return
            _reset_merchant_publication_state(context, clear_selection=True)
            _set_merchant_publication_mode(context, "multi")
            allowed_channel_records = list_merchant_multi_allowed_channel_records(query.from_user.id)
            if not allowed_channel_records:
                await bot.send_message(
                    chat_id,
                    "⛔ אין לך ערוצים משויכים לפרסום מרובה. מנהל צריך לשייך ערוצים ייעודיים לפרסום מרובה.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                    ]),
                )
                return
            context.user_data[_MERCHANT_SELECTED_CHANNELS_KEY] = []
            await _send_merchant_compose_screen(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                publication_mode="multi",
            )
            await bot.send_message(
                chat_id,
                "🧩 נפתחה טיוטה חדשה ונפרדת. בחר ערוצים ותוכן לפרסום החדש.",
            )
            return

        if sub_action == "cancelinput":
            context.user_data.pop(_MERCHANT_STATE_KEY, None)
            await bot.send_message(chat_id, "✅ בוטל. חזרת לעריכת הפרסום.", reply_markup=_kb_merchant_back_to_compose())
            return

        if sub_action == "mypubs":
            await _show_merchant_publication_list(bot, chat_id, query.from_user.id)
            return

        if sub_action == "pubview" and len(parts) > 4:
            pub_id = int(parts[4])
            pub = get_publication(pub_id)
            if not pub or int(pub.get("created_by") or 0) != query.from_user.id:
                await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
                return
            await _show_merchant_publication_details(bot, chat_id, pub_id)
            return

        if sub_action == "pubpreview" and len(parts) > 4:
            pub_id = int(parts[4])
            pub = get_publication(pub_id)
            if not pub or int(pub.get("created_by") or 0) != query.from_user.id:
                await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
                return
            selected_keys = _detect_selected_keys_from_publication(pub, allowed_channel_records)
            _get_merchant_draft(context, selected_keys)
            draft = context.user_data[_MERCHANT_DRAFT_KEY]
            draft["content_text"] = str(pub.get("content_text") or "")
            draft["media_type"] = str(pub.get("media_type") or "") or None
            draft["file_id"] = str(pub.get("file_id") or "") or None
            context.user_data[_MERCHANT_EDIT_PUB_ID_KEY] = pub_id
            await _send_merchant_publication_preview(bot, chat_id, context, query.from_user.id)
            return

        if sub_action == "pubedit" and len(parts) > 4:
            pub_id = int(parts[4])
            pub = get_publication(pub_id)
            if not pub or int(pub.get("created_by") or 0) != query.from_user.id:
                await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
                return
            selected_keys = _detect_selected_keys_from_publication(pub, allowed_channel_records)
            _get_merchant_draft(context, selected_keys)
            draft = context.user_data[_MERCHANT_DRAFT_KEY]
            draft["content_text"] = str(pub.get("content_text") or "")
            draft["media_type"] = str(pub.get("media_type") or "") or None
            draft["file_id"] = str(pub.get("file_id") or "") or None
            context.user_data[_MERCHANT_EDIT_PUB_ID_KEY] = pub_id
            await _send_merchant_compose_screen(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                publication_mode=current_mode,
            )
            return

        if sub_action == "pubrun" and len(parts) > 4:
            pub_id = int(parts[4])
            pub = get_publication(pub_id)
            if not pub or int(pub.get("created_by") or 0) != query.from_user.id:
                await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
                return
            is_active_recurring = int(pub.get("is_recurring") or 0) == 1 and str(pub.get("status") or "") == "active"
            if is_active_recurring:
                wait_seconds, per_publication_wait = _resolve_manual_wait_seconds(
                    query.from_user.id,
                    capability_flags,
                    pub_id,
                )
                if wait_seconds > 0:
                    await _send_manual_cooldown_message_scoped(
                        bot,
                        chat_id,
                        wait_seconds,
                        per_publication=per_publication_wait,
                    )
                    return
                selected_keys = _detect_selected_keys_from_publication(pub, allowed_channel_records)
                selected_channels = [
                    ch for ch in allowed_channel_records if str(ch.get("channel_key") or "") in selected_keys
                ]
                result = await run_publication_now(bot, pub_id)
                targets_line = "\n".join(
                    f"• {str(ch.get('display_name') or ch.get('channel_key') or '')}" for ch in selected_channels[:6]
                )
                if len(selected_channels) > 6:
                    targets_line += f"\n• ועוד {len(selected_channels) - 6}"
                await bot.send_message(
                    chat_id,
                    (
                        "✅ <b>נשלחה שליחה מיידית נוספת</b>\n\n"
                        f"📨 נשלחו: <b>{result.get('sent', 0)}</b>\n"
                        f"❌ נכשלו: <b>{result.get('failed', 0)}</b>\n"
                        f"🎯 יעדים ייחודיים: <b>{result.get('total', 0)}</b>\n\n"
                        f"📡 נשלח אל:\n{targets_line or '• ללא יעד'}\n\n"
                        "⏱️ הטיימר השעתי נשאר פעיל."
                    ),
                    parse_mode="HTML",
                )
                await _show_merchant_publication_details(bot, chat_id, pub_id)
                return
            selected_keys = _detect_selected_keys_from_publication(pub, allowed_channel_records)
            _get_merchant_draft(context, selected_keys)
            draft = context.user_data[_MERCHANT_DRAFT_KEY]
            draft["content_text"] = str(pub.get("content_text") or "")
            draft["media_type"] = str(pub.get("media_type") or "") or None
            draft["file_id"] = str(pub.get("file_id") or "") or None
            context.user_data[_MERCHANT_EDIT_PUB_ID_KEY] = pub_id
            await _run_merchant_publication_send(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                recurring_hourly=False,
            )
            return

        if sub_action == "pubhourly" and len(parts) > 4:
            pub_id = int(parts[4])
            pub = get_publication(pub_id)
            if not pub or int(pub.get("created_by") or 0) != query.from_user.id:
                await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
                return
            if not merchant_has_hourly_publish(query.from_user.id):
                await bot.send_message(chat_id, "⛔ לא הופעלה עבורך אפשרות פרסום שעתי על ידי מנהל.")
                return
            if int(pub.get("is_recurring") or 0) == 1 and str(pub.get("status") or "") == "active":
                await bot.send_message(chat_id, "ℹ️ פרסום זה כבר מוגדר לאוטומציה כל שעה.")
                await _show_merchant_publication_details(bot, chat_id, pub_id)
                return

            selected_keys = _detect_selected_keys_from_publication(pub, allowed_channel_records)
            _get_merchant_draft(context, selected_keys)
            draft = context.user_data[_MERCHANT_DRAFT_KEY]
            draft["content_text"] = str(pub.get("content_text") or "")
            draft["media_type"] = str(pub.get("media_type") or "") or None
            draft["file_id"] = str(pub.get("file_id") or "") or None
            context.user_data[_MERCHANT_EDIT_PUB_ID_KEY] = pub_id
            await _run_merchant_publication_send(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                recurring_hourly=True,
            )
            return

        if sub_action == "pubstop" and len(parts) > 4:
            pub_id = int(parts[4])
            pub = get_publication(pub_id)
            if not pub or int(pub.get("created_by") or 0) != query.from_user.id:
                await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
                return
            await _cancel_merchant_publication_jobs(context, pub_id)
            update_publication_record(
                pub_id,
                status="canceled",
                is_recurring=0,
                repeat_every_minutes=None,
                recurrence_type=None,
                next_run_at=None,
                scheduled_at=None,
            )
            await bot.send_message(chat_id, "⛔ הפרסום השעתי נעצר.")
            await _show_merchant_publication_details(bot, chat_id, pub_id)
            return

        if sub_action == "pubdel" and len(parts) > 4:
            pub_id = int(parts[4])
            pub = get_publication(pub_id)
            if not pub or int(pub.get("created_by") or 0) != query.from_user.id:
                await bot.send_message(chat_id, "⚠️ הפרסום לא נמצא.")
                return
            await _cancel_merchant_publication_jobs(context, pub_id)
            ok = remove_publication(pub_id)
            if ok:
                if int(context.user_data.get(_MERCHANT_EDIT_PUB_ID_KEY) or 0) == pub_id:
                    _reset_merchant_publication_state(context, clear_selection=False)
                remaining = list_creator_publications(query.from_user.id, limit=1)
                if not remaining:
                    _reset_merchant_publication_state(context, clear_selection=True)
                    await bot.send_message(chat_id, "✅ הפרסום נמחק. לא נשארו פרסומים שמורים, והטיוטה אופסה.")
                else:
                    await bot.send_message(chat_id, "✅ הפרסום נמחק.")
            else:
                await bot.send_message(chat_id, "❌ מחיקת פרסום נכשלה.")
            await _show_merchant_publication_list(bot, chat_id, query.from_user.id)
            return

        if sub_action == "channels":
            context.user_data[_MERCHANT_CHANNEL_PICKER_SOURCE_KEY] = "channels"
            _set_merchant_publication_mode(context, "regular")
            allowed_channel_records = regular_channel_records
            selected = _get_selected_merchant_channels(context, allowed_channel_records)
            await _send_merchant_channels_picker_screen(
                bot,
                chat_id,
                allowed_channel_records,
                selected,
                publication_mode="regular",
            )
            return

        if sub_action == "status":
            hourly_label = "פעיל" if is_hourly else "לא פעיל"
            multi_label = "פעיל" if capability_flags.get("user.publish.multi") else "לא פעיל"
            limit_label = str(_merchant_open_publication_limit(query.from_user.id, capability_flags))
            capability_lines = [
                f"✅ {label}"
                for key, label in MERCHANT_CAPABILITY_LABELS.items()
                if capability_flags.get(key)
            ]
            if not capability_lines:
                capability_lines = ["אין הרשאות פעילות כרגע."]
            required_lines = []
            for item in required_statuses:
                mark = "✅" if item["status"] == "joined" else ("❌" if item["status"] == "missing" else "⚠️")
                required_lines.append(f"{mark} {item['channel']['display_name']}")
            await bot.send_message(
                chat_id,
                (
                    "🛡️ <b>ההרשאות והמצב שלך</b>\n\n"
                    f"⏱️ פרסום שעתי: <b>{hourly_label}</b>\n"
                    f"🧩 פרסומים מרובים: <b>{multi_label}</b>\n"
                    f"🧮 מכסת פרסומים פתוחים: <b>{limit_label}</b>\n"
                    f"📡 ערוצי פרסום רגיל: <b>{regular_channels_count}</b>\n"
                    f"🧩 ערוצי פרסום מרובה: <b>{multi_channels_count}</b>\n"
                    f"🔐 ערוצי חובה: <b>{len(required_statuses)}</b>\n\n"
                    + "\n".join(capability_lines)
                    + ("\n\n🔐 <b>בדיקת הצטרפות</b>\n" + "\n".join(required_lines) if required_lines else "")
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                ]),
            )
            return

        if sub_action in {"start", "startcompose"}:
            if missing_required:
                await _send_required_channels_gate(bot, chat_id, required_statuses)
                return
            if not can_start_publication:
                await bot.send_message(
                    chat_id,
                    "⛔ אין לך עדיין הרשאות מלאות להתחלת פרסום.\nנדרשות לפחות הרשאת יצירת פרסום והרשאת מדיה.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                    ]),
                )
                return
            if not channels:
                await bot.send_message(
                    chat_id,
                    "⛔ אין לך ערוצים משויכים עדיין. מנהל צריך לשייך לך ערוץ קודם.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                    ]),
                )
                return
            selected = _get_selected_merchant_channels(context, allowed_channel_records)
            picker_source = "startcompose" if sub_action == "startcompose" else "start"
            context.user_data[_MERCHANT_CHANNEL_PICKER_SOURCE_KEY] = picker_source
            back_callback_data = "pub:user:merchant:compose" if picker_source == "startcompose" else "pub:user:merchant"
            await _send_merchant_start_screen(
                bot,
                chat_id,
                allowed_channel_records,
                selected,
                capability_flags,
                publication_mode=current_mode,
                back_callback_data=back_callback_data,
            )
            return

        if sub_action == "pickch" and len(parts) > 4:
            if missing_required:
                await _send_required_channels_gate(bot, chat_id, required_statuses)
                return
            channel_key = str(parts[4] or "")
            allowed_keys = {str(ch.get("channel_key") or "") for ch in allowed_channel_records}
            allowed_keys.discard("")
            selected = _get_selected_merchant_channels(context, allowed_channel_records)
            if channel_key in allowed_keys:
                if channel_key in selected:
                    selected.remove(channel_key)
                else:
                    selected.add(channel_key)
                context.user_data[_MERCHANT_SELECTED_CHANNELS_KEY] = sorted(selected)
            if context.user_data.get(_MERCHANT_CHANNEL_PICKER_SOURCE_KEY) == "channels":
                await _send_merchant_channels_picker_screen(
                    bot,
                    chat_id,
                    allowed_channel_records,
                    selected,
                    publication_mode=current_mode,
                    back_callback_data="pub:user:merchant",
                )
            else:
                picker_source = str(context.user_data.get(_MERCHANT_CHANNEL_PICKER_SOURCE_KEY) or "start")
                back_callback_data = "pub:user:merchant:compose" if picker_source == "startcompose" else "pub:user:merchant"
                await _send_merchant_start_screen(
                    bot,
                    chat_id,
                    allowed_channel_records,
                    selected,
                    capability_flags,
                    publication_mode=current_mode,
                    back_callback_data=back_callback_data,
                )
            return

        if sub_action == "startconfirm":
            selected = _get_selected_merchant_channels(context, allowed_channel_records)
            if not selected:
                await bot.send_message(
                    chat_id,
                    "⚠️ צריך לבחור לפחות ערוץ אחד לפרסום.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ חזרה לבחירת ערוצים", callback_data="pub:user:merchant:start")],
                    ]),
                )
                return
            _get_merchant_draft(context, selected)
            await _send_merchant_compose_screen(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                publication_mode=current_mode,
            )
            return

        if sub_action == "settext":
            context.user_data[_MERCHANT_STATE_KEY] = _AWAIT_MERCHANT_TEXT
            await bot.send_message(
                chat_id,
                "📝 שלח עכשיו את הטקסט לפרסום.",
                reply_markup=_kb_merchant_cancel_input(),
            )
            return

        if sub_action == "setmedia":
            if not _has_any_media_permission(capability_flags):
                await bot.send_message(chat_id, "⛔ אין לך הרשאת העלאת מדיה.")
                return
            context.user_data[_MERCHANT_STATE_KEY] = _AWAIT_MERCHANT_MEDIA
            await bot.send_message(
                chat_id,
                "🖼️ שלח עכשיו תמונה / וידאו / אנימציה / מסמך / אודיו לפרסום.",
                reply_markup=_kb_merchant_cancel_input(),
            )
            return

        if sub_action == "preview":
            await _send_merchant_publication_preview(bot, chat_id, context, query.from_user.id)
            return

        if sub_action == "sendnow":
            await _run_merchant_publication_send(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                recurring_hourly=False,
            )
            return

        if sub_action == "sendhourly":
            if not merchant_has_hourly_publish(query.from_user.id):
                await bot.send_message(chat_id, "⛔ לא הופעלה עבורך אפשרות פרסום שעתי על ידי מנהל.")
                return
            await _run_merchant_publication_send(
                bot,
                chat_id,
                context,
                query.from_user.id,
                allowed_channel_records,
                capability_flags,
                recurring_hourly=True,
            )
            return

        if sub_action == "schedule":
            if missing_required:
                await _send_required_channels_gate(bot, chat_id, required_statuses)
                return
            if not capability_flags.get("user.merchant.schedule"):
                await bot.send_message(
                    chat_id,
                    "⛔ אין לך הרשאת תזמון פרסום בפאנל הסוחר.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                    ]),
                )
                return
            schedule_rows: list[list[InlineKeyboardButton]] = []
            if capability_flags.get("user.merchant.start"):
                schedule_rows.append([InlineKeyboardButton("🧾 פתח יצירת פרסום", callback_data="pub:user:merchant:compose")])
            if capability_flags.get("user.merchant.publications"):
                schedule_rows.append([InlineKeyboardButton("🗂️ הפרסומים שלי", callback_data="pub:user:merchant:mypubs")])
            schedule_rows.append([InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")])
            await bot.send_message(
                chat_id,
                (
                    "⏱️ <b>תזמון פרסום</b>\n\n"
                    "כאן אפשר לבדוק אם הפרסום השעתי פעיל ומה צריך לעשות כדי להפעיל או לעצור אותו.\n\n"
                    f"הרשאת תזמון: <b>פעילה</b>\n"
                    f"מצב כל שעה: <b>{'פעיל' if is_hourly else 'כבוי'}</b>\n\n"
                    "כדי להפעיל פרסום כל שעה, היכנס למסך יצירת הפרסום ולחץ 'הפעל אוטומטי כל שעה'.\n"
                    "כדי לעצור טיימר פעיל: הפרסומים שלי -> פתח פרסום -> עצור שעתי."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(schedule_rows),
            )
            return

        if sub_action == "reviews":
            if not capability_flags.get("user.review.write"):
                await bot.send_message(
                    chat_id,
                    "⛔ אין לך הרשאת חוות דעת כרגע.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                    ]),
                )
                return
            reviews = list_merchant_reviews(query.from_user.id, limit=10)
            count = count_merchant_reviews(query.from_user.id)
            lines = [f"• {str(item.get('review_text') or '').strip()}" for item in reviews] or ["אין עדיין חוות דעת."]
            await bot.send_message(
                chat_id,
                (
                    "⭐ <b>חוות הדעת שלי</b>\n\n"
                    f"סה\"כ חוות דעת: <b>{count}</b>\n\n"
                    + "\n".join(lines)
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ חזרה לאזור סוחר", callback_data="pub:user:merchant")],
                ]),
            )
            return

        hourly_label = "כן" if is_hourly else "לא"
        merchant_profile = get_merchant_profile(query.from_user.id)
        merchant_name = str((merchant_profile or {}).get("display_name") or query.from_user.full_name or query.from_user.username or "סוחר").strip()
        channels_preview = "\n".join(f"• {c}" for c in channels[:5]) if channels else "אין ערוצים מורשים"
        if len(channels) > 5:
            channels_preview += f"\n... ועוד {len(channels) - 5}"

        menu_rows = []
        if capability_flags.get("user.merchant.start") and can_start_publication and not missing_required:
            menu_rows.append([InlineKeyboardButton("▶️ התחל פרסום", callback_data="pub:user:merchant:start")])
            if capability_flags.get("user.publish.multi"):
                menu_rows.append([InlineKeyboardButton("🧩 פרסום נוסף (מרובה)", callback_data="pub:user:merchant:newpub")])
        if capability_flags.get("user.merchant.schedule") and not missing_required:
            menu_rows.append([InlineKeyboardButton("⏱️ תזמון פרסום", callback_data="pub:user:merchant:schedule")])
        if capability_flags.get("user.review.write"):
            menu_rows.append([InlineKeyboardButton("⭐ חוות דעת", callback_data="pub:user:merchant:reviews")])
        if capability_flags.get("user.merchant.required"):
            menu_rows.append([InlineKeyboardButton("🔐 חובת הצטרפות", callback_data="pub:user:merchant:required")])
        if capability_flags.get("user.merchant.channels"):
            menu_rows.append([InlineKeyboardButton("📡 הערוצים שלי", callback_data="pub:user:merchant:channels")])
        if capability_flags.get("user.merchant.publications"):
            menu_rows.append([InlineKeyboardButton("🗂️ הפרסומים שלי", callback_data="pub:user:merchant:mypubs")])
        if capability_flags.get("user.merchant.status"):
            menu_rows.append([InlineKeyboardButton("🛡️ סטטוס הרשאות", callback_data="pub:user:merchant:status")])
        menu_rows.append([InlineKeyboardButton("⬅️ חזרה לבית", callback_data="pub:user:home")])

        prefix = ""
        if missing_required:
            prefix = (
                "🔐 <b>לפני תחילת פרסום יש להשלים הצטרפות לערוצי החובה.</b>\n"
                "הצטרף לערוצים ואז לחץ בדוק שוב.\n\n"
            )
            menu_rows = _build_required_join_buttons(not_joined_required) + [
                [InlineKeyboardButton("🔄 בדוק שוב", callback_data="pub:user:merchant")],
                [InlineKeyboardButton("🔁 הפעל מחדש", callback_data="RESTART_BOT_PENDING")],
            ] + menu_rows
        elif unknown_required:
            prefix = (
                "ℹ️ <b>יש ערוצי חובה פרטיים שלא אומתו אוטומטית.</b>\n"
                "זה לא חוסם כרגע פרסום, אבל כדי אימות מלא בזמן אמת צריך להגדיר לערוצים מזהה בדיקה: -100... או @username.\n\n"
            )
        elif not channels:
            prefix = (
                "📡 <b>אין לך עדיין ערוצי פרסום מורשים.</b>\n"
                "פנה למנהל כדי לשייך לך לפחות ערוץ פרסום אחד.\n\n"
            )
        await bot.send_message(
            chat_id,
            (
                "💼 <b>אזור סוחר</b>\n\n"
                f"שלום <b>{merchant_name}</b>\n"
                "כאן אפשר לנהל פרסומים, ערוצים ותזמון.\n\n"
                f"{prefix}"
                f"⏱️ פרסום שעתי: <b>{hourly_label}</b>\n"
                f"🧩 פרסומים מרובים: <b>{'פעיל' if capability_flags.get('user.publish.multi') else 'לא פעיל'}</b>\n"
                f"🧮 מכסה פתוחה: <b>{_merchant_open_publication_limit(query.from_user.id, capability_flags)}</b>\n"
                f"📡 ערוצי פרסום רגיל: <b>{regular_channels_count}</b>\n"
                f"🧩 ערוצי פרסום מרובה: <b>{multi_channels_count}</b>\n"
                f"📍 מצב עריכה נוכחי: <b>{'פרסום מרובה' if current_mode == 'multi' else 'פרסום רגיל'}</b>\n\n"
                f"{channels_preview}"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(menu_rows),
        )

    elif action == "contact":
        context.user_data.pop(_SUPPORT_CHAT_SUPPRESSED_KEY, None)
        context.user_data[_CONTACT_STATE_KEY] = "awaiting_contact_category"
        context.user_data.pop(_CONTACT_CATEGORY_KEY, None)
        subscriber = register_or_touch_subscriber(query.from_user)
        subscriber_id = int(subscriber["id"])
        open_chat = get_open_subscriber_chat(subscriber_id)
        subscriber_chat_id = 0

        if open_chat:
            subscriber_chat_id = int(open_chat["id"])
            has_open_contact_request = False
            try:
                messages = get_subscriber_chat_history(subscriber_chat_id)
                has_open_contact_request = _has_pending_contact_request(messages)
            except Exception:
                has_open_contact_request = False

            if has_open_contact_request:
                context.user_data.pop(_CONTACT_STATE_KEY, None)
                await bot.send_message(
                    query.message.chat_id,
                    "⏳ הבקשה שלך כבר בטיפול.\nאנא המתן למענה מהמנהל.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 הפעל בוט מחדש", callback_data="RESTART_BOT_PENDING")],
                    ]),
                )
                return
        else:
            subscriber_chat_id = int(open_subscriber_chat(subscriber_id, ADMIN_ID))

        context.user_data[_CONTACT_SUBSCRIBER_ID_KEY] = subscriber_id
        context.user_data[_CONTACT_CHAT_ID_KEY] = subscriber_chat_id

        try:
            await _notify_admin_contact_open(bot, query.from_user, subscriber_id, subscriber_chat_id)
        except Exception:
            pass

        await bot.send_message(
            query.message.chat_id,
            "📞 <b>צור קשר</b>\n\nבחר סוג פנייה:",
            reply_markup=_contact_categories_keyboard(),
            parse_mode="HTML",
        )

    elif action == "contactcat" and len(parts) > 3:
        context.user_data.pop(_SUPPORT_CHAT_SUPPRESSED_KEY, None)
        category_key = parts[3]
        category_label = _CONTACT_CATEGORIES.get(category_key)
        if not category_label:
            await bot.send_message(chat_id, "⚠️ סוג פנייה לא תקין. נסה שוב.")
            return

        context.user_data[_CONTACT_STATE_KEY] = "awaiting_contact_text"
        context.user_data[_CONTACT_CATEGORY_KEY] = category_key

        await bot.send_message(
            chat_id,
            (
                f"{category_label}\n\n"
                "✍️ נא לכתוב עכשיו את תוכן הפנייה שלך בהודעה אחת."
            ),
        )

    elif action == "msg" and len(parts) > 3:
        btn = pub_get_button_by_id(int(parts[3]))
        if btn and btn["value"]:
            btype   = btn["button_type"]
            val     = btn["value"]
            back_kb = _back_keyboard(btn)
            if btype == "text":
                await bot.send_message(chat_id, val, parse_mode="HTML", reply_markup=back_kb)
            elif btype == "phone":
                await bot.send_message(chat_id, f"📞 {val}", reply_markup=back_kb)
            elif btype == "email":
                await bot.send_message(chat_id, f"📧 {val}", reply_markup=back_kb)

    elif action == "loc" and len(parts) > 3:
        btn = pub_get_button_by_id(int(parts[3]))
        if btn and btn["value"]:
            back_kb = _back_keyboard(btn)
            try:
                lat_s, lon_s = btn["value"].split(",")
                await bot.send_location(
                    chat_id,
                    latitude=float(lat_s.strip()),
                    longitude=float(lon_s.strip()),
                    reply_markup=back_kb,
                )
            except (ValueError, TelegramError) as exc:
                logger.error("handle_user_nav loc failed for btn %s: %s", parts[3], exc)