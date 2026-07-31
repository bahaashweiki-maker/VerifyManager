from __future__ import annotations

from typing import Optional

from database.database import get_connection, now_il


def get_open_chat_for_subscriber(subscriber_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_admin_chats
            WHERE subscriber_id = ?
              AND is_open = 1
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (subscriber_id,),
        )
        return cur.fetchone()


def create_subscriber_chat(subscriber_id: int, admin_id: int) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO subscriber_admin_chats (
                subscriber_id,
                admin_id,
                is_open,
                created_at
            )
            VALUES (?, ?, 1, ?)
            """,
            (subscriber_id, admin_id, now_il().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return int(cur.lastrowid)


def close_subscriber_chat(chat_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE subscriber_admin_chats
            SET is_open = 0,
                closed_at = ?
            WHERE id = ?
            """,
            (now_il().strftime("%Y-%m-%d %H:%M:%S"), chat_id),
        )
        conn.commit()
        return cur.rowcount > 0


def add_chat_message(
    chat_id: int,
    sender_role: str,
    sender_id: int,
    message_text: str,
    file_id: str | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO subscriber_admin_chat_messages (
                chat_id,
                sender_role,
                sender_id,
                message_text,
                file_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chat_id, sender_role, sender_id, message_text, file_id, now_il().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return int(cur.lastrowid)


def reset_subscriber_chat_history(subscriber_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM subscriber_admin_chat_messages
            WHERE chat_id IN (
                SELECT id
                FROM subscriber_admin_chats
                WHERE subscriber_id = ?
            )
            """,
            (subscriber_id,),
        )
        conn.commit()


def count_subscriber_chat_messages(subscriber_id: int, sender_role: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT COUNT(*)
            FROM subscriber_admin_chat_messages m
            JOIN subscriber_admin_chats c ON c.id = m.chat_id
            WHERE c.subscriber_id = ?
              AND m.sender_role = ?
            """,
            (subscriber_id, sender_role),
        )
        return int(cur.fetchone()[0])


def get_subscriber_chats(subscriber_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_admin_chats
            WHERE subscriber_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (subscriber_id,),
        )
        return cur.fetchall()


def get_chat_by_id(chat_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM subscriber_admin_chats WHERE id = ?",
            (chat_id,),
        )
        return cur.fetchone()


def get_chat_messages(chat_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_admin_chat_messages
            WHERE chat_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (chat_id,),
        )
        return cur.fetchall()


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))