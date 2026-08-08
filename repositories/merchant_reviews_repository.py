from __future__ import annotations

import sqlite3
from typing import Optional

from database.database import get_connection


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))


def create_merchant_review(
    merchant_id: int,
    reviewer_id: int,
    reviewer_name: str | None,
    review_text: str,
) -> int:
    text = (review_text or "").strip()
    if merchant_id <= 0 or reviewer_id <= 0 or not text:
        return 0
    with get_connection() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO merchant_reviews (
                    merchant_id,
                    reviewer_id,
                    reviewer_name,
                    review_text,
                    status
                )
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (merchant_id, reviewer_id, (reviewer_name or "").strip() or None, text),
            )
        except sqlite3.OperationalError:
            cur = conn.execute(
                """
                INSERT INTO merchant_reviews (
                    merchant_id,
                    reviewer_id,
                    reviewer_name,
                    review_text
                )
                VALUES (?, ?, ?, ?)
                """,
                (merchant_id, reviewer_id, (reviewer_name or "").strip() or None, text),
            )
        conn.commit()
        return int(cur.lastrowid)


def list_merchant_reviews(merchant_id: int, limit: int = 10) -> list[dict]:
    if merchant_id <= 0:
        return []
    with get_connection() as conn:
        conn.row_factory = _row_factory
        rows = conn.execute(
            """
            SELECT *
            FROM merchant_reviews
            WHERE merchant_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (merchant_id, max(1, int(limit))),
        ).fetchall()
    return rows


def count_merchant_reviews(merchant_id: int) -> int:
    if merchant_id <= 0:
        return 0
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM merchant_reviews WHERE merchant_id = ?",
            (merchant_id,),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def get_latest_merchant_review(merchant_id: int) -> Optional[dict]:
    rows = list_merchant_reviews(merchant_id, limit=1)
    return rows[0] if rows else None


def list_reviews_by_reviewer(reviewer_id: int, limit: int = 10) -> list[dict]:
    if reviewer_id <= 0:
        return []
    with get_connection() as conn:
        conn.row_factory = _row_factory
        rows = conn.execute(
            """
            SELECT *
            FROM merchant_reviews
            WHERE reviewer_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (reviewer_id, max(1, int(limit))),
        ).fetchall()
    return rows


def count_reviews_by_reviewer(reviewer_id: int) -> int:
    if reviewer_id <= 0:
        return 0
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM merchant_reviews WHERE reviewer_id = ?",
            (reviewer_id,),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def get_merchant_review(review_id: int) -> Optional[dict]:
    if review_id <= 0:
        return None
    with get_connection() as conn:
        conn.row_factory = _row_factory
        row = conn.execute(
            "SELECT * FROM merchant_reviews WHERE id = ?",
            (review_id,),
        ).fetchone()
    return row


def list_reviews_by_status(status: str, limit: int = 50) -> list[dict]:
    if not status:
        return []
    with get_connection() as conn:
        conn.row_factory = _row_factory
        rows = conn.execute(
            """
            SELECT *
            FROM merchant_reviews
            WHERE COALESCE(status, 'pending') = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (status, max(1, int(limit))),
        ).fetchall()
    return rows


def count_reviews_by_status(status: str) -> int:
    if not status:
        return 0
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM merchant_reviews WHERE COALESCE(status, 'pending') = ?",
            (status,),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def approve_merchant_review(review_id: int, response_text: str | None = None) -> bool:
    if review_id <= 0:
        return False
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE merchant_reviews
            SET status = 'approved', response_text = ?
            WHERE id = ?
            """,
            ((response_text or "").strip() or None, review_id),
        )
        conn.commit()
    return int(cur.rowcount or 0) > 0


def reject_merchant_review(review_id: int, response_text: str | None = None) -> bool:
    if review_id <= 0:
        return False
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE merchant_reviews
            SET status = 'rejected', response_text = ?
            WHERE id = ?
            """,
            ((response_text or "").strip() or None, review_id),
        )
        conn.commit()
    return int(cur.rowcount or 0) > 0


def delete_merchant_review(review_id: int) -> bool:
    if review_id <= 0:
        return False
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM merchant_reviews WHERE id = ?", (review_id,))
        conn.commit()
    return int(cur.rowcount or 0) > 0


def list_approved_reviews_for_merchant(merchant_id: int, limit: int = 200) -> list[dict]:
    if merchant_id <= 0:
        return []
    with get_connection() as conn:
        conn.row_factory = _row_factory
        rows = conn.execute(
            """
            SELECT *
            FROM merchant_reviews
            WHERE merchant_id = ? AND COALESCE(status, 'pending') = 'approved'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (merchant_id, max(1, int(limit))),
        ).fetchall()
    return rows


