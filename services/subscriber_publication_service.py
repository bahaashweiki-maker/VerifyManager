from __future__ import annotations

import base64
from datetime import datetime, timedelta
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.database import get_connection, now_il
from repositories.subscriber_publications_repository import (
        get_publication_delivery_by_id,
    create_publication_delivery,
    count_publications,
    create_publication,
    delete_publication,
    get_all_publications,
    get_publication_by_id,
    get_publication_buttons,
    get_publication_stats_summary,
    increment_publication_delivery,
    list_due_publication_deletions,
    list_pending_publication_deletions,
    list_pending_publication_deliveries,
    list_publications_page,
    mark_publication_delivery_status,
    record_publication_stat,
    reset_publication_stats_baseline,
    replace_publication_buttons,
    update_publication,
)


def list_publications(limit: int = 50) -> list:
    return get_all_publications(limit=limit)


def list_publications_paged(page: int, per_page: int = 10, search: str = "", status: str | None = None) -> tuple[list, int]:
    rows = list_publications_page(page=page, per_page=per_page, search=search, status=status)
    total = count_publications(search=search, status=status)
    return rows, total


def create_publication_record(
    *,
    title: str | None,
    content_text: str | None,
    media_type: str | None,
    file_id: str | None,
    target_type: str,
    target_value: str | None,
    status: str,
    created_by: int | None,
    scheduled_at: str | None = None,
    is_recurring: int = 0,
    repeat_every_minutes: int | None = None,
    recurrence_type: str | None = None,
    recurrence_weekdays: str | None = None,
    recurrence_day_of_month: int | None = None,
    recurrence_time: str | None = None,
    next_run_at: str | None = None,
    auto_delete_minutes: int | None = None,
    buttons: list[dict] | None = None,
) -> int:
    pub_id = create_publication(
        title=title,
        content_text=content_text,
        media_type=media_type,
        file_id=file_id,
        target_type=target_type,
        target_value=target_value,
        status=status,
        created_by=created_by,
        scheduled_at=scheduled_at,
        is_recurring=is_recurring,
        repeat_every_minutes=repeat_every_minutes,
        recurrence_type=recurrence_type,
        recurrence_weekdays=recurrence_weekdays,
        recurrence_day_of_month=recurrence_day_of_month,
        recurrence_time=recurrence_time,
        next_run_at=next_run_at,
        auto_delete_minutes=auto_delete_minutes,
    )
    if pub_id > 0 and buttons is not None:
        replace_publication_buttons(pub_id, buttons)
    return pub_id


def get_publication(publication_id: int) -> Optional[dict]:
    return get_publication_by_id(publication_id)


def update_publication_record(publication_id: int, **fields) -> bool:
    return update_publication(publication_id, **fields)


def remove_publication(publication_id: int) -> bool:
    return delete_publication(publication_id)


def list_publication_buttons(publication_id: int) -> list:
    return get_publication_buttons(publication_id)


def replace_publication_buttons_record(publication_id: int, buttons: list[dict]) -> None:
    replace_publication_buttons(publication_id, buttons)


def publication_stats(publication_id: int) -> dict:
    return get_publication_stats_summary(publication_id)


def reset_publication_stats(publication_id: int) -> bool:
    return reset_publication_stats_baseline(publication_id)


def create_publication_delivery_record(
    *,
    publication_id: int,
    subscriber_id: int | None,
    telegram_id: int,
    message_id: int,
    delete_at: str | None,
) -> int:
    return create_publication_delivery(
        publication_id=publication_id,
        subscriber_id=subscriber_id,
        telegram_id=telegram_id,
        message_id=message_id,
        delete_at=delete_at,
    )


def list_pending_delivery_records(publication_id: int) -> list:
    return list_pending_publication_deliveries(publication_id)


def list_due_deletion_records(now_iso: str) -> list:
    return list_due_publication_deletions(now_iso)


def list_pending_deletion_records() -> list:
    return list_pending_publication_deletions()


def mark_delivery_status(delivery_id: int, status: str) -> bool:
    return mark_publication_delivery_status(delivery_id, status)


def get_delivery_record(delivery_id: int) -> Optional[dict]:
    return get_publication_delivery_by_id(delivery_id)


