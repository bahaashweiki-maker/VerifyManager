"""
app/engine/publishing_renderer.py

פונקציות render למשתמש — דף הבית ועמודים.

רישום ב-app/bot.py:
    from app.engine.publishing_renderer import handle_user_nav, render_home
    # ניתוב pub:user: מתבצע בתוך button_click — ראה bot.py
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from repositories.home_repository import get_home
from repositories.pub_page_repository import pub_get_page_by_id, pub_get_pages_by_parent
from repositories.pub_button_repository import (
    pub_get_buttons_for_home,
    pub_get_buttons_for_page,
    pub_get_button_by_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# מעקב הודעת בית — מניעת הצפה בעת לחיצות חוזרות על /start
# ---------------------------------------------------------------------------
_last_home_msg: dict[int, int] = {}


# ---------------------------------------------------------------------------
# כפתורי מערכת
# ---------------------------------------------------------------------------
_SYSTEM_BUTTONS: list[list[InlineKeyboardButton]] = [
    [InlineKeyboardButton("🪪 שלח אימות", callback_data="START_VERIFY")],
]


# ---------------------------------------------------------------------------
# המרת כפתור DB → InlineKeyboardButton
# ---------------------------------------------------------------------------

def _db_btn_to_tg(btn) -> Optional[InlineKeyboardButton]:
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
            target = btn["target_page_id"] or value
            return InlineKeyboardButton(label, callback_data=f"pub:user:page:{target}")
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
) -> InlineKeyboardMarkup:
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
        rows.extend(_SYSTEM_BUTTONS)
    return InlineKeyboardMarkup(rows)


def _back_keyboard(btn) -> InlineKeyboardMarkup:
    """מקלדת עם כפתור ⬅️ חזור לעמוד המקור של כפתור התוכן."""
    page_id = btn["page_id"]
    back_cb = f"pub:user:page:{page_id}" if page_id else "pub:user:home"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזור", callback_data=back_cb)]
    ])


# ---------------------------------------------------------------------------
# _send_media
# ---------------------------------------------------------------------------

async def _send_media(
    bot: Bot,
    chat_id: int,
    file_id: str,
    media_type: Optional[str],
    caption: str,
    keyboard: InlineKeyboardMarkup,
):
    kwargs = dict(
        chat_id=chat_id,
        caption=caption,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    if media_type == "animation":
        return await bot.send_animation(animation=file_id, **kwargs)
    elif media_type == "video":
        return await bot.send_video(video=file_id, **kwargs)
    else:
        return await bot.send_photo(photo=file_id, **kwargs)


# ---------------------------------------------------------------------------
# render_home
# ---------------------------------------------------------------------------

async def render_home(
    bot: Bot,
    chat_id: int,
) -> None:
    prev_msg_id = _last_home_msg.pop(chat_id, None)
    if prev_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
        except Exception:
            pass

    try:
        _raw  = get_home()
        home  = dict(_raw) if _raw is not None else None  # sqlite3.Row → dict
        text  = "👋 ברוך הבא!"
        image = None

        if home and home["is_active"]:
            text     = home["text"] or text
            image    = home["image_file_id"]
            buttons  = pub_get_buttons_for_home(1)
            keyboard = _build_keyboard(buttons, include_system=True)
        else:
            keyboard = InlineKeyboardMarkup(_SYSTEM_BUTTONS)

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
# render_page
# ---------------------------------------------------------------------------

async def render_page(
    bot: Bot,
    chat_id: int,
    page_id: int,
) -> bool:
    try:
        _raw = pub_get_page_by_id(page_id)
        if _raw is None or not _raw["is_active"]:
            return False
        page = dict(_raw)   # sqlite3.Row → dict (נדרש כדי לתמוך ב-.get())

        # כפתורי ניווט לעמודי-בן פעילים
        sub_pages = [p for p in pub_get_pages_by_parent(page_id) if p["is_active"]]
        nav_rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton(
                f"{'📂' if sp['page_type'] == 'catalog' else '📄'} {sp['title']}",
                callback_data=f"pub:user:page:{sp['id']}",
            )]
            for sp in sub_pages
        ]

        # כפתורי DB לעמוד
        buttons = pub_get_buttons_for_page(page_id)
        db_kb   = _build_keyboard(buttons, include_system=False)

        # כפתור חזרה
        back_cb = (
            f"pub:user:page:{page['parent_id']}"
            if page["parent_id"]
            else "pub:user:home"
        )
        all_rows = (
            nav_rows
            + list(db_kb.inline_keyboard)
            + [[InlineKeyboardButton("◀️ חזור", callback_data=back_cb)]]
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
# handle_user_nav
# ---------------------------------------------------------------------------

async def handle_user_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    parts   = query.data.split(":")
    action  = parts[2] if len(parts) > 2 else ""
    bot     = context.bot
    chat_id = query.message.chat_id

    try:
        await query.message.delete()
    except TelegramError:
        pass

    if action == "home":
        await render_home(bot, chat_id)

    elif action == "page" and len(parts) > 3:
        await render_page(bot, chat_id, int(parts[3]))

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