def count_approved_reviews_for_merchant(merchant_id: int) -> int:
    if merchant_id <= 0:
        return 0
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM merchant_reviews
            WHERE merchant_id = ? AND COALESCE(status, 'pending') = 'approved'
            """,
            (merchant_id,),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def submit_merchant_reply(review_id: int, merchant_id: int, reply_text: str) -> bool:
    if review_id <= 0 or merchant_id <= 0 or not (reply_text or "").strip():
        return False
    with get_connection() as conn:
        try:
            cur = conn.execute(
                """
                UPDATE merchant_reviews
                SET merchant_reply_text = ?,
                    merchant_reply_status = 'pending',
                    merchant_reply_updated_at = datetime('now'),
                    merchant_reply_admin_note = NULL
                WHERE id = ? AND merchant_id = ? AND COALESCE(status, 'pending') = 'approved'
                """,
                ((reply_text or "").strip(), review_id, merchant_id),
            )
            conn.commit()
        except sqlite3.OperationalError:
            return False
    return int(cur.rowcount or 0) > 0


def approve_merchant_reply(review_id: int, admin_note: str | None = None) -> bool:
    if review_id <= 0:
        return False
    with get_connection() as conn:
        try:
            cur = conn.execute(
                """
                UPDATE merchant_reviews
                SET merchant_reply_status = 'approved',
                    merchant_reply_updated_at = datetime('now'),
                    merchant_reply_admin_note = ?
                WHERE id = ? AND COALESCE(merchant_reply_text, '') <> ''
                """,
                ((admin_note or "").strip() or None, review_id),
            )
            conn.commit()
        except sqlite3.OperationalError:
            return False
    return int(cur.rowcount or 0) > 0


def reject_merchant_reply(review_id: int, admin_note: str | None = None) -> bool:
    if review_id <= 0:
        return False
    with get_connection() as conn:
        try:
            cur = conn.execute(
                """
                UPDATE merchant_reviews
                SET merchant_reply_status = 'rejected',
                    merchant_reply_updated_at = datetime('now'),
                    merchant_reply_admin_note = ?
                WHERE id = ? AND COALESCE(merchant_reply_text, '') <> ''
                """,
                ((admin_note or "").strip() or None, review_id),
            )
            conn.commit()
        except sqlite3.OperationalError:
            return False
    return int(cur.rowcount or 0) > 0


def admin_edit_merchant_reply(
    review_id: int,
    new_reply_text: str,
    keep_status: str = "pending",
) -> bool:
    if review_id <= 0 or not (new_reply_text or "").strip():
        return False
    target_status = keep_status if keep_status in {"pending", "approved", "rejected"} else "pending"
    with get_connection() as conn:
        try:
            cur = conn.execute(
                """
                UPDATE merchant_reviews
                SET merchant_reply_text = ?,
                    merchant_reply_status = ?,
                    merchant_reply_updated_at = datetime('now')
                WHERE id = ?
                """,
                ((new_reply_text or "").strip(), target_status, review_id),
            )
            conn.commit()
        except sqlite3.OperationalError:
            return False
    return int(cur.rowcount or 0) > 0


def count_pending_merchant_replies() -> int:
    with get_connection() as conn:
        try:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM merchant_reviews
                WHERE COALESCE(merchant_reply_status, '') = 'pending'
                """
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
    return int(row[0] or 0) if row else 0


def delete_merchant_reply(review_id: int) -> bool:
    if review_id <= 0:
        return False
    with get_connection() as conn:
        try:
            cur = conn.execute(
                """
                UPDATE merchant_reviews
                SET merchant_reply_text = NULL,
                    merchant_reply_status = NULL,
                    merchant_reply_updated_at = datetime('now'),
                    merchant_reply_admin_note = NULL
                WHERE id = ?
                """,
                (review_id,),
            )
            conn.commit()
        except sqlite3.OperationalError:
            return False
    return int(cur.rowcount or 0) > 0