def _parse_time_hhmm(raw: str | None) -> tuple[int, int] | None:
    text = (raw or "").strip()
    if not text or ":" not in text:
        return None
    parts = text.split(":", 1)
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except Exception:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _next_monthly(after_dt: datetime, day_of_month: int, hour: int, minute: int) -> datetime:
    year = after_dt.year
    month = after_dt.month
    for _ in range(24):
        month += 1
        if month > 12:
            month = 1
            year += 1
        for day in range(31, 27, -1):
            try:
                _ = datetime(year, month, day, hour, minute)
                max_day = day
                break
            except Exception:
                continue
        chosen_day = min(max(1, day_of_month), max_day)
        candidate = datetime(year, month, chosen_day, hour, minute)
        if candidate > after_dt:
            return candidate
    return after_dt + timedelta(days=30)


def compute_next_run(publication: dict, from_time: datetime | None = None) -> str | None:
    now = from_time or datetime.utcnow()
    recurrence_type = str(publication.get("recurrence_type") or "").strip().lower()
    interval = int(publication.get("repeat_every_minutes") or 0)

    base_anchor = now
    raw_anchor = str(publication.get("next_run_at") or "").strip()
    if raw_anchor:
        try:
            base_anchor = datetime.strptime(raw_anchor, "%Y-%m-%d %H:%M:%S")
        except Exception:
            base_anchor = now

    if recurrence_type in {"", "interval"}:
        if interval <= 0:
            return None
        candidate = base_anchor + timedelta(minutes=interval)
        while candidate <= now:
            candidate += timedelta(minutes=interval)
        return candidate.strftime("%Y-%m-%d %H:%M:%S")

    if recurrence_type == "daily":
        hhmm = _parse_time_hhmm(publication.get("recurrence_time"))
        if not hhmm:
            return None
        hour, minute = hhmm
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.strftime("%Y-%m-%d %H:%M:%S")

    if recurrence_type == "weekly":
        hhmm = _parse_time_hhmm(publication.get("recurrence_time"))
        if not hhmm:
            return None
        hour, minute = hhmm
        raw_days = str(publication.get("recurrence_weekdays") or "").strip()
        days = []
        for token in raw_days.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                day = int(token)
            except Exception:
                continue
            if 0 <= day <= 6:
                days.append(day)
        if not days:
            days = [now.weekday()]

        candidates = []
        for d in sorted(set(days)):
            delta = (d - now.weekday()) % 7
            dt = (now + timedelta(days=delta)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=7)
            candidates.append(dt)
        return min(candidates).strftime("%Y-%m-%d %H:%M:%S") if candidates else None

    if recurrence_type == "monthly":
        hhmm = _parse_time_hhmm(publication.get("recurrence_time"))
        if not hhmm:
            return None
        day_of_month = int(publication.get("recurrence_day_of_month") or 1)
        hour, minute = hhmm
        candidate = _next_monthly(now, day_of_month, hour, minute)
        return candidate.strftime("%Y-%m-%d %H:%M:%S")

    return None


def count_publication_recipients(target_type: str, target_value: str | None) -> int:
    return len(_resolve_recipients(target_type, target_value))


def list_available_publication_permissions(limit: int = 200) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT up.permission
            FROM user_permissions up
            JOIN subscribers s ON s.telegram_id = up.telegram_id
            ORDER BY up.permission ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [str(r[0]) for r in rows if r and r[0]]


def _resolve_recipients(target_type: str, target_value: str | None) -> list[tuple[int, int]]:
    with get_connection() as conn:
        if target_type == "all":
            rows = conn.execute("SELECT id, telegram_id FROM subscribers").fetchall()
        elif target_type == "active":
            rows = conn.execute("SELECT id, telegram_id FROM subscribers WHERE status = 'active'").fetchall()
        elif target_type == "suspended":
            rows = conn.execute("SELECT id, telegram_id FROM subscribers WHERE status = 'suspended'").fetchall()
        elif target_type == "verified":
            rows = conn.execute(
                """
                SELECT DISTINCT s.id, s.telegram_id
                FROM subscribers s
                JOIN (
                    SELECT telegram_id, MAX(id) AS last_id
                    FROM verifications
                    GROUP BY telegram_id
                ) lv ON lv.telegram_id = s.telegram_id
                JOIN verifications v ON v.id = lv.last_id
                WHERE v.status = 'approved'
                """
            ).fetchall()
        elif target_type == "catalog" and target_value:
            permission = f"catalog.{target_value.strip()}"
            rows = conn.execute(
                """
                SELECT DISTINCT s.id, s.telegram_id
                FROM subscribers s
                JOIN user_permissions up ON up.telegram_id = s.telegram_id
                WHERE up.permission = ?
                """,
                (permission,),
            ).fetchall()
        elif target_type == "permission" and target_value:
            rows = conn.execute(
                """
                SELECT DISTINCT s.id, s.telegram_id
                FROM subscribers s
                JOIN user_permissions up ON up.telegram_id = s.telegram_id
                WHERE up.permission = ?
                """,
                (target_value.strip(),),
            ).fetchall()
        else:
            rows = []
    return [
        (int(r[0]), int(r[1]))
        for r in rows
        if r and r[0] is not None and r[1] is not None
    ]


