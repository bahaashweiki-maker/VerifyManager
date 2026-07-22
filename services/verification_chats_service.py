from __future__ import annotations

import logging
from typing import Optional

from database.database import get_connection

logger = logging.getLogger(__name__)


def create_verification_chat(telegram_id: int, verification_id: int, opened_by: int) -> Optional[int]:
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO verification_chats
                    (telegram_id, verification_id, opened_by, is_open)
                VALUES (?, ?, ?, 1)
                """,
                (telegram_id, verification_id, opened_by),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as exc:
        logger.error("create_verification_chat failed: %s", exc)
        return None


def get_user_verification_chats(telegram_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM verification_chats
            WHERE telegram_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (telegram_id,),
        )
        return cur.fetchall()


def get_verification_chat(chat_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM verification_chats WHERE id = ?",
            (chat_id,),
        )
        return cur.fetchone()


def close_verification_chat(chat_id: int) -> bool:
    try:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE verification_chats
                SET is_open = 0, closed_at = datetime('now')
                WHERE id = ?
                """,
                (chat_id,),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("close_verification_chat failed: %s", exc)
        return False


def add_verification_chat_message(
    chat_id: int,
    sender_role: str,
    message_type: str,
    content_text: str | None = None,
    file_id: str | None = None,
) -> bool:
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO verification_chat_messages
                    (chat_id, sender_role, message_type, content_text, file_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, sender_role, message_type, content_text, file_id),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("add_verification_chat_message failed: %s", exc)
        return False


def get_verification_chat_messages(chat_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM verification_chat_messages
            WHERE chat_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (chat_id,),
        )
        return cur.fetchall()


def get_verification_chat_message(message_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM verification_chat_messages WHERE id = ?",
            (message_id,),
        )
        return cur.fetchone()


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))
