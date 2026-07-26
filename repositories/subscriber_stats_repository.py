from __future__ import annotations

from database.database import get_connection


def get_subscriber_personal_stats(subscriber_id: int) -> dict:
    with get_connection() as conn:
        conn.row_factory = _row_factory

        subscriber = conn.execute(
            "SELECT * FROM subscribers WHERE id = ?",
            (subscriber_id,),
        ).fetchone() or {}

        msgs_from_admin = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_admin_chat_messages m
            JOIN subscriber_admin_chats c ON c.id = m.chat_id
            WHERE c.subscriber_id = ?
              AND m.sender_role = 'admin'
            """,
            (subscriber_id,),
        ).fetchone())

        msgs_from_subscriber = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_admin_chat_messages m
            JOIN subscriber_admin_chats c ON c.id = m.chat_id
            WHERE c.subscriber_id = ?
              AND m.sender_role = 'subscriber'
            """,
            (subscriber_id,),
        ).fetchone())

        sent_publications = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE subscriber_id = ?
              AND event_key IN ('sent', 'delivered')
            """,
            (subscriber_id,),
        ).fetchone())

        publication_clicks = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE subscriber_id = ?
              AND event_key IN ('click', 'button_click')
            """,
            (subscriber_id,),
        ).fetchone())

        activity_events = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_activity_log
            WHERE subscriber_id = ?
            """,
            (subscriber_id,),
        ).fetchone())

        return {
            "joined_at": subscriber.get("joined_at"),
            "first_seen_at": subscriber.get("first_seen_at"),
            "last_seen_at": subscriber.get("last_seen_at"),
            "login_count": int(subscriber.get("login_count") or 0),
            "basic_activity": int(subscriber.get("basic_activity") or 0),
            "activity_events": int(activity_events or 0),
            "messages_sent_to_subscriber": int(msgs_from_admin or 0),
            "messages_received_from_subscriber": int(msgs_from_subscriber or 0),
            "publications_sent": int(sent_publications or 0),
            "publication_button_clicks": int(publication_clicks or 0),
        }


def _read_count(row) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row.get("total") or 0)
    try:
        return int(row[0] or 0)
    except Exception:
        return 0


def get_subscriber_activity(subscriber_id: int, limit: int = 50) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_activity_log
            WHERE subscriber_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (subscriber_id, limit),
        )
        return cur.fetchall()


def get_global_stats_snapshots(limit: int = 30) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_system_stats
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))
