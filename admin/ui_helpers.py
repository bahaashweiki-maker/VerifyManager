"""
admin/ui_helpers.py
---------------------
רכיבי UI גנריים לשימוש בכל מודולי האדמין של הבוט.
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# כפתורים גנריים
# ---------------------------------------------------------------------------

def back_button(callback_data: str, label: str = "◀️ חזור") -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=callback_data)


def cancel_button(callback_data: str, label: str = "◀️ חזור") -> InlineKeyboardButton:
    """ביטול = חזרה — אותו מינוח בכל מקום."""
    return InlineKeyboardButton(label, callback_data=callback_data)


def delete_button(callback_data: str, label: str = "🗑 מחק") -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=callback_data)


def confirm_button(callback_data: str, label: str = "✅ כן, מחק") -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=callback_data)


# ---------------------------------------------------------------------------
# מקלדות גנריות
# ---------------------------------------------------------------------------

def kb_back(callback_data: str, label: str = "◀️ חזור") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[back_button(callback_data, label)]])


def kb_cancel(callback_data: str, label: str = "◀️ חזור") -> InlineKeyboardMarkup:
    """מקלדת חזרה בלבד — משמשת בכל מצבי 'ממתין לקלט'."""
    return InlineKeyboardMarkup([[back_button(callback_data, label)]])


def kb_back_cancel(
    back_cb: str,
    cancel_cb: Optional[str] = None,
    back_label: str = "◀️ חזור",
    cancel_label: str = "❌ ביטול",
) -> InlineKeyboardMarkup:
    cancel_cb = cancel_cb or back_cb
    return InlineKeyboardMarkup([
        [back_button(back_cb, back_label), cancel_button(cancel_cb, cancel_label)],
    ])


def kb_confirm_delete(
    confirm_cb: str,
    cancel_cb: str,
    confirm_label: str = "✅ כן, מחק",
    cancel_label: str = "◀️ חזור",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        confirm_button(confirm_cb, confirm_label),
        cancel_button(cancel_cb, cancel_label),
    ]])


def kb_toggle_delete(
    toggle_cb: str,
    delete_cb: str,
    is_active: bool,
    active_label: str = "🔴 השבת",
    inactive_label: str = "🟢 הפעל",
) -> list[InlineKeyboardButton]:
    """שורת הפעלה/כיבוי + מחיקה — מחזיר שורה בודדת."""
    return [
        InlineKeyboardButton(active_label if is_active else inactive_label, callback_data=toggle_cb),
        delete_button(delete_cb),
    ]


def kb_move_row(up_cb: str, down_cb: str) -> list[InlineKeyboardButton]:
    """שורת סדר — תוויות מפורשות למניעת בלבול."""
    return [
        InlineKeyboardButton("⬆️ למעלה", callback_data=up_cb),
        InlineKeyboardButton("⬇️ למטה",  callback_data=down_cb),
    ]


# ---------------------------------------------------------------------------
# עזרי handler
# ---------------------------------------------------------------------------

async def answer_query(update: Update, text: str = "", alert: bool = False) -> None:
    if update.callback_query:
        try:
            await update.callback_query.answer(text, show_alert=alert)
        except Exception:
            pass


async def edit_or_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
    parse_mode: str = "HTML",
) -> None:
    """
    עורך הודעה קיימת כשאפשר — ושולח חדשה כשהעריכה נכשלת.

    כשהעריכה נכשלת (למשל הודעת מדיה קודמת): מוחק תחילה, שולח אחר-כך.
    כך לא מצטברות הודעות בצ'אט בשום מצב.
    """
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text, reply_markup=keyboard, parse_mode=parse_mode
            )
            return
        except Exception:
            await safe_delete_message(update)   # מחק לפני שליחה חדשה

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=keyboard,
        parse_mode=parse_mode,
    )


async def safe_delete_message(update: Update) -> None:
    """מוחק את ההודעה הנוכחית בשקט."""
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass