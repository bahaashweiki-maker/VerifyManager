from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from services.page_service import load_page
from services.message_manager import MessageManager


class PageEngine:

    @staticmethod
    async def show_page(update, context: ContextTypes.DEFAULT_TYPE, page_key: str):

        # מחיקת ההודעה הקודמת של הבוט
        await MessageManager.clear(update, context)

        page = load_page(page_key)

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