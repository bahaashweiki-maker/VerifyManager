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

_SYSTEM_BUTTONS: list[list[InlineKeyboardButton]] = [
    [InlineKeyboardButton("🪪 שלח אימות", callback_data="START_VERIFY")],
]

# כפתור עם עד _SHORT_LABEL_MAX תווים נחשב "קצר" ומוזווג עם קצר אחר.
# כפתור ארוך יותר מקבל שורה מלאה לעצמו.
# בדיקת אורך: len() על Python str — Hebrew / emoji = תו אחד כל אחד.
_SHORT_LABEL_MAX = 11


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


def _row_sort_key(btn) -> tuple:
    """מפתח מיון תואם sqlite3.Row — ללא שימוש ב-.get()."""
    row_index = btn["row_index"] or 0
    try:
        sort_order = btn["sort_order"]
        sort_order = sort_order if sort_order is not None else 0
    except IndexError:
        sort_order = 0
    return (row_index, sort_order)


# ---------------------------------------------------------------------------
# _build_keyboard — greedy packing
# ---------------------------------------------------------------------------

def _build_keyboard(
    buttons: list,
    include_system: bool = False,
) -> InlineKeyboardMarkup:
    """
    בונה InlineKeyboardMarkup בפריסה מקצועית — כמו בוטים מובילים בטלגרם.

    אלגוריתם greedy packing:
    ─────────────────────────────────────────────────────
    • כפתורים ממוינים לפי (row_index, sort_order) — כוונת ה-DB נשמרת.
    • סריקה ליניארית; בכל שלב:
        – כפתור קצר (label ≤ _SHORT_LABEL_MAX תווים):
            אם יש כפתור קצר ממתין → הם מוזווגים לשורה אחת.
            אחרת → הכפתור ממתין לשותף.
        – כפתור ארוך:
            אם יש ממתין → הוא נשלח תחילה לשורה משלו.
            הכפתור הארוך נשלח לשורה משלו.
    • לעולם לא יותר מ-2 כפתורים בשורה.
    • כפתורים כבויים (is_active=0) מושמטים.
    ─────────────────────────────────────────────────────
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
        rows.extend(_SYSTEM_BUTTONS)

    return InlineKeyboardMarkup(rows)


def _back_keyboard(btn) -> InlineKeyboardMarkup:
    """מקלדת עם כפתור ⬅️ חזור לעמוד המקור של כפתור התוכן."""
    page_id = btn["page_id"]
    back_cb = f"pub:user:page:{page_id}" if page_id else "pub:user:home"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזור", callback_data=back_cb)]
    ])


async def _delete_message(message) -> None:
    """מוחק הודעה קיימת לפני שליחת חדשה — מתועד בלוג אם נכשל."""
    try:
        await message.delete()
    except TelegramError as exc:
        logger.warning(
            "Could not delete message %d in chat %d: %s",
            message.message_id,
            message.chat_id,
            exc,
        )


# ---------------------------------------------------------------------------
# render_home
# ---------------------------------------------------------------------------

async def render_home(
    bot: Bot,
    chat_id: int,
) -> Optional[int]:
    """
    שולח את דף הבית למשתמש כהודעה חדשה.
    מחזיר את message_id של ההודעה שנשלחה, או None בכשל.
    """
    try:
        home  = get_home()
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
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return sent.message_id

    except TelegramError as exc:
        logger.error("render_home failed for chat_id=%d: %s", chat_id, exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# render_page
# ---------------------------------------------------------------------------

async def render_page(
    bot: Bot,
    chat_id: int,
    page_id: int,
) -> bool:
    """
    שולח עמוד פרסום למשתמש כהודעה חדשה.
    מחזיר True בהצלחה, False בכשל.
    """
    try:
        page = pub_get_page_by_id(page_id)
        if page is None or not page["is_active"]:
            return False

        sub_pages = [p for p in pub_get_pages_by_parent(page_id) if p["is_active"]]
        nav_rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton(
                f"{'📂' if sp['page_type'] == 'catalog' else '📄'} {sp['title']}",
                callback_data=f"pub:user:page:{sp['id']}",
            )]
            for sp in sub_pages
        ]

        buttons = pub_get_buttons_for_page(page_id)
        db_kb   = _build_keyboard(buttons, include_system=False)

        parent_id = page["parent_id"]
        back_cb   = f"pub:user:page:{parent_id}" if parent_id else "pub:user:home"
        all_rows  = (
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
            await bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML",
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
    """
    מטפל בכל callback_data שמתחיל ב-pub:user:.

    בכל מעבר: מוחק את ההודעה הקיימת (await) לפני שליחת החדשה.
    """
    query = update.callback_query
    await query.answer()

    parts   = query.data.split(":")
    action  = parts[2] if len(parts) > 2 else ""
    bot     = context.bot
    chat_id = query.message.chat_id

    await _delete_message(query.message)

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