def encode_publication_note(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "note:b64:"
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return f"note:b64:{encoded}"


def decode_publication_note(value: str | None) -> str | None:
    raw = (value or "").strip()
    prefix = "note:b64:"
    if not raw.startswith(prefix):
        return None
    payload = raw[len(prefix):]
    if not payload:
        return ""
    try:
        return base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def _build_publication_keyboard(publication_id: int) -> InlineKeyboardMarkup | None:
    buttons = get_publication_buttons(publication_id)
    if not buttons:
        return None
    rows_by_row_index: dict[int, list[InlineKeyboardButton]] = {}
    row_order: list[int] = []
    for idx, b in enumerate(buttons, start=1):
        title = str(b.get("title") or "כפתור")
        value = str(b.get("url") or "").strip()
        row_idx_raw = b.get("row_index")
        try:
            row_idx = int(row_idx_raw) if row_idx_raw is not None else idx
        except Exception:
            row_idx = idx
        if row_idx not in rows_by_row_index:
            rows_by_row_index[row_idx] = []
            row_order.append(row_idx)
        note_text = decode_publication_note(value)
        if note_text is not None:
            rows_by_row_index[row_idx].append(InlineKeyboardButton(title, callback_data=f"SUBS_PUB_NOTE_{publication_id}_{idx}"))
            continue
        if value:
            rows_by_row_index[row_idx].append(InlineKeyboardButton(title, url=value))
    rows = [rows_by_row_index[r] for r in row_order if rows_by_row_index.get(r)]
    return InlineKeyboardMarkup(rows) if rows else None


async def handle_publication_note_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    if data == "SUBS_PUB_NOTE_BACK":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        return True

    if data.startswith("SUBS_PUB_NOTE_BACK_"):
        try:
            publication_id = int(data[len("SUBS_PUB_NOTE_BACK_"):])
        except Exception:
            await query.answer("כפתור לא תקין", show_alert=True)
            return True

        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        try:
            await _send_publication_to_chat(context.bot, publication_id, query.message.chat_id)
        except Exception:
            pass
        return True

    if not data.startswith("SUBS_PUB_NOTE_"):
        return False

    payload = data[len("SUBS_PUB_NOTE_"):]
    parts = payload.split("_", 1)
    if len(parts) != 2:
        await query.answer("כפתור לא תקין", show_alert=True)
        return True

    try:
        publication_id = int(parts[0])
        button_index = int(parts[1])
    except Exception:
        await query.answer("כפתור לא תקין", show_alert=True)
        return True

    buttons = get_publication_buttons(publication_id)
    if not (1 <= button_index <= len(buttons)):
        await query.answer("הערה לא נמצאה", show_alert=True)
        return True

    button = buttons[button_index - 1]
    note_text = decode_publication_note(button.get("url"))
    if note_text is None:
        await query.answer("זהו כפתור קישור", show_alert=True)
        return True

    subscriber_id = None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM subscribers WHERE telegram_id = ? LIMIT 1",
                (int(query.message.chat_id),),
            ).fetchone()
            if row:
                subscriber_id = int(row[0])
    except Exception:
        subscriber_id = None

    try:
        record_publication_stat(publication_id, subscriber_id, "button_click")
    except Exception:
        pass

    await query.answer()
    back_cb = f"SUBS_PUB_NOTE_BACK_{publication_id}"
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזור", callback_data=back_cb)],
    ])
    try:
        await query.message.edit_text(
            text=note_text or "(ללא תוכן)",
            reply_markup=reply_markup,
        )
    except Exception:
        try:
            await query.message.edit_caption(
                caption=note_text or "(ללא תוכן)",
                reply_markup=reply_markup,
            )
        except Exception:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=note_text or "(ללא תוכן)",
                reply_markup=reply_markup,
            )
    return True


