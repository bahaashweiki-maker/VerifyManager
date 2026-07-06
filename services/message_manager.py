from telegram import Update
from telegram.ext import ContextTypes


class MessageManager:

    @staticmethod
    async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):

        chat_id = update.effective_chat.id

        last_message = context.user_data.get("last_message")

        if last_message:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=last_message
                )
            except:
                pass

    @staticmethod
    def save(context: ContextTypes.DEFAULT_TYPE, message_id: int):

        context.user_data["last_message"] = message_id