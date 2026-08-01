from __future__ import annotations

import sqlite3
from typing import Optional

from database.database import get_connection, now_il


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


def get_publication_by_id(publication_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publications
            WHERE id = ?
            """,
            (publication_id,),
        )
        return cur.fetchone()


def create_publication(
    *,
    title: str | None,
    content_text: str | None,
    media_type: str | None,
    file_id: str | None,
    target_type: str,
    target_value: str | None,
    status: str,
    created_by: int | None,
    scheduled_at: str | None = None,
    is_recurring: int = 0,
    repeat_every_minutes: int | None = None,
    recurrence_type: str | None = None,
    recurrence_weekdays: str | None = None,
    recurrence_day_of_month: int | None = None,
    recurrence_time: str | None = None,
    next_run_at: str | None = None,
    auto_delete_minutes: int | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO subscriber_publications (
                title,
                content_text,
                media_type,
                file_id,
                target_type,
                target_value,
                status,
                scheduled_at,
                created_by,
                is_recurring,
                repeat_every_minutes,
                recurrence_type,
                recurrence_weekdays,
                recurrence_day_of_month,
                recurrence_time,
                next_run_at,
                auto_delete_minutes,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                title,
                content_text,
                media_type,
                file_id,
                target_type,
                target_value,
                status,
                scheduled_at,
                created_by,
                is_recurring,
                repeat_every_minutes,
                recurrence_type,
                recurrence_weekdays,
                recurrence_day_of_month,
                recurrence_time,
                next_run_at,
                auto_delete_minutes,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_publication(publication_id: int, **fields) -> bool:
    if not fields:
        return False

    allowed = {
        "title",
        "content_text",
        "media_type",
        "file_id",
        "target_type",
        "target_value",
        "status",
        "scheduled_at",
        "auto_delete_at",
        "is_recurring",
        "repeat_every_minutes",
        "recurrence_type",
        "recurrence_weekdays",
        "recurrence_day_of_month",
        "recurrence_time",
        "next_run_at",
        "last_sent_at",
        "sent_success_count",
        "sent_fail_count",
        "total_targets",
        "auto_delete_minutes",
    }
    clean_items = [(k, v) for k, v in fields.items() if k in allowed]
    if not clean_items:
        return False

    set_sql = ", ".join([f"{k} = ?" for k, _ in clean_items] + ["updated_at = datetime('now')"])
    values = [v for _, v in clean_items] + [publication_id]

    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE subscriber_publications SET {set_sql} WHERE id = ?",
            tuple(values),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_publication(publication_id: int) -> bool:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM subscriber_publication_deliveries WHERE publication_id = ?",
            (publication_id,),
        )
        conn.execute(
            "DELETE FROM subscriber_publication_buttons WHERE publication_id = ?",
            (publication_id,),
        )
        conn.execute(
            "DELETE FROM subscriber_publication_stats WHERE publication_id = ?",
            (publication_id,),
        )
        cur = conn.execute(
            "DELETE FROM subscriber_publications WHERE id = ?",
            (publication_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def count_publications(search: str = "", status: str | None = None) -> int:
    where = []
    params: list = []

    if search.strip():
        pattern = f"%{search.strip()}%"
        where.append("(COALESCE(title, '') LIKE ? OR COALESCE(content_text, '') LIKE ?)")
        params.extend([pattern, pattern])

    if status:
        where.append("status = ?")
        params.append(status)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with get_connection() as conn:
        cur = conn.execute(
            f"SELECT COUNT(*) FROM subscriber_publications {where_sql}",
            tuple(params),
        )
        return int(cur.fetchone()[0])


def list_publications_page(
    *,
    page: int,
    per_page: int,
    search: str = "",
    status: str | None = None,
) -> list:
    where = []
    params: list = []

    if search.strip():
        pattern = f"%{search.strip()}%"
        where.append("(COALESCE(title, '') LIKE ? OR COALESCE(content_text, '') LIKE ?)")
        params.extend([pattern, pattern])

    if status:
        where.append("status = ?")
        params.append(status)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    offset = max(page, 1)
    offset = (offset - 1) * per_page

    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            f"""
            SELECT *
            FROM subscriber_publications
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [per_page, offset]),
        )
        return cur.fetchall()


