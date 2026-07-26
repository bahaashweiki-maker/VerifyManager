from __future__ import annotations

from database.database import get_connection


def get_all_publications(limit: int = 50) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publications
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def get_publication_buttons(publication_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publication_buttons
            WHERE publication_id = ?
            ORDER BY order_index ASC, id ASC
            """,
            (publication_id,),
        )
        return cur.fetchall()


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))