async def _send_publication_to_chat(bot: Bot, publication_id: int, chat_id: int):
    pub = get_publication_by_id(publication_id)
    if not pub:
        return None

    keyboard = _build_publication_keyboard(publication_id)
    media_type = (pub.get("media_type") or "").strip()
    file_id = (pub.get("file_id") or "").strip()
    content = (pub.get("content_text") or "").strip()

    if media_type and file_id:
        if media_type == "photo":
            return await bot.send_photo(chat_id=chat_id, photo=file_id, caption=content or None, reply_markup=keyboard)
        if media_type == "video":
            return await bot.send_video(chat_id=chat_id, video=file_id, caption=content or None, reply_markup=keyboard)
        if media_type == "animation":
            return await bot.send_animation(chat_id=chat_id, animation=file_id, caption=content or None, reply_markup=keyboard)
        if media_type == "document":
            return await bot.send_document(chat_id=chat_id, document=file_id, caption=content or None, reply_markup=keyboard)
        if media_type == "audio":
            return await bot.send_audio(chat_id=chat_id, audio=file_id, caption=content or None, reply_markup=keyboard)
        if media_type == "voice":
            return await bot.send_voice(chat_id=chat_id, voice=file_id, caption=content or None, reply_markup=keyboard)
        if media_type == "video_note":
            sent_message = await bot.send_video_note(chat_id=chat_id, video_note=file_id)
            if content or keyboard:
                return await bot.send_message(chat_id=chat_id, text=content or "", reply_markup=keyboard)
            return sent_message
        if media_type == "sticker":
            sent_message = await bot.send_sticker(chat_id=chat_id, sticker=file_id)
            if content or keyboard:
                return await bot.send_message(chat_id=chat_id, text=content or "", reply_markup=keyboard)
            return sent_message

    return await bot.send_message(chat_id=chat_id, text=content or "", reply_markup=keyboard)


async def dispatch_publication(bot: Bot, publication_id: int) -> dict:
    pub = get_publication_by_id(publication_id)
    if not pub:
        return {"ok": False, "reason": "not_found", "sent": 0, "failed": 0, "total": 0}

    recipients = _resolve_recipients(pub.get("target_type") or "all", pub.get("target_value"))
    keyboard = _build_publication_keyboard(publication_id)
    media_type = (pub.get("media_type") or "").strip()
    file_id = (pub.get("file_id") or "").strip()
    content = (pub.get("content_text") or "").strip()

    sent = 0
    failed = 0
    deliveries: list[dict] = []
    for subscriber_id, tg_id in recipients:
        try:
            sent_message = None
            if media_type and file_id:
                if media_type == "photo":
                    sent_message = await bot.send_photo(chat_id=tg_id, photo=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "video":
                    sent_message = await bot.send_video(chat_id=tg_id, video=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "animation":
                    sent_message = await bot.send_animation(chat_id=tg_id, animation=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "document":
                    sent_message = await bot.send_document(chat_id=tg_id, document=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "audio":
                    sent_message = await bot.send_audio(chat_id=tg_id, audio=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "voice":
                    sent_message = await bot.send_voice(chat_id=tg_id, voice=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "video_note":
                    sent_message = await bot.send_video_note(chat_id=tg_id, video_note=file_id)
                    if content or keyboard:
                        sent_message = await bot.send_message(chat_id=tg_id, text=content or "", reply_markup=keyboard)
                elif media_type == "sticker":
                    sent_message = await bot.send_sticker(chat_id=tg_id, sticker=file_id)
                    if content or keyboard:
                        sent_message = await bot.send_message(chat_id=tg_id, text=content or "", reply_markup=keyboard)
                else:
                    sent_message = await bot.send_message(chat_id=tg_id, text=content or "")
            else:
                sent_message = await bot.send_message(chat_id=tg_id, text=content or "", reply_markup=keyboard)

            sent += 1
            record_publication_stat(publication_id, subscriber_id, "sent")
            if sent_message and getattr(sent_message, "message_id", None):
                deliveries.append(
                    {
                        "subscriber_id": subscriber_id,
                        "telegram_id": tg_id,
                        "message_id": int(sent_message.message_id),
                    }
                )
        except Exception:
            failed += 1
            record_publication_stat(publication_id, subscriber_id, "failed")

    increment_publication_delivery(publication_id, sent, failed, len(recipients))

    is_recurring = int(pub.get("is_recurring") or 0) == 1
    if is_recurring:
        next_run_at = compute_next_run(pub, from_time=now_il().replace(tzinfo=None))
        update_publication(publication_id, status="active", next_run_at=next_run_at)
    else:
        update_publication(publication_id, status="sent", next_run_at=None)

    return {
        "ok": True,
        "sent": sent,
        "failed": failed,
        "total": len(recipients),
        "deliveries": deliveries,
    }
