from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from database.database import get_connection
from repositories.subscriber_publications_repository import (
    count_publications,
    create_publication,
    delete_publication,
    get_all_publications,
    get_publication_by_id,
    get_publication_buttons,
    get_publication_stats_summary,
    increment_publication_delivery,
    list_publications_page,
    record_publication_stat,
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
    next_run_at: str | None = None,
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
        next_run_at=next_run_at,
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


def publication_stats(publication_id: int) -> dict:
    return get_publication_stats_summary(publication_id)


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


def _build_publication_keyboard(publication_id: int) -> InlineKeyboardMarkup | None:
    buttons = get_publication_buttons(publication_id)
    if not buttons:
        return None
    rows = [[InlineKeyboardButton(str(b.get("title") or "קישור"), url=str(b.get("url") or ""))] for b in buttons if b.get("url")]
    return InlineKeyboardMarkup(rows) if rows else None


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
    for subscriber_id, tg_id in recipients:
        try:
            if media_type and file_id:
                if media_type == "photo":
                    await bot.send_photo(chat_id=tg_id, photo=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "video":
                    await bot.send_video(chat_id=tg_id, video=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "animation":
                    await bot.send_animation(chat_id=tg_id, animation=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "document":
                    await bot.send_document(chat_id=tg_id, document=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "audio":
                    await bot.send_audio(chat_id=tg_id, audio=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "voice":
                    await bot.send_voice(chat_id=tg_id, voice=file_id, caption=content or None, reply_markup=keyboard)
                elif media_type == "video_note":
                    await bot.send_video_note(chat_id=tg_id, video_note=file_id)
                    if content or keyboard:
                        await bot.send_message(chat_id=tg_id, text=content or "", reply_markup=keyboard)
                elif media_type == "sticker":
                    await bot.send_sticker(chat_id=tg_id, sticker=file_id)
                    if content or keyboard:
                        await bot.send_message(chat_id=tg_id, text=content or "", reply_markup=keyboard)
                else:
                    await bot.send_message(chat_id=tg_id, text=content or "")
            else:
                await bot.send_message(chat_id=tg_id, text=content or "", reply_markup=keyboard)

            sent += 1
            record_publication_stat(publication_id, subscriber_id, "sent")
        except Exception:
            failed += 1
            record_publication_stat(publication_id, subscriber_id, "failed")

    increment_publication_delivery(publication_id, sent, failed, len(recipients))

    is_recurring = int(pub.get("is_recurring") or 0) == 1
    if is_recurring:
        interval = int(pub.get("repeat_every_minutes") or 0)
        next_run_at = None
        if interval > 0:
            next_run_at = (datetime.utcnow() + timedelta(minutes=interval)).strftime("%Y-%m-%d %H:%M:%S")
        update_publication(publication_id, status="active", next_run_at=next_run_at)
    else:
        update_publication(publication_id, status="sent", next_run_at=None)

    return {
        "ok": True,
        "sent": sent,
        "failed": failed,
        "total": len(recipients),
    }
