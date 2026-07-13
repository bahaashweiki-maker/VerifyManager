from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import ContextTypes

from services.verify_admin_service import (
    get_verification_by_id,
)


async def verify_media_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    # ======================================
    # הצגת תעודת זהות
    # ======================================

    if data.startswith("VIEW_ID_"):

        verification_id = int(data.split("_")[-1])

        verify = get_verification_by_id(verification_id)

        if not verify:
            await query.answer(
                "❌ האימות לא נמצא.",
                show_alert=True
            )
            return

        if not verify["id_photo"]:
            await query.answer(
                "⚠️ אין תמונת תעודת זהות.",
                show_alert=True
            )
            return

        # שמירת message_id של הודעת פרטי האימות — ייחודי לפי מזהה האימות
        context.user_data[f"verify_detail_msg_id_{verification_id}"] = query.message.message_id

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזור", callback_data=f"MEDIA_BACK_{verification_id}")]
        ])

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=verify["id_photo"],
            caption=(
                f"🪪 תעודת זהות\n"
                f"אימות #{verify['id']}"
            ),
            reply_markup=keyboard
        )

        return

    # ======================================
    # הצגת סלפי
    # ======================================

    if data.startswith("VIEW_SELFIE_"):

        verification_id = int(data.split("_")[-1])

        verify = get_verification_by_id(verification_id)

        if not verify:
            await query.answer(
                "❌ האימות לא נמצא.",
                show_alert=True
            )
            return

        if not verify["selfie"]:
            await query.answer(
                "⚠️ אין סלפי.",
                show_alert=True
            )
            return

        # שמירת message_id של הודעת פרטי האימות — ייחודי לפי מזהה האימות
        context.user_data[f"verify_detail_msg_id_{verification_id}"] = query.message.message_id

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזור", callback_data=f"MEDIA_BACK_{verification_id}")]
        ])

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=verify["selfie"],
            caption=(
                f"🤳 סלפי\n"
                f"אימות #{verify['id']}"
            ),
            reply_markup=keyboard
        )

        return

    # ======================================
    # הצגת צילום מסך
    # ======================================

    if data.startswith("VIEW_SOCIAL_"):

        verification_id = int(data.split("_")[-1])

        verify = get_verification_by_id(verification_id)

        if not verify:
            await query.answer(
                "❌ האימות לא נמצא.",
                show_alert=True
            )
            return

        if not verify["social"]:
            await query.answer(
                "⚠️ אין צילום מסך.",
                show_alert=True
            )
            return

        # שמירת message_id של הודעת פרטי האימות — ייחודי לפי מזהה האימות
        context.user_data[f"verify_detail_msg_id_{verification_id}"] = query.message.message_id

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזור", callback_data=f"MEDIA_BACK_{verification_id}")]
        ])

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=verify["social"],
            caption=(
                f"📱 צילום מסך\n"
                f"אימות #{verify['id']}"
            ),
            reply_markup=keyboard
        )

        return

    # ======================================
    # הצגת סרטון
    # ======================================

    if data.startswith("VIEW_VIDEO_"):

        verification_id = int(data.split("_")[-1])

        verify = get_verification_by_id(verification_id)

        if not verify:
            await query.answer(
                "❌ האימות לא נמצא.",
                show_alert=True
            )
            return

        if not verify["video"]:
            await query.answer(
                "⚠️ אין סרטון.",
                show_alert=True
            )
            return

        # שמירת message_id של הודעת פרטי האימות — ייחודי לפי מזהה האימות
        context.user_data[f"verify_detail_msg_id_{verification_id}"] = query.message.message_id

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ חזור", callback_data=f"MEDIA_BACK_{verification_id}")]
        ])

        await context.bot.send_video(
            chat_id=query.message.chat_id,
            video=verify["video"],
            caption=(
                f"🎥 סרטון אימות\n"
                f"אימות #{verify['id']}"
            ),
            reply_markup=keyboard
        )

        return

    # ======================================
    # לא נמצא Callback מתאים
    # ======================================

    await query.answer(
        "⚠️ פעולה לא קיימת.",
        show_alert=True
    )
