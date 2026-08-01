import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from admin import verified_users_admin


def test_message_media_label_for_video_note() -> None:
    assert verified_users_admin._message_media_label("video_note") == "🔵 וידאו עגול"


def test_video_note_does_not_send_automatically_to_admin() -> None:
    update = SimpleNamespace(
        message=SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            photo=None,
            video=None,
            video_note=SimpleNamespace(file_id="video-note-file-id"),
            document=None,
            text=None,
            reply_text=AsyncMock(),
        )
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(
            send_message=AsyncMock(),
            send_video_note=AsyncMock(),
        )
    )

    with patch.object(
        verified_users_admin,
        "get_user_verification_chats",
        return_value=[{"id": 7, "is_open": True, "opened_by": 99, "verification_id": 3}],
    ), patch.object(verified_users_admin, "add_verification_chat_message"), patch.object(
        verified_users_admin,
        "_fmt_admin_name",
        return_value="Admin",
    ):
        result = asyncio.run(verified_users_admin.handle_verification_chat_user_message(update, context))

    assert result is True
    context.bot.send_video_note.assert_not_called()
    context.bot.send_message.assert_called()
