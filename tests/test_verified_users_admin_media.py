import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from admin import subscriptions_admin, verified_users_admin


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
            delete=AsyncMock(),
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


def test_verified_user_media_message_is_deleted_after_successful_storage() -> None:
    update = SimpleNamespace(
        message=SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            photo=[SimpleNamespace(file_id="photo-file-id")],
            video=None,
            video_note=None,
            document=None,
            text=None,
            reply_text=AsyncMock(),
            delete=AsyncMock(),
        )
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(), send_video_note=AsyncMock()))

    with patch.object(
        verified_users_admin,
        "get_user_verification_chats",
        return_value=[{"id": 7, "is_open": True, "opened_by": 99, "verification_id": 3}],
    ), patch.object(verified_users_admin, "add_verification_chat_message") as add_mock, patch.object(
        verified_users_admin,
        "_fmt_admin_name",
        return_value="Admin",
    ):
        result = asyncio.run(verified_users_admin.handle_verification_chat_user_message(update, context))

    assert result is True
    add_mock.assert_called_once()
    update.message.delete.assert_awaited_once()


def test_subscriptions_media_message_is_deleted_after_successful_storage() -> None:
    update = SimpleNamespace(
        message=SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            photo=[SimpleNamespace(file_id="photo-file-id")],
            video=None,
            video_note=None,
            document=None,
            text=None,
            delete=AsyncMock(),
        ),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    with patch("services.subscribers_service.get_subscriber_card_by_telegram_id", return_value={"id": 5, "telegram_id": 42}), patch.object(
        subscriptions_admin,
        "get_open_subscriber_chat",
        return_value={"id": 8, "admin_id": 99},
    ), patch.object(subscriptions_admin, "add_subscriber_chat_message") as add_mock, patch.object(
        subscriptions_admin,
        "track_subscriber_activity",
    ):
        result = asyncio.run(subscriptions_admin.handle_subscriber_user_message(update, context))

    assert result is True
    add_mock.assert_called_once()
    update.message.delete.assert_awaited_once()
