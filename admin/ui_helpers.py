"""
admin/ui_helpers.py
---------------------
רכיבי UI גנריים לשימוש בכל מודולי האדמין של הבוט.

ייבוא מכל handler:
    from admin.ui_helpers import (
        back_button, cancel_button,
        kb_back, kb_cancel, kb_confirm_delete,
        answer_query, edit_or_send,
    )

הוסף כאן כל רכיב UI שמשמש יותר ממודול אחד.
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
# כפתורים גנריים — building blocks
# ---------------------------------------------------------------------------

def back_button(callback_data: str, label: str = "◀️ חזור") -> InlineKeyboardButton:
    """כפתור חזרה גנרי."""
    return InlineKeyboardButton(label, callback_data=callback_data)


def cancel_button(callback_data: str, label: str = "❌ ביטול") -> InlineKeyboardButton:
    """כפתור ביטול גנרי."""
    return InlineKeyboardButton(label, callback_data=callback_data)


def delete_button(callback_data: str, label: str = "🗑 מחק") -> InlineKeyboardButton:
    """כפתור מחיקה גנרי."""
    return InlineKeyboardButton(label, callback_data=callback_data)


def confirm_button(callback_data: str, label: str = "✅ כן, מחק") -> InlineKeyboardButton:
    """כפתור אישור מחיקה גנרי."""
    return InlineKeyboardButton(label, callback_data=callback_data)


# ---------------------------------------------------------------------------
# מקלדות גנריות — מוכנות לשליחה
# ---------------------------------------------------------------------------

def kb_back(callback_data: str, label: str = "◀️ חזור") -> InlineKeyboardMarkup:
    """מקלדת עם כפתור חזרה בלבד."""
    return InlineKeyboardMarkup([[back_button(callback_data, label)]])


def kb_cancel(callback_data: str, label: str = "❌ ביטול") -> InlineKeyboardMarkup:
    """מקלדת עם כפתור ביטול בלבד."""
    return InlineKeyboardMarkup([[cancel_button(callback_data, label)]])


def kb_back_cancel(
    back_cb: str,
    cancel_cb: Optional[str] = None,
    back_label: str = "◀️ חזור",
    cancel_label: str = "❌ ביטול",
) -> InlineKeyboardMarkup:
    """
    מקלדת עם חזרה וביטול.

    אם cancel_cb לא נמסר — משתמש ב-back_cb גם לביטול.
    """
    cancel_cb = cancel_cb or back_cb
    return InlineKeyboardMarkup([
        [back_button(back_cb, back_label), cancel_button(cancel_cb, cancel_label)],
    ])


def kb_confirm_delete(
    confirm_cb: str,
    cancel_cb: str,
    confirm_label: str = "✅ כן, מחק",
    cancel_label: str = "❌ ביטול",
) -> InlineKeyboardMarkup:
    """
    דיאלוג אישור מחיקה גנרי.

    Parameters:
        confirm_cb:    callback_data לאישור המחיקה.
        cancel_cb:     callback_data לביטול.
        confirm_label: תווית לכפתור האישור.
        cancel_label:  תווית לכפתור הביטול.
    """
    return InlineKeyboardMarkup([
        [
            confirm_button(confirm_cb, confirm_label),
            cancel_button(cancel_cb, cancel_label),
        ]
    ])


def kb_toggle_delete(
    toggle_cb: str,
    delete_cb: str,
    is_active: bool,
    active_label: str = "🔴 השבת",
    inactive_label: str = "🟢 הצג",
) -> list[InlineKeyboardButton]:
    """
    שורה עם כפתורי הפעלה/כיבוי + מחיקה.

    מחזיר list[InlineKeyboardButton] (שורה) — הוסף לרשימת הrows.
    """
    toggle_label = active_label if is_active else inactive_label
    return [
        InlineKeyboardButton(toggle_label, callback_data=toggle_cb),
        delete_button(delete_cb),
    ]


def kb_move_row(
    up_cb: str,
    down_cb: str,
    left_cb: Optional[str] = None,
    right_cb: Optional[str] = None,
) -> list[InlineKeyboardButton]:
    """
    שורה עם כפתורי הזזה.

    up_cb / down_cb    — חובה: מעביר לשורה מעל/מתחת (שינוי row_index).
    left_cb / right_cb — אופציונלי: מחליף עם שכן שמאל/ימין באותה שורה
                         (swap sort_order בתוך row_index).

    סדר הכפתורים בשורה (כשכולם נמסרים): ⬅️ ⬆️ ⬇️ ➡️

    מחזיר list[InlineKeyboardButton] — הוסף לרשימת הrows.
    """
    row: list[InlineKeyboardButton] = []
    if left_cb:
        row.append(InlineKeyboardButton("⬅️", callback_data=left_cb))
    row.append(InlineKeyboardButton("⬆️", callback_data=up_cb))
    row.append(InlineKeyboardButton("⬇️", callback_data=down_cb))
    if right_cb:
        row.append(InlineKeyboardButton("➡️", callback_data=right_cb))
    return row


# ---------------------------------------------------------------------------
# עזרי handler — שגרות חוזרות
# ---------------------------------------------------------------------------

async def answer_query(update: Update, text: str = "", alert: bool = False) -> None:
    """
    סוגר callback query בשקט.

    Parameters:
        text:  הודעת toast (אופציונלי).
        alert: אם True — מוצג כ-alert popup.
    """
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
    עורך את ההודעה הקיימת (callback query) או שולח חדשה (command / message).

    שימושי בכניסה ל-handler שיכולה לבוא גם כ-/command וגם כ-callback.
    """
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text, reply_markup=keyboard, parse_mode=parse_mode
            )
            return
        except Exception:
            pass  # אם העריכה נכשלת — שולח הודעה חדשה

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=keyboard,
        parse_mode=parse_mode,
    )


async def safe_delete_message(update: Update) -> None:
    """מוחק את ההודעה הנוכחית בשקט (ללא חריגה אם נכשל)."""
    if update.callback_query:
        try:
            await update.callback_query.delete_message()
        except Exception:
            pass