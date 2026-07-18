from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from services.page_service import load_page
from services.message_manager import MessageManager

# ──────────────────────────────────────────────────────────────────────────────
# ניווט: מעקב היסטוריה ב-context.user_data
#
# _BACK_PREFIX  — prefix ל-callback_data של כפתורי ⬅️ חזור.
#                 callback_data = "_back:{page_key_to_return_to}"
#                 bot.py אינו מטפל בו ישירות — נופל ל-PageEngine.show_page.
#
# _NAV_STACK    — מפתח ב-context.user_data לשמירת רשימת הניווט (list[str]).
#                 כל כניסה לעמוד חדש מוסיפה אותו לרשימה.
#                 לחיצה על ⬅️ מסירה את הרמה הנוכחית מהרשימה.
# ──────────────────────────────────────────────────────────────────────────────
_BACK_PREFIX  = "_back:"
_NAV_STACK    = "_nav_stack"


class PageEngine:

    @staticmethod
    async def show_page(update, context: ContextTypes.DEFAULT_TYPE, page_key: str):

        # מחיקת ההודעה הקודמת של הבוט
        await MessageManager.clear(update, context)

        # ── ניהול stack ניווט ────────────────────────────────────────────────
        is_back    = page_key.startswith(_BACK_PREFIX)
        actual_key = page_key[len(_BACK_PREFIX):] if is_back else page_key

        stack: list = list(context.user_data.get(_NAV_STACK, []))

        if is_back:
            # חזרה: מסיר את הרמה הנוכחית מה-stack
            if stack:
                stack.pop()
        else:
            # קדימה: מוסיף רק אם שונה מהרמה הנוכחית (מניעת כפילות)
            if not stack or stack[-1] != actual_key:
                stack.append(actual_key)

        context.user_data[_NAV_STACK] = stack

        # callback לכפתור ⬅️ חזור
        if len(stack) >= 2:
            back_cb = f"{_BACK_PREFIX}{stack[-2]}"   # עמוד קודם
        else:
            back_cb = "HOME"                          # מטופל ב-bot.py → render_home
        # ─────────────────────────────────────────────────────────────────────

        page = load_page(actual_key)

        if not page:
            if update.callback_query:
                await update.callback_query.answer()
                sent = await update.callback_query.message.reply_text(
                    "❌ העמוד לא נמצא."
                )
            else:
                sent = await update.message.reply_text(
                    "❌ העמוד לא נמצא."
                )

            MessageManager.save(context, sent.message_id)
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    btn["title"],
                    callback_data=btn["target_page"]
                )
            ]
            for btn in page.get("buttons", [])
        ]

        # כפתור ⬅️ חזור — מוצג תמיד בתחתית המקלדת
        keyboard.append([InlineKeyboardButton("⬅️ חזור", callback_data=back_cb)])

        markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:

            await update.callback_query.answer()

            sent = await context.bot.send_message(
                chat_id=update.callback_query.message.chat_id,
                text=page["text"],
                reply_markup=markup,
                parse_mode="HTML"
            )

        else:

            sent = await update.message.reply_text(
                page["text"],
                reply_markup=markup,
                parse_mode="HTML"
            )

        MessageManager.save(context, sent.message_id)