def replace_publication_buttons(publication_id: int, buttons: list[dict]) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM subscriber_publication_buttons WHERE publication_id = ?",
            (publication_id,),
        )
        for idx, b in enumerate(buttons):
            title = (b.get("title") or "").strip()
            url = (b.get("url") or "").strip()
            if not title or not url:
                continue
            conn.execute(
                """
                INSERT INTO subscriber_publication_buttons (publication_id, title, url, order_index)
                VALUES (?, ?, ?, ?)
                """,
                (publication_id, title, url, idx),
            )
        conn.commit()


def record_publication_stat(publication_id: int, subscriber_id: int | None, event_key: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO subscriber_publication_stats (publication_id, subscriber_id, event_key)
            VALUES (?, ?, ?)
            """,
            (publication_id, subscriber_id, event_key),
        )
        conn.commit()


def get_due_scheduled_publications(now_iso: str) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publications
            WHERE status = 'scheduled'
              AND scheduled_at IS NOT NULL
              AND scheduled_at <= ?
            ORDER BY scheduled_at ASC, id ASC
            """,
            (now_iso,),
        )
        return cur.fetchall()


def get_active_recurring_publications() -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publications
            WHERE status = 'active'
              AND is_recurring = 1
              AND repeat_every_minutes IS NOT NULL
            ORDER BY id DESC
            """
        )
        return cur.fetchall()


def increment_publication_delivery(publication_id: int, success_count: int, fail_count: int, total_targets: int) -> None:
    now_str = now_il().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE subscriber_publications
            SET sent_success_count = COALESCE(sent_success_count, 0) + ?,
                sent_fail_count = COALESCE(sent_fail_count, 0) + ?,
                total_targets = ?,
                last_sent_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (success_count, fail_count, total_targets, now_str, now_str, publication_id),
        )
        conn.commit()


def get_publication_stats_summary(publication_id: int) -> dict:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        pub = conn.execute(
            "SELECT * FROM subscriber_publications WHERE id = ?",
            (publication_id,),
        ).fetchone() or {}
        rows = conn.execute(
            """
            SELECT event_key, COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE publication_id = ?
            GROUP BY event_key
            """,
            (publication_id,),
        ).fetchall()
        by_event = {r["event_key"]: int(r["total"]) for r in rows}
        return {
            "publication": pub,
            "events": by_event,
        }


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


def create_publication_delivery(
    *,
    publication_id: int,
    subscriber_id: int | None,
    telegram_id: int,
    message_id: int,
    delete_at: str | None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO subscriber_publication_deliveries (
                publication_id,
                subscriber_id,
                telegram_id,
                message_id,
                delete_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (publication_id, subscriber_id, telegram_id, message_id, delete_at),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_pending_publication_deliveries(publication_id: int) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publication_deliveries
            WHERE publication_id = ?
              AND status = 'pending'
            ORDER BY id ASC
            """,
            (publication_id,),
        )
        return cur.fetchall()


def list_due_publication_deletions(now_iso: str) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publication_deliveries
            WHERE status = 'pending'
              AND delete_at IS NOT NULL
              AND delete_at <= ?
            ORDER BY delete_at ASC, id ASC
            """,
            (now_iso,),
        )
        return cur.fetchall()


def list_pending_publication_deletions() -> list:
        with get_connection() as conn:
                conn.row_factory = _row_factory
                cur = conn.execute(
                        """
                        SELECT *
                        FROM subscriber_publication_deliveries
                        WHERE status = 'pending'
                            AND delete_at IS NOT NULL
                        ORDER BY delete_at ASC, id ASC
                        """
                )
                return cur.fetchall()


def get_publication_delivery_by_id(delivery_id: int) -> Optional[dict]:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_publication_deliveries
            WHERE id = ?
            """,
            (delivery_id,),
        )
        return cur.fetchone()


def mark_publication_delivery_status(delivery_id: int, status: str) -> bool:
    with get_connection() as conn:
        if status == "deleted":
            cur = conn.execute(
                """
                UPDATE subscriber_publication_deliveries
                SET status = ?, deleted_at = datetime('now')
                WHERE id = ?
                """,
                (status, delivery_id),
            )
        else:
            cur = conn.execute(
                """
                UPDATE subscriber_publication_deliveries
                SET status = ?
                WHERE id = ?
                """,
                (status, delivery_id),
            )
        conn.commit()
        return cur.rowcount > 0


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))
