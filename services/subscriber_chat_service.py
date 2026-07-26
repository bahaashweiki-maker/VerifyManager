from __future__ import annotations

from repositories.subscriber_chats_repository import (
    get_subscriber_chats,
    get_chat_by_id,
    get_chat_messages,
    get_open_chat_for_subscriber,
    create_subscriber_chat,
    close_subscriber_chat,
    add_chat_message,
    reset_subscriber_chat_history,
    count_subscriber_chat_messages,
)


def list_subscriber_chats(subscriber_id: int) -> list:
    return get_subscriber_chats(subscriber_id)


def get_subscriber_chat(chat_id: int):
    return get_chat_by_id(chat_id)


def get_subscriber_chat_history(chat_id: int) -> list:
    return get_chat_messages(chat_id)


def get_open_subscriber_chat(subscriber_id: int):
    return get_open_chat_for_subscriber(subscriber_id)


def open_subscriber_chat(subscriber_id: int, admin_id: int) -> int:
    existing = get_open_chat_for_subscriber(subscriber_id)
    if existing:
        return int(existing["id"])
    return create_subscriber_chat(subscriber_id=subscriber_id, admin_id=admin_id)


def close_chat(chat_id: int) -> bool:
    return close_subscriber_chat(chat_id)


def add_subscriber_chat_message(
    chat_id: int,
    sender_role: str,
    sender_id: int,
    message_text: str,
    file_id: str | None = None,
) -> int:
    return add_chat_message(
        chat_id=chat_id,
        sender_role=sender_role,
        sender_id=sender_id,
        message_text=message_text,
        file_id=file_id,
    )


def clear_subscriber_chat_history(subscriber_id: int) -> None:
    reset_subscriber_chat_history(subscriber_id)


def count_messages_to_subscriber(subscriber_id: int) -> int:
    return count_subscriber_chat_messages(subscriber_id=subscriber_id, sender_role="admin")


def count_messages_from_subscriber(subscriber_id: int) -> int:
    return count_subscriber_chat_messages(subscriber_id=subscriber_id, sender_role="subscriber")
