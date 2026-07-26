from __future__ import annotations

from typing import Optional

from database.database import get_connection


def get_all_subscribers(limit: int = 50) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscribers
            ORDER BY joined_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def get_subscribers_page(page: int, per_page: int = 10) -> list:
    offset = max(page, 1)
    offset = (offset - 1) * per_page
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscribers
            ORDER BY joined_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        )
        return cur.fetchall()


def get_subscribers_count() -> int:
    with get_connection() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM subscribers")
        return int(cur.fetchone()[0])


def get_subscriber_by_telegram_id(telegram_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM subscribers WHERE telegram_id = ?",
            (telegram_id,),
        )
        return cur.fetchone()


def touch_subscriber(
    telegram_id: int,
    full_name: Optional[str],
    username: Optional[str],
) -> dict:
    with get_connection() as conn:
        ins = conn.execute(
            """
            INSERT OR IGNORE INTO subscribers (
                telegram_id,
                full_name,
                username,
                first_seen_at,
                last_seen_at,
                login_count
            )
            VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)
            """,
            (telegram_id, full_name, username),
        )

        if ins.rowcount == 0:
            conn.execute(
                """
                UPDATE subscribers
                SET
                    full_name = COALESCE(?, full_name),
                    username = COALESCE(?, username),
                    last_seen_at = datetime('now'),
                    login_count = login_count + 1
                WHERE telegram_id = ?
                """,
                (full_name, username, telegram_id),
            )

        conn.commit()

        conn.row_factory = _row_factory
        out = conn.execute(
            "SELECT * FROM subscribers WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return out or {}


def search_subscribers(term: str, limit: int = 50) -> list:
    pattern = f"%{term}%"
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscribers
            WHERE CAST(telegram_id AS TEXT) LIKE ?
               OR COALESCE(full_name, '') LIKE ?
               OR COALESCE(username, '') LIKE ?
            ORDER BY joined_at DESC, id DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        )
        return cur.fetchall()


def search_subscribers_page(term: str, page: int, per_page: int = 10) -> list:
    pattern = f"%{term}%"
    offset = max(page, 1)
    offset = (offset - 1) * per_page
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscribers
            WHERE CAST(telegram_id AS TEXT) LIKE ?
               OR COALESCE(full_name, '') LIKE ?
               OR COALESCE(username, '') LIKE ?
            ORDER BY joined_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (pattern, pattern, pattern, per_page, offset),
        )
        return cur.fetchall()


def count_subscribers_search(term: str) -> int:
    pattern = f"%{term}%"
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT COUNT(*)
            FROM subscribers
            WHERE CAST(telegram_id AS TEXT) LIKE ?
               OR COALESCE(full_name, '') LIKE ?
               OR COALESCE(username, '') LIKE ?
            """,
            (pattern, pattern, pattern),
        )
        return int(cur.fetchone()[0])


def get_subscriber_by_id(subscriber_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            "SELECT * FROM subscribers WHERE id = ?",
            (subscriber_id,),
        )
        return cur.fetchone()


def set_subscriber_status(subscriber_id: int, status: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE subscribers SET status = ? WHERE id = ?",
            (status, subscriber_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_subscriber(subscriber_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM subscribers WHERE id = ?",
            (subscriber_